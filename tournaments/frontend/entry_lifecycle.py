"""One active direct game per player, with five-minute search/arrival deadlines."""
import json
import logging
import time
from datetime import timedelta
from urllib.request import Request, urlopen
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from tournaments.models import DirectPlaySettings, HeadToHeadTable, WalletTransaction
from .task_ownership import fence_task_ownership


logger = logging.getLogger(__name__)
ACTIVE = ('open', 'ready', 'playing')


ENTRY_WINDOW_SECONDS = 5 * 60
SEARCH_PRESENCE_SECONDS = 90


def touch_open_searches(user_id):
    """Explicit presence keeps only the owner's unmatched searches alive."""
    candidates = HeadToHeadTable.objects.filter(
        host_id=user_id, status=HeadToHeadTable.STATUS_OPEN, guest__isnull=True,
    ).filter(Q(mode=HeadToHeadTable.MODE_MATCH) | Q(is_quick_match=True))
    if not candidates.exists():
        return 0
    updated = 0
    now_ts = int(timezone.now().timestamp())
    with transaction.atomic():
        searches = candidates.select_for_update()
        for table in searches:
            last_seen = (table.settlement or {}).get('search_seen_at')
            if type(last_seen) is int and now_ts - last_seen < 25:
                continue
            table.settlement = {**(table.settlement or {}),
                                'search_seen_at': now_ts}
            table.save(update_fields=['settlement'])
            updated += 1
    return updated


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


def open_search_expired(table, now=None):
    """Read-only admission check; cleanup and refunds are separate operations."""
    now = now or timezone.now()
    if table.created_at <= now - timedelta(seconds=ENTRY_WINDOW_SECONDS):
        return True
    last_seen = (table.settlement or {}).get('search_seen_at')
    if type(last_seen) is not int:
        last_seen = int(table.created_at.timestamp())
    return (table.mode == HeadToHeadTable.MODE_MATCH or table.is_quick_match) and (
        int(now.timestamp()) - last_seen >= SEARCH_PRESENCE_SECONDS)


def _candidate_ids(tables, batch_size=50, *, cursor=0, stop_id=None):
    """Keyset pages close each read cursor before taking a writer lock."""
    last_id = stop_id if stop_id is not None else tables.order_by('-pk').values_list('pk', flat=True).first()
    while last_id is not None:
        ids = list(tables.filter(pk__gt=cursor, pk__lte=last_id).order_by('pk')
                   .values_list('pk', flat=True)[:batch_size])
        if not ids:
            return
        yield from ids
        cursor = ids[-1]


def expire_unstarted_tables(user_id=None, heartbeat=None, *, allow_remote=True,
                            cursor=0, stop_id=None, max_items=None, max_seconds=None):
    if max_items is not None and max_items < 1:
        raise ValueError('max_items must be positive')
    if max_seconds is not None and max_seconds <= 0:
        raise ValueError('max_seconds must be positive')
    bounded = max_items is not None or max_seconds is not None
    batch_started = time.monotonic()
    checked = 0
    now = timezone.now()
    now_ts = int(now.timestamp())
    open_cutoff = now - timedelta(seconds=ENTRY_WINDOW_SECONDS)

    tables = HeadToHeadTable.objects.filter(status__in=ACTIVE)

    if user_id is not None:
        tables = tables.filter(
            Q(host_id=user_id) |
            Q(guest_id=user_id)
        )

    failed_ids = []
    stop_id = stop_id if stop_id is not None else tables.order_by('-pk').values_list('pk', flat=True).first()
    continuation = None
    for pk in _candidate_ids(tables, cursor=cursor, stop_id=stop_id):
        # Finish the current item's remote request and transaction before
        # yielding; never interrupt a refund halfway through. At most one
        # bounded remote request can overrun this soft wall-time budget.
        if ((max_items is not None and checked >= max_items)
                or (max_seconds is not None and time.monotonic() - batch_started >= max_seconds)):
            continuation = {'cursor': cursor, 'stop_id': stop_id}
            break
        cursor = pk
        checked += 1
        if heartbeat is not None and not heartbeat():
            logger.warning('event=task_lease_lost handler=expire_unstarted_tables table_id=%s phase=before_item', pk)
            return False

        observed = HeadToHeadTable.objects.filter(pk=pk).first()
        if observed is None:
            continue

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
            if not allow_remote:
                # Requests cannot decide whether a remote room already started.
                # Keep its reservation and active-game guard until the worker
                # receives an authoritative response; never refund speculatively.
                continue
            try:
                result = remote_expiry(observed)
            except Exception:
                failed_ids.append(pk)
                logger.warning(
                    'event=direct_entry_expiry_failed table_id=%s phase=remote_request', pk,
                    exc_info=True)
                continue
            if heartbeat is not None and not heartbeat():
                logger.warning('event=task_lease_lost handler=expire_unstarted_tables table_id=%s phase=after_remote', pk)
                return False
            if result == 'started':
                with transaction.atomic():
                    current = HeadToHeadTable.objects.select_for_update().get(pk=pk)
                    fence_task_ownership()
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
            fence_task_ownership()
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
                WalletTransaction.refund_entry_fees(
                    user=player, head_to_head_table=table, note=f'Entry deadline expired: {table.code}')
            table.status = 'cancelled'
            table.completed_at = timezone.now()
            table.settlement = {**(table.settlement or {}),
                                'reason': ('search_timeout' if observed.created_at <= open_cutoff else 'search_offline')
                                if observed.status == 'open' else 'entry_timeout',
                                'reservation_released': True}
            table.save(update_fields=['status', 'completed_at', 'settlement', 'updated_at'])
            transaction.on_commit(lambda table_id=pk, reason=table.settlement['reason']: logger.info(
                'event=direct_entry_expired table_id=%s reason=%s', table_id, reason,
            ))
    if failed_ids:
        raise RuntimeError(f'Direct game entry expiry failed for tables: {failed_ids}')
    if bounded:
        logger.debug('event=direct_entry_expiry_batch checked=%s continuation=%s duration_ms=%s',
                     checked, bool(continuation), int((time.monotonic() - batch_started) * 1000))
        return {'checked': checked, 'continuation': continuation}
    return True
