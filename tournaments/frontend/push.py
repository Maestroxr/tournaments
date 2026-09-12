"""Opt-in Web Push, with durable per-device match-ready delivery."""
import base64
import hashlib
import json
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import PushDelivery, PushSubscription, TablePushDelivery


def configured():
    return bool(getattr(settings, 'WEB_PUSH_PUBLIC_KEY', '') and
                getattr(settings, 'WEB_PUSH_PRIVATE_KEY', '') and
                getattr(settings, 'WEB_PUSH_SUBJECT', ''))


def endpoint_allowed(endpoint):
    try:
        parsed = urlsplit(endpoint)
        host = parsed.hostname or ''
        trusted = (host in ('fcm.googleapis.com', 'web.push.apple.com') or
                   host.endswith('.push.services.mozilla.com') or
                   host.endswith('.notify.windows.com'))
        return (len(endpoint) <= 2048 and parsed.scheme == 'https' and
                not parsed.username and not parsed.password and not parsed.fragment and
                parsed.port in (None, 443) and trusted)
    except (ValueError, TypeError):
        return False


def validate_subscription(data):
    endpoint = data.get('endpoint')
    if not isinstance(endpoint, str) or not endpoint_allowed(endpoint):
        raise ValueError('Unsupported push service endpoint.')
    keys = data.get('keys')
    if not isinstance(keys, dict):
        raise ValueError('Subscription keys are required.')
    for key, size in (('p256dh', 65), ('auth', 16)):
        value = keys.get(key)
        try:
            raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
            if len(raw) != size or (key == 'p256dh' and raw[0] != 4):
                raise ValueError()
        except (TypeError, ValueError):
            raise ValueError('Invalid subscription key.') from None
    return endpoint, keys


@require_http_methods(['GET'])
def config(request):
    if not request.user.is_authenticated:
        return JsonResponse({'detail': 'Authentication required'}, status=401)
    return JsonResponse({'enabled': configured(), 'publicKey': getattr(settings, 'WEB_PUSH_PUBLIC_KEY', '') if configured() else ''})


@require_http_methods(['POST', 'DELETE'])
def subscription(request):
    if not request.user.is_authenticated:
        return JsonResponse({'detail': 'Authentication required'}, status=401)
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError()
        endpoint = data.get('endpoint')
        if not isinstance(endpoint, str) or len(endpoint) > 2048:
            raise ValueError()
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'detail': 'Invalid subscription'}, status=400)
    digest = hashlib.sha256(endpoint.encode()).hexdigest()
    if request.method == 'DELETE':
        PushSubscription.objects.filter(user=request.user, endpoint_hash=digest).delete()
        return JsonResponse({'subscribed': False})
    if not configured():
        return JsonResponse({'detail': 'Phone notifications are not configured yet.'}, status=503)
    try:
        endpoint, keys = validate_subscription(data)
    except ValueError as error:
        return JsonResponse({'detail': str(error)}, status=400)
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        existing = PushSubscription.objects.select_for_update().filter(endpoint_hash=digest).first()
        if (not existing or existing.user_id != request.user.pk) and request.user.push_subscriptions.count() >= 10:
            return JsonResponse({'detail': 'Maximum of 10 devices reached.'}, status=400)
        if existing and existing.user_id != request.user.pk:
            PushDelivery.objects.filter(subscription=existing).delete()
        PushSubscription.objects.update_or_create(endpoint_hash=digest, defaults={
            'user': request.user, 'endpoint': endpoint, 'p256dh': keys['p256dh'], 'auth': keys['auth'],
            'language': 'en' if data.get('language') == 'en' else 'he',
        })
    return JsonResponse({'subscribed': True})


def discover_ready_matches():
    """Worker discovers newly playable fixtures even when the website is closed."""
    from tournaments.models import Tournament
    from gamelink.views import playable_seat
    if not configured() or not settings.GAMELINK_ENABLED:
        return 0
    created = 0
    for tournament in Tournament.objects.filter(published=True, stages__fixtures__isnull=False).distinct():
        stage = tournament.current_stage
        if stage is None:
            continue
        fixtures = stage.current_fixtures
        if fixtures is None:
            continue
        for fixture in fixtures.select_related('player1__user', 'player2__user'):
            for player in (fixture.player1, fixture.player2):
                if not player or not player.user_id or playable_seat(player.user, fixture)[0] is None:
                    continue
                for device in PushSubscription.objects.filter(user_id=player.user_id):
                    _, new = PushDelivery.objects.get_or_create(subscription=device, fixture=fixture,
                                                               defaults={'next_attempt_at': timezone.now()})
                    created += int(new)
    return created


def queue_table_push(table, *, kind, recipient_id):
    """Queue an opt-in notification for a direct-play table event."""
    if not configured() or not table.guest_id:
        return 0
    created = 0
    for device in PushSubscription.objects.filter(user_id=recipient_id):
        _, new = TablePushDelivery.objects.get_or_create(
            subscription=device,
            table=table,
            kind=kind,
            defaults={'next_attempt_at': timezone.now()},
        )
        created += int(new)
    return created


def queue_guest_joined_push(table):
    return queue_table_push(
        table,
        kind=TablePushDelivery.KIND_GUEST_JOINED,
        recipient_id=table.host_id,
    )


def queue_host_entered_push(table):
    return queue_table_push(
        table,
        kind=TablePushDelivery.KIND_HOST_ENTERED,
        recipient_id=table.guest_id,
    )


