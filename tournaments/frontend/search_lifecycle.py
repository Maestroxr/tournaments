"""Retire incompatible, unmatched searches without changing funded game terms."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from tournaments.models import DirectPlaySettings, HeadToHeadTable, WalletTransaction


def _cancellation_reason(table, settings):
    if table.game_format == 'legacy':
        return 'legacy_search_closed'
    profile = settings.format_profiles.get(table.game_format)
    if (not settings.enabled or not profile or not profile.get('enabled')
            or not profile.get('quick') or table.rules_snapshot != profile):
        return 'rules_changed'
    clocks = profile.get('time_controls', [])
    doubling_options = profile.get('doubling_options', [])
    if (table.target_points not in profile.get('target_points', [])
            or table.time_control not in clocks
            or table.doubling_enabled not in doubling_options):
        return 'rules_changed'
    if table.game_format == 'money':
        clock = 'normal' if 'normal' in clocks else clocks[0]
        doubling = True if True in doubling_options else doubling_options[0]
        if (table.target_points != 1 or table.time_control != clock
                or table.doubling_enabled != doubling):
            return 'rules_changed'
    return None


def reconcile_searches(settings, *, host_id=None):
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
    affected = [(table, reason) for table in searches
                if (reason := _cancellation_reason(table, settings)) is not None]
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
            WalletTransaction.create_entry(
                user=hosts[table.host_id], amount=refund,
                kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND,
                head_to_head_table=table,
                note=f'Unmatched search closed: {reason}; reservation released',
            )
        table.status = HeadToHeadTable.STATUS_CANCELLED
        table.completed_at = timezone.now()
        table.settlement = {
            'reason': reason, 'reservation_released': True, 'refund': str(refund),
        }
        table.save(update_fields=['status', 'completed_at', 'settlement', 'updated_at'])
        cancelled.append(table.pk)
    return cancelled


def reconcile_searches_locked(*, host_id=None):
    """Reconcile existing searches after an upgrade or on a player's return."""
    DirectPlaySettings.load()
    with transaction.atomic():
        settings = DirectPlaySettings.objects.select_for_update().get(pk=1)
        return reconcile_searches(settings, host_id=host_id)
