import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import connection
from django.test import RequestFactory, TransactionTestCase, skipUnlessDBFeature
from django.test.utils import CaptureQueriesContext
from tournaments.models import DirectPlaySettings, HeadToHeadTable, WalletTransaction

from . import api


class HeadToHeadJoinTests(TransactionTestCase):
    def setUp(self):
        self.host = User.objects.create_user(username='join_host')
        self.guest = User.objects.create_user(username='join_guest')
        self.factory = RequestFactory()
        DirectPlaySettings.load()
        for user in (self.host, self.guest):
            WalletTransaction.create_entry(
                user=user, amount=Decimal('1000'),
                kind=WalletTransaction.KIND_DEPOSIT,
            )

    def table(self, game_format='legacy', **kwargs):
        table = HeadToHeadTable.objects.create(
            code=f'J{HeadToHeadTable.objects.count():05d}',
            game_format=game_format, mode='match',
            amount=Decimal('100'), fee_percent=Decimal('5'),
            fee_per_player=Decimal('5'), **{'host': self.host, **kwargs},
        )
        if game_format == 'match':
            WalletTransaction.create_entry(
                user=table.host, amount=Decimal('-100'),
                kind=WalletTransaction.KIND_HEAD_TO_HEAD_ENTRY,
                head_to_head_table=table,
            )
        return table

    def join(self, table):
        request = self.factory.post(f'/api/head-to-head/tables/{table.code}/join')
        request.user = self.guest
        serialize = api._serialize_head_to_head

        def serialize_after_commit(value):
            self.assertFalse(connection.in_atomic_block)
            return serialize(value)

        with patch.object(api, '_serialize_head_to_head', side_effect=serialize_after_commit):
            return api.api_head_to_head_join(request, table.code)

    def assert_funded_once(self, table):
        response = self.join(table)
        self.assertEqual(response.status_code, 200)
        table.refresh_from_db()
        self.assertEqual(table.status, HeadToHeadTable.STATUS_READY)
        self.assertEqual(table.guest_id, self.guest.pk)
        for user in (self.host, self.guest):
            self.assertEqual(WalletTransaction.balance_for_user(user), Decimal('900'))
            self.assertEqual(table.wallet_transactions.filter(user=user).count(), 1)
        self.assertEqual(self.join(table).status_code, 409)
        self.assertEqual(table.wallet_transactions.count(), 2)

    def test_legacy_join_funds_both_players_once_and_serializes_after_commit(self):
        self.assert_funded_once(self.table())

    def test_match_join_keeps_host_reserve_and_serializes_after_commit(self):
        self.assert_funded_once(self.table('match'))

    def test_guest_active_game_blocks_both_formats_without_charging(self):
        self.table(host=self.guest, status=HeadToHeadTable.STATUS_PLAYING,
                   settlement={'entry_confirmed': True})
        for game_format in ('legacy', 'match'):
            with self.subTest(game_format=game_format):
                table = self.table(game_format)
                entries_before = WalletTransaction.objects.count()
                response = self.join(table)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(json.loads(response.content)['code'], 'active_game_exists')
                self.assertEqual(WalletTransaction.objects.count(), entries_before)
                table.refresh_from_db()
                self.assertIsNone(table.guest_id)

    def test_host_active_game_preserves_each_formats_rejection_without_charging(self):
        self.table(status=HeadToHeadTable.STATUS_PLAYING,
                   settlement={'entry_confirmed': True})
        for game_format, status in (('legacy', 409), ('match', 400)):
            with self.subTest(game_format=game_format):
                table = self.table(game_format)
                entries_before = WalletTransaction.objects.count()
                self.assertEqual(self.join(table).status_code, status)
                self.assertEqual(WalletTransaction.objects.count(), entries_before)

    @skipUnlessDBFeature('has_select_for_update_of')
    def test_table_select_locks_only_table_before_ordered_account_locks(self):
        table = self.table()
        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(self.join(table).status_code, 200)
        table_queries = [
            query['sql'] for query in captured.captured_queries
            if 'FOR UPDATE' in query['sql']
            and f'FROM "{HeadToHeadTable._meta.db_table}"' in query['sql']
            and 'JOIN' in query['sql']
        ]
        self.assertEqual(len(table_queries), 1)
        self.assertTrue(table_queries[0].endswith(
            f'FOR UPDATE OF "{HeadToHeadTable._meta.db_table}"'))
