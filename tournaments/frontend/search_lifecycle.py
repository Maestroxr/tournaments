"""Retire incompatible, unmatched searches without changing funded game terms."""
from decimal import Decimal
import logging
from time import perf_counter

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from tournaments.models import DirectPlaySettings, HeadToHeadTable, WalletTransaction
from .task_ownership import fence_task_ownership

logger = logging.getLogger(__name__)


def _cancellation_reason(table, settings):
    if table.game_format == 'legacy':
        return 'legacy_search_closed'
    profile = settings.format_profiles.get(table.game_format)
    if (not settings.enabled or not profile or not profile.get('enabled')):
        return 'rules_changed'
    if table.is_quick_match and not profile.get('quick'):
        return 'rules_changed'
    return None


def reconcile_searches(settings, *, host_id=None, table_ids=None):
    """Caller must hold the settings-row lock inside transaction.atomic().

    Creation uses the same settings -> tables -> users lock order. A concurrent
    match therefore either completes first, or sees the newly published rules.
    Public/friend tables and already paired games keep their existing contracts.
    """
    searches = HeadToHeadTable.objects.select_for_update().filter(
        is_quick_match=True, status=HeadToHeadTable.STATUS_OPEN,
        guest__isnull=True).order_by('pk')
    if host_id is not None:
        searches = searches.filter(host_id=host_id)
    if table_ids is not None:
        searches = searches.filter(pk__in=table_ids)
    affected = [(table, reason) for table in searches
                if (reason := _cancellation_reason(table, settings)) is not None]
    fence_task_ownership()
    # A player can host several searches, and table order is not user order.
    # Acquire the complete balance-lock set in the same order as settlement and
    # joining, before writing any refund; otherwise concurrent settlement can
    # hold a lower user ID while we hold a higher one and deadlock.
    hosts = {user.pk: user for user in User.objects.select_for_update().filter(
        pk__in={table.host_id for table, _ in affected}).order_by('pk')}
    cancelled = []
    for table, reason in affected:
        # Sum the actual ledger, including any partial earlier release. Never
        # recalculate a refund from newly changed stake or loss-limit settings.
        net = table.wallet_transactions.filter(user_id=table.host_id, kind__in=(
            WalletTransaction.KIND_HEAD_TO_HEAD_ENTRY,
            WalletTransaction.KIND_HEAD_TO_HEAD_REFUND,
        )).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        refund = max(Decimal('0'), -net).quantize(Decimal('0.01'))
        if refund:
            WalletTransaction.refund_entry_fees(
                user=hosts[table.host_id],
                head_to_head_table=table,
                note=f'Unmatched search closed: {reason}; reservation released',
            )
        table.status = HeadToHeadTable.STATUS_CANCELLED
        table.completed_at = timezone.now()
        table.settlement = {
            'reason': reason, 'reservation_released': True, 'refund': str(refund),
        }
        table.save(update_fields=[
                   'status', 'completed_at', 'settlement', 'updated_at'])
        cancelled.append(table.pk)
    return cancelled


def reconcile_searches_locked(*, host_id=None, heartbeat=None, batch_size=25,
                             cursor=0, stop_id=None, max_batches=None):
    """Reconcile existing searches after an upgrade or on a player's return."""
    DirectPlaySettings.load()
    if batch_size < 1:
        raise ValueError('batch_size must be positive')
    candidates = HeadToHeadTable.objects.filter(
        is_quick_match=True, status=HeadToHeadTable.STATUS_OPEN, guest__isnull=True)
    if host_id is not None:
        candidates = candidates.filter(host_id=host_id)
    if max_batches is not None and max_batches < 1:
        raise ValueError('max_batches must be positive')
    last_id = stop_id or candidates.order_by('-pk').values_list('pk', flat=True).first()
    batches = 0
    cancelled = []
    while last_id is not None:
        ids = list(candidates.filter(pk__gt=cursor, pk__lte=last_id).order_by('pk')
                   .values_list('pk', flat=True)[:batch_size])
        if not ids:
            break
        if heartbeat is not None and not heartbeat():
            return False
        # Release the writer between batches. Every candidate is checked again
        # under current settings; paired games can never be refunded here.
        started = perf_counter()
        with transaction.atomic():
            settings = DirectPlaySettings.objects.select_for_update().get(pk=1)
            batch = reconcile_searches(settings, host_id=host_id, table_ids=ids)
            cancelled.extend(batch)
        duration = round((perf_counter() - started) * 1000, 1)
        if batch or duration >= 250:
            logger.info('event=search_reconcile_batch candidates=%s cancelled=%s duration_ms=%s host_scoped=%s',
                        len(ids), len(batch), duration, host_id is not None)
        cursor = ids[-1]
        batches += 1
        if max_batches is not None and batches >= max_batches:
            more = candidates.filter(pk__gt=cursor, pk__lte=last_id).exists()
            return {'cancelled': cancelled, 'continuation':
                    {'cursor': cursor, 'stop_id': last_id} if more else None}
    return {'cancelled': cancelled, 'continuation': None} if max_batches is not None else cancelled