def send_notification(device, payload):
    # Keep provider encryption/signing in the maintained Web Push library.
    import requests
    from pywebpush import webpush
    class NoRedirectSession(requests.Session):
        def request(self, *args, **kwargs):
            kwargs['allow_redirects'] = False
            return super().request(*args, **kwargs)
    if not endpoint_allowed(device.endpoint):
        raise ValueError('Unsupported push endpoint')
    with NoRedirectSession() as session:
        response = webpush(
            subscription_info={'endpoint': device.endpoint, 'keys': {'p256dh': device.p256dh, 'auth': device.auth}},
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=settings.WEB_PUSH_PRIVATE_KEY,
            vapid_claims={'sub': settings.WEB_PUSH_SUBJECT},
            ttl=300, timeout=10, requests_session=session,
        )
        if not 200 <= response.status_code < 300:
            raise ValueError('Push service rejected delivery')


def deliver_pending(limit=100, heartbeat=None):
    from gamelink.views import playable_seat
    if not configured():
        return 0
    sent = 0
    due = PushDelivery.objects.filter(delivered_at=None, discarded_at=None, attempts__lt=5,
                                     next_attempt_at__lte=timezone.now()).order_by('pk')
    for delivery_id in list(due.values_list('pk', flat=True)[:limit]):
        if heartbeat:
            heartbeat()
        now = timezone.now()
        # Atomic lease prevents two workers sending the same item concurrently.
        claimed = PushDelivery.objects.filter(pk=delivery_id, delivered_at=None, discarded_at=None,
            next_attempt_at__lte=now, attempts__lt=5).update(attempts=F('attempts') + 1, next_attempt_at=now + timedelta(seconds=60))
        if not claimed:
            continue
        delivery = PushDelivery.objects.select_related('subscription__user', 'fixture__mode__tournament').filter(pk=delivery_id).first()
        if not delivery:
            continue
        device = delivery.subscription
        if playable_seat(device.user, delivery.fixture)[0] is None:
            PushDelivery.objects.filter(pk=delivery_id).update(discarded_at=now)
            continue
        name = delivery.fixture.mode.tournament.name
        english = device.language == 'en'
        payload = {
            'title': 'Your match is ready' if english else 'המשחק שלך מוכן',
            'body': f'{name} — open the club to join.' if english else f'{name} — פתח את המועדון כדי להיכנס למשחק.',
            'url': f'/tournaments/tournaments/{delivery.fixture.mode.tournament_id}',
            'tag': f'match-ready:{delivery.fixture_id}',
        }
        try:
            send_notification(device, payload)
        except Exception as error:
            response = getattr(error, 'response', None)
            status = getattr(response, 'status_code', None)
            if status in (404, 410):
                PushSubscription.objects.filter(pk=device.pk).delete()
            # Do not log endpoints, encryption keys or provider response bodies.
            continue
        PushDelivery.objects.filter(pk=delivery_id).update(delivered_at=timezone.now())
        sent += 1
    return sent + deliver_pending_table_events(limit=limit, heartbeat=heartbeat)


def deliver_pending_table_events(limit=100, heartbeat=None):
    from tournaments.models import HeadToHeadTable

    if not configured():
        return 0
    sent = 0
    due = TablePushDelivery.objects.filter(
        delivered_at=None,
        discarded_at=None,
        attempts__lt=5,
        next_attempt_at__lte=timezone.now(),
    ).order_by('pk')
    for delivery_id in list(due.values_list('pk', flat=True)[:limit]):
        if heartbeat:
            heartbeat()
        now = timezone.now()
        claimed = TablePushDelivery.objects.filter(
            pk=delivery_id,
            delivered_at=None,
            discarded_at=None,
            next_attempt_at__lte=now,
            attempts__lt=5,
        ).update(attempts=F('attempts') + 1, next_attempt_at=now + timedelta(seconds=60))
        if not claimed:
            continue
        delivery = TablePushDelivery.objects.select_related('subscription__user', 'table__host', 'table__guest').filter(pk=delivery_id).first()
        if not delivery:
            continue
        table = delivery.table
        recipient_id = delivery.subscription.user_id
        valid_status = table.status in (HeadToHeadTable.STATUS_READY, HeadToHeadTable.STATUS_PLAYING)
        expects_host = delivery.kind == TablePushDelivery.KIND_GUEST_JOINED
        expected_recipient = table.host_id if expects_host else table.guest_id
        if not valid_status or not table.guest_id or recipient_id != expected_recipient:
            TablePushDelivery.objects.filter(pk=delivery_id).update(discarded_at=now)
            continue
        english = delivery.subscription.language == 'en'
        if expects_host:
            title = 'A player joined your table' if english else 'שחקן הצטרף לשולחן שלך'
            body = f'Table {table.code} is ready — open your games to start.' if english else f'שולחן {table.code} מוכן — פתח את המשחקים כדי להתחיל.'
            tag = f'table-guest-joined:{table.pk}'
        else:
            title = 'The host entered your game' if english else 'המארח נכנס למשחק שלך'
            body = f'Table {table.code} is waiting for you — open your games to join.' if english else f'שולחן {table.code} מחכה לך — פתח את המשחקים כדי להצטרף.'
            tag = f'table-host-entered:{table.pk}'
        payload = {
            'title': title,
            'body': body,
            'url': f'/tournaments/my-games?table={table.code}',
            'tag': tag,
        }
        try:
            send_notification(delivery.subscription, payload)
        except Exception as error:
            response = getattr(error, 'response', None)
            if getattr(response, 'status_code', None) in (404, 410):
                PushSubscription.objects.filter(pk=delivery.subscription_id).delete()
            continue
        TablePushDelivery.objects.filter(pk=delivery_id).update(delivered_at=timezone.now())
        sent += 1
    return sent
