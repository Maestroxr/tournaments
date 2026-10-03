"""One active direct game per player, with five-minute search/arrival deadlines."""
import json
import logging
from decimal import Decimal
from datetime import timedelta
from urllib.request import Request, urlopen
from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from tournaments.models import DirectPlaySettings, HeadToHeadTable, WalletTransaction


logger = logging.getLogger(__name__)
ACTIVE = ('open', 'ready', 'playing')


ENTRY_WINDOW_SECONDS = 5 * 60
SEARCH_PRESENCE_SECONDS = 90


def touch_open_searches(user_id):
    """Visible lobby polling keeps only the owner's unmatched searches alive."""
    with transaction.atomic():
        searches = HeadToHeadTable.objects.select_for_update().filter(
            host_id=user_id, status=HeadToHeadTable.STATUS_OPEN, guest__isnull=True,
        ).filter(Q(mode=HeadToHeadTable.MODE_MATCH) | Q(is_quick_match=True))
        for table in searches:
            table.settlement = {**(table.settlement or {}),
                                'search_seen_at': int(timezone.now().timestamp())}
            table.save(update_fields=['settlement'])


def mark_entry_ready(table):
    settlement = dict(table.settlement or {})
    settlement['entry_deadline'] = int(
        timezone.now().timestamp()) + ENTRY_WINDOW_SECONDS
    settlement['entry_window_seconds'] = ENTRY_WINDOW_SECONDS
    settlement.pop('entry_confirmed', None)

    table.settlement = settlement
    table.status = HeadToHeadTable.STATUS_READY


def active_table(user_id, exclude=None):
    tables = HeadToHeadTable.objects.filter(
        Q(host_id=user_id) | Q(guest_id=user_id), status__in=ACTIVE)
    if exclude is not None:
        tables = tables.exclude(pk=exclude)
    return tables.first()


def remote_expiry(table):
    from gamelink.signing import sign_command_body
    raw = json.dumps({'v': 1, 'action': 'expire_unstarted',
                     'fixture_id': -table.pk}).encode()
    timestamp = str(int(timezone.now().timestamp()))
    request = Request(settings.GAMELINK_BACKGAMMON_URL.rstrip('/') + '/api/link/admin-command/',
                      data=raw, headers={'Content-Type': 'application/json', 'X-Gamelink-Timestamp': timestamp,
                                         'X-Gamelink-Issuer': settings.GAMELINK_ISSUER,
                                         'X-Gamelink-Signature': sign_command_body(raw, timestamp)}, method='POST')
    with urlopen(request, timeout=3) as response:
        return json.load(response).get('status')


def expire_unstarted_tables(user_id=None, heartbeat=None):
    now = timezone.now()
    now_ts = int(now.timestamp())
    open_cutoff = now - timedelta(seconds=ENTRY_WINDOW_SECONDS)

    tables = HeadToHeadTable.objects.filter(status__in=ACTIVE)

    if user_id is not None:
        tables = tables.filter(
            Q(host_id=user_id) |
            Q(guest_id=user_id) |
            Q(status=HeadToHeadTable.STATUS_OPEN)
        )

    ids = list(tables.values_list('pk', flat=True))

    for pk in ids:
        if heartbeat is not None and not heartbeat():
            return False

        observed = HeadToHeadTable.objects.get(pk=pk)

        if (observed.settlement or {}).get('entry_confirmed'):
            continue

        if observed.status == HeadToHeadTable.STATUS_OPEN:
            last_seen = (observed.settlement or {}).get('search_seen_at')
            if type(last_seen) is not int:
                last_seen = int(observed.created_at.timestamp())
            search_offline = (observed.mode == HeadToHeadTable.MODE_MATCH or observed.is_quick_match) and (
                now_ts - last_seen >= SEARCH_PRESENCE_SECONDS)
            if observed.created_at > open_cutoff and not search_offline:
                continue
        else:
            entry_deadline = (observed.settlement or {}).get('entry_deadline')

            # Compatibility for tables created before entry_deadline was stored.
            if type(entry_deadline) is not int:
                entry_deadline = (
                    int(observed.updated_at.timestamp()) +
                    ENTRY_WINDOW_SECONDS
                )
            elif (observed.settlement or {}).get('entry_window_seconds') is None:
                # Existing paired tables used a 24-hour deadline.
                entry_deadline = entry_deadline - 24 * 60 * 60 + ENTRY_WINDOW_SECONDS

            if entry_deadline > now_ts:
                continue
        result = None
        if observed.status == 'playing' or observed.external_room_id:
            try:
                result = remote_expiry(observed)
            except Exception:
                logger.warning(
                    'Entry expiry deferred for table %s: game server unavailable', pk)
                continue
            if result == 'started':
                with transaction.atomic():
                    current = HeadToHeadTable.objects.select_for_update().get(pk=pk)
                    current.settlement = {
                        **(current.settlement or {}), 'entry_confirmed': True}
                    current.save(update_fields=['settlement'])
                continue
            if result not in ('missing', 'cancelled'):
                continue
        # Same settings -> table -> users lock order as creation and joining.
        with transaction.atomic():
            DirectPlaySettings.objects.select_for_update().get(pk=1)
            table = HeadToHeadTable.objects.select_for_update().get(pk=pk)
            if table.status not in ACTIVE:
                continue
            if table.status != observed.status or table.external_room_id != observed.external_room_id:
                continue
            if (table.settlement or {}).get('entry_confirmed'):
                continue
            if table.settlement != observed.settlement:
                continue
            from django.contrib.auth.models import User
            players = list(User.objects.select_for_update().filter(
                pk__in=[table.host_id, table.guest_id]).order_by('pk'))
            for player in players:
                net = table.wallet_transactions.filter(user=player).filter(
                    Q(amount__lt=0) | Q(
                        kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND)
                ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
                if net < 0:
                    WalletTransaction.create_entry(user=player, amount=-net,
                                                   kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND,
                                                   head_to_head_table=table, note=f'Entry deadline expired: {table.code}')
            table.status = 'cancelled'
            table.completed_at = timezone.now()
            table.settlement = {**(table.settlement or {}),
                                'reason': ('search_timeout' if observed.created_at <= open_cutoff else 'search_offline')
                                if observed.status == 'open' else 'entry_timeout',
                                'reservation_released': True}
            table.save(update_fields=['status', 'completed_at', 'settlement', 'updated_at'])
    return True
