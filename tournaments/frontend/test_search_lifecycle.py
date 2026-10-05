import copy
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from frontend.search_lifecycle import reconcile_searches_locked
from tournaments.models import DirectPlaySettings, HeadToHeadTable, WalletTransaction


class SearchLifecycleTests(TestCase):
    def test_settings_publication_does_not_scan_or_refund_inside_save(self):
        from frontend.models import Task
        table = self.search()
        self.settings.enabled = False
        with patch('frontend.search_lifecycle.reconcile_searches') as reconcile:
            self.settings.save()
        reconcile.assert_not_called()
        table.refresh_from_db()
        self.assertEqual(table.status, 'open')
        self.assertFalse(table.wallet_transactions.filter(kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND).exists())
        self.assertTrue(Task.objects.filter(key='reconcile-searches', status='pending').exists())
        reconcile_searches_locked()
        table.refresh_from_db()
        self.assertEqual(table.status, 'cancelled')

    def test_cleanup_budget_continues_after_cursor_and_refunds_only_once(self):
        tables = [self.search('legacy') for _ in range(4)]
        result = reconcile_searches_locked(batch_size=1, max_batches=2)
        self.assertEqual(result['cancelled'], [tables[0].pk, tables[1].pk])
        self.assertEqual(HeadToHeadTable.objects.filter(pk__in=[t.pk for t in tables], status='open').count(), 2)
        continuation = result['continuation']
        result = reconcile_searches_locked(batch_size=1, max_batches=2, **continuation)
        self.assertEqual(result['cancelled'], [tables[2].pk, tables[3].pk])
        self.assertIsNone(result['continuation'])
        reconcile_searches_locked()
        self.assertEqual(WalletTransaction.objects.filter(
            head_to_head_table__in=tables, kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND).count(), 4)

    def test_settings_save_does_not_steal_cleanup_lease_or_reset_cursor(self):
        import uuid
        from frontend.models import Task
        token = uuid.uuid4()
        Task.objects.filter(key='reconcile-searches').update(
            status='running', lease_token=token, kwargs={'cursor': 99, 'stop_id': 200})
        self.settings.enabled = False
        self.settings.save()
        task = Task.objects.get(key='reconcile-searches')
        self.assertEqual(task.lease_token, token)
        self.assertEqual(task.status, 'running')
        self.assertEqual(task.kwargs, {'cursor': 99, 'stop_id': 200})

    def test_disabled_quick_search_cannot_be_joined_before_cleanup(self):
        from django.core.exceptions import ValidationError
        from django.db import transaction
        from frontend.game_formats import join_table
        table = self.search()
        self.settings.format_profiles['money']['quick'] = False
        self.settings.save()
        with self.assertRaises(ValidationError), transaction.atomic():
            join_table(table, self.guest, self.settings)
        self.assertFalse(table.wallet_transactions.filter(user=self.guest).exists())

    def test_worker_reconciles_in_small_batches_and_refunds_once(self):
        from frontend.search_lifecycle import reconcile_searches
        tables = [self.search('legacy') for _ in range(3)]
        with patch('frontend.search_lifecycle.reconcile_searches', wraps=reconcile_searches) as reconcile:
            self.assertEqual(reconcile_searches_locked(batch_size=1), [t.pk for t in tables])
        self.assertEqual(reconcile.call_count, 3)
        self.assertTrue(all(len(call.kwargs['table_ids']) == 1 for call in reconcile.call_args_list))
        self.assertEqual(reconcile_searches_locked(batch_size=1), [])
        self.assertEqual(WalletTransaction.objects.filter(
            head_to_head_table__in=tables, kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND).count(), 3)

    def test_reconcile_stops_before_writing_when_lease_is_lost(self):
        table = self.search('legacy')
        self.assertIs(reconcile_searches_locked(heartbeat=lambda: False), False)
        table.refresh_from_db()
        self.assertEqual(table.status, 'open')
        self.assertFalse(table.wallet_transactions.filter(
            kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND).exists())

    def setUp(self):
        self.settings = DirectPlaySettings.load()
        self.host = User.objects.create_user('search-lifecycle-host')
        self.guest = User.objects.create_user('search-lifecycle-guest')
        for user in (self.host, self.guest):
            WalletTransaction.create_entry(user=user, amount=10000,
                                           kind=WalletTransaction.KIND_DEPOSIT)
        self.sequence = 0

    def search(self, game_format='money', *, host=None, status='open', quick=True, mode='match', reserve=None):
        self.sequence += 1
        profile = copy.deepcopy(
            self.settings.format_profiles.get(game_format, {}))
        table = HeadToHeadTable.objects.create(
            code=f'S{self.sequence:05}', host=host or self.host,
            guest=self.guest if status in ('ready', 'playing') else None,
            game_format=game_format, rules_snapshot=profile, mode=mode,
            is_quick_match=quick, status=status, amount=100,
            quick_stakes=['100.00'], fee_percent=5, fee_per_player=5,
            target_points=1 if game_format == 'money' else 5,
            time_control='normal', doubling_enabled=True,
        )
        reserve = (800 if game_format ==
                   'money' else 100) if reserve is None else reserve
        if reserve:
            WalletTransaction.create_entry(user=table.host, amount=-reserve,
                                           kind=WalletTransaction.KIND_HEAD_TO_HEAD_ENTRY, head_to_head_table=table)
        return table

    def test_changed_profile_does_not_cancel_existing_quick_search(self):
        money = self.search()
        match = self.search('match')
        snapshot = copy.deepcopy(money.rules_snapshot)
        self.settings.format_profiles['money']['fee_percent'] = 10
        self.settings.save()
        reconcile_searches_locked()
        money.refresh_from_db()
        match.refresh_from_db()
        self.assertEqual(money.status, 'open')
        self.assertEqual(money.rules_snapshot, snapshot)
        self.assertEqual(money.fee_percent, 5)
        self.assertEqual(money.settlement, {})
        self.assertEqual(match.status, 'open')
        self.assertEqual(WalletTransaction.balance_for_user(self.host), 9100)
        self.assertEqual(WalletTransaction.objects.filter(
            head_to_head_table=money, kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND).count(), 0)

        new_money = self.search()
        self.assertEqual(new_money.rules_snapshot['fee_percent'], 10)

    def test_changed_match_profile_does_not_cancel_existing_match_search(self):
        table = self.search('match')
        self.settings.format_profiles['match']['time_controls'] = ['fast']
        self.settings.save()
        reconcile_searches_locked()
        table.refresh_from_db()
        self.assertEqual(table.status, 'open')
        self.assertEqual(table.settlement, {})
        self.assertEqual(WalletTransaction.balance_for_user(self.host), 9900)

        new_match = self.search('match')
        self.assertEqual(new_match.rules_snapshot['time_controls'], ['fast'])

    def test_existing_paired_and_public_friend_contracts_survive_profile_change(self):
        tables = [self.search(status='ready'), self.search(status='playing'),
                  self.search('match', quick=False), self.search('match', quick=False, mode='friend')]
        contracts = [(table.status, copy.deepcopy(table.rules_snapshot), table.fee_percent,
                      table.target_points, table.time_control) for table in tables]
        balance = WalletTransaction.balance_for_user(self.host)
        self.settings.enabled = False
        self.settings.format_profiles['money']['loss_limit_multiplier'] = 4
        self.settings.format_profiles['match']['fee_percent'] = 10
        self.settings.save()
        reconcile_searches_locked()
        for table, original in zip(tables, contracts):
            table.refresh_from_db()
            self.assertEqual((table.status, table.rules_snapshot, table.fee_percent,
                              table.target_points, table.time_control), original)
        self.assertEqual(
            WalletTransaction.balance_for_user(self.host), balance)
        self.assertFalse(WalletTransaction.objects.filter(
            kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND).exists())

    def test_actual_ledger_multiple_entries_partial_release_and_retry(self):
        table = self.search(reserve=600)
        WalletTransaction.create_entry(user=self.host, amount=-200,
                                       kind=WalletTransaction.KIND_HEAD_TO_HEAD_ENTRY, head_to_head_table=table)
        WalletTransaction.create_entry(user=self.host, amount=150,
                                       kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND, head_to_head_table=table)
        # Profile changes preserve funded searches; disabling quick access is
        # the cancellation trigger for this ledger/refund test.
        self.settings.format_profiles['money']['quick'] = False
        self.settings.save()
        reconcile_searches_locked()
        table.refresh_from_db()
        self.assertEqual(table.settlement['refund'], '650.00')
        self.assertEqual(WalletTransaction.balance_for_user(self.host), 10000)
        self.assertEqual(reconcile_searches_locked(), [])
        self.settings.save()
        reconcile_searches_locked()
        self.assertEqual(WalletTransaction.objects.filter(
            head_to_head_table=table, kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND).count(), 2)

    def test_global_disable_closes_both_queue_formats(self):
        tables = [self.search(), self.search('match')]
        self.settings.enabled = False
        self.settings.save()
        reconcile_searches_locked()
        for table in tables:
            table.refresh_from_db()
            self.assertEqual(table.status, 'cancelled')
        self.assertEqual(WalletTransaction.balance_for_user(self.host), 10000)

    def test_disabled_quick_access_retires_only_its_queue(self):
        money = self.search()
        match = self.search('match')
        self.settings.format_profiles['money']['quick'] = False
        self.settings.save()
        reconcile_searches_locked()
        money.refresh_from_db()
        match.refresh_from_db()
        self.assertEqual(money.status, 'cancelled')
        self.assertEqual(match.status, 'open')

    def test_already_released_reservation_does_not_create_negative_or_duplicate_release(self):
        table = self.search()
        WalletTransaction.create_entry(user=self.host, amount=800,
                                       kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND, head_to_head_table=table)
        self.settings.enabled = False
        self.settings.save()
        reconcile_searches_locked()
        table.refresh_from_db()
        self.assertEqual(table.settlement['refund'], '0.00')
        self.assertEqual(WalletTransaction.objects.filter(
            head_to_head_table=table, kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND).count(), 1)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), 10000)

    def test_unchanged_and_unrelated_settings_preserve_search(self):
        table = self.search()
        self.settings.coin_grant_amount = 500
        self.settings.format_profiles['match']['fee_percent'] = 9
        self.settings.save()
        reconcile_searches_locked()
        table.refresh_from_db()
        self.assertEqual(table.status, 'open')
        self.assertEqual(WalletTransaction.balance_for_user(self.host), 9200)

    def test_update_fields_uses_persisted_profile_not_unsaved_attribute(self):
        table = self.search()
        self.settings.format_profiles['money']['fee_percent'] = 9
        self.settings.coin_grant_amount = 500
        self.settings.save(update_fields=['coin_grant_amount'])
        table.refresh_from_db()
        self.assertEqual(table.status, 'open')
        self.assertEqual(DirectPlaySettings.load(
        ).format_profiles['money']['fee_percent'], 5)

    def test_reconcile_keeps_existing_searches_open_when_only_profile_changes(self):
        money = self.search()
        money.time_control = 'slow'
        money.save(update_fields=['time_control'])
        match = self.search('match')
        match.time_control = 'slow'
        match.save(update_fields=['time_control'])
        self.assertEqual(reconcile_searches_locked(), [])
        money.refresh_from_db()
        match.refresh_from_db()
        self.assertEqual(money.status, 'open')
        self.assertEqual(match.status, 'open')

    def test_host_scoped_reconcile_and_legacy_without_reservation(self):
        own = self.search('legacy', reserve=0)
        other = self.search('legacy', host=self.guest, reserve=0)
        self.assertEqual(reconcile_searches_locked(
            host_id=self.host.pk), [own.pk])
        own.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(own.settlement['reason'], 'legacy_search_closed')
        self.assertEqual(own.settlement['refund'], '0.00')
        self.assertEqual(other.status, 'open')
        self.assertFalse(WalletTransaction.objects.filter(
            kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND).exists())

    def test_management_command_reconciles_existing_legacy_searches(self):
        table = self.search('legacy', reserve=0)
        output = StringIO()
        call_command('reconcile_direct_searches', stdout=output)
        table.refresh_from_db()
        self.assertEqual(table.status, 'cancelled')
        self.assertIn('Closed 1 unmatched searches', output.getvalue())

    def test_harmless_profile_change_does_not_trigger_refund_path(self):
        table = self.search()
        old_profiles = copy.deepcopy(self.settings.format_profiles)
        self.settings.format_profiles['money']['fee_percent'] = 10
        self.settings.save()
        reconcile_searches_locked()
        table.refresh_from_db()
        self.assertEqual(table.status, 'open')
        self.assertEqual(table.settlement, {})
        self.assertEqual(DirectPlaySettings.load(
        ).format_profiles['money']['fee_percent'], 10)
        self.assertEqual(DirectPlaySettings.load(
        ).format_profiles, self.settings.format_profiles)
        self.assertEqual(WalletTransaction.balance_for_user(
            self.host), Decimal('9200'))
        self.assertEqual(WalletTransaction.objects.filter(
            head_to_head_table=table, kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND).count(), 0)
