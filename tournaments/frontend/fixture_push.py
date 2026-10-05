"""Deliver tournament waiting notifications outside HTTP and bracket workers."""
from datetime import timedelta
import logging
import uuid

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from tournaments.observability import incident_event
from .models import FixturePushDelivery, PushDelivery, PushSubscription


def queue_match_ready(fixture, recipient_id):
    # Use the same durable delivery as background discovery, so the initial
    # fixture transition and the next worker scan cannot queue duplicates.
    queued = 0
    for device_id in PushSubscription.objects.filter(user_id=recipient_id).values_list('pk', flat=True):
        _, created = PushDelivery.objects.get_or_create(
            subscription_id=device_id, fixture=fixture,
            defaults={'next_attempt_at': timezone.now()},
        )
        queued += int(created)
    if queued:
        fields = dict(fixture_id=fixture.pk, tournament_id=fixture.mode.tournament_id,
                      kind='match_ready', devices=queued)
        transaction.on_commit(lambda: incident_event('fixture_push_queued', **fields))
    return queued


def queue_opponent_waiting(fixture, recipient_id):
    queued = 0
    for device_id in PushSubscription.objects.filter(user_id=recipient_id).values_list('pk', flat=True):
        _, created = FixturePushDelivery.objects.get_or_create(
            subscription_id=device_id, fixture=fixture,
            kind=FixturePushDelivery.KIND_OPPONENT_WAITING,
            defaults={'next_attempt_at': timezone.now()},
        )
        queued += int(created)
    if queued:
        fields = dict(fixture_id=fixture.pk, tournament_id=fixture.mode.tournament_id,
                      kind='opponent_waiting', devices=queued)
        transaction.on_commit(lambda: incident_event('fixture_push_queued', **fields))
    return queued


def deliver_fixture_pushes(limit=100, heartbeat=None):
    from gamelink.views import playable_seat
    from .push import send_notification

    sent = 0
    due_ids = list(FixturePushDelivery.objects.filter(
        delivered_at=None, discarded_at=None, attempts__lt=5,
        next_attempt_at__lte=timezone.now(),
    ).order_by('pk').values_list('pk', flat=True)[:limit])
    for delivery_id in due_ids:
        if heartbeat is not None and heartbeat() is False:
            break
        now = timezone.now()
        token = uuid.uuid4()
        claimed = FixturePushDelivery.objects.filter(
            pk=delivery_id, delivered_at=None, discarded_at=None, attempts__lt=5,
            next_attempt_at__lte=now,
        ).update(attempts=F('attempts') + 1, next_attempt_at=now + timedelta(seconds=60), lease_token=token)
        if not claimed:
            continue
        delivery = FixturePushDelivery.objects.select_related(
            'subscription__user', 'fixture__mode__tournament', 'fixture__game_link',
            'fixture__player1__user', 'fixture__player2__user',
        ).filter(pk=delivery_id, lease_token=token).first()
        if delivery is None:
            continue
        owned = FixturePushDelivery.objects.filter(pk=delivery_id, lease_token=token)
        fixture = delivery.fixture
        link = getattr(fixture, 'game_link', None)
        seat, _ = playable_seat(delivery.subscription.user, fixture)
        if seat is None or (link and link.status in ('playing', 'completed', 'cancelled')):
            owned.update(discarded_at=now, lease_token=None)
            continue
        english = delivery.subscription.language == 'en'
        name = fixture.mode.tournament.name
        payload = {
            'title': 'Your opponent is waiting' if english else 'היריב שלך מחכה לך',
            'body': f'{name} — open your games to join your opponent.' if english else f'{name} — פתח את המשחקים שלך כדי להצטרף ליריב.',
            'url': '/tournaments/my-games',
            'tag': f'tournament-opponent-waiting:{fixture.pk}',
        }
        try:
            send_notification(delivery.subscription, payload)
        except Exception as error:
            status = getattr(getattr(error, 'response', None), 'status_code', None)
            incident_event('fixture_push_failed', level=logging.WARNING, fixture_id=fixture.pk,
                           tournament_id=fixture.mode.tournament_id, delivery_id=delivery_id,
                           device_id=delivery.subscription_id, provider_status=status,
                           attempt=delivery.attempts, error_type=type(error).__name__)
            if status in (404, 410):
                PushSubscription.objects.filter(pk=delivery.subscription_id).delete()
            else:
                owned.update(last_failure_at=timezone.now(), lease_token=None)
            continue
        if owned.update(delivered_at=timezone.now(), lease_token=None):
            sent += 1
            incident_event('fixture_push_accepted', fixture_id=fixture.pk,
                           tournament_id=fixture.mode.tournament_id, delivery_id=delivery_id,
                           device_id=delivery.subscription_id)
        else:
            incident_event('fixture_push_lease_lost', level=logging.WARNING,
                           fixture_id=fixture.pk, delivery_id=delivery_id)
    return sent
