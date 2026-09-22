import json
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from tournaments.models import DirectPlaySettings, HeadToHeadTable, WalletTransaction
from frontend.entry_lifecycle import expire_unstarted_tables


class EntryLifecycleTests(TestCase):
    def setUp(self):
        DirectPlaySettings.load()
        self.user = User.objects.create_user('entry-host')
        WalletTransaction.create_entry(user=self.user, amount=10000, kind=WalletTransaction.KIND_DEPOSIT)
        self.client.force_login(self.user)

    def create(self):
        return self.client.post('/api/head-to-head/tables', json.dumps({
            'game_format': 'match', 'mode': 'match', 'amount': 100,
            'target_points': 1, 'time_control': 'normal', 'doubling_enabled': True,
        }), content_type='application/json')

    def old_table(self, status='open'):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.content)
        table = HeadToHeadTable.objects.get(pk=response.json()['id'])
        HeadToHeadTable.objects.filter(pk=table.pk).update(
            created_at=timezone.now() - timedelta(minutes=11), status=status)
        return table

    def test_second_game_rejected_without_another_charge(self):
        self.assertEqual(self.create().status_code, 201)
        balance = WalletTransaction.balance_for_user(self.user)
        response = self.create()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'active_game_exists')
        self.assertEqual(WalletTransaction.balance_for_user(self.user), balance)
        self.assertEqual(HeadToHeadTable.objects.count(), 1)

    def test_player_with_a_game_cannot_join_another_table(self):
        first = self.create()
        other = User.objects.create_user('entry-other')
        WalletTransaction.create_entry(user=other, amount=10000, kind=WalletTransaction.KIND_DEPOSIT)
        self.client.force_login(other)
        self.assertEqual(self.create().status_code, 201)
        balance = WalletTransaction.balance_for_user(other)
        response = self.client.post(f'/api/head-to-head/tables/{first.json()["code"]}/join')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(WalletTransaction.balance_for_user(other), balance)

    def test_expiry_refunds_once_and_releases_slot(self):
        table = self.old_table()
        expire_unstarted_tables()
        expire_unstarted_tables()
        table.refresh_from_db()
        self.assertEqual(table.status, 'cancelled')
        self.assertEqual(WalletTransaction.balance_for_user(self.user), 10000)
        self.assertEqual(self.create().status_code, 201)

    def test_expiry_releases_only_remaining_reservation(self):
        table = self.old_table()
        WalletTransaction.create_entry(user=self.user, amount=25,
            kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND, head_to_head_table=table)
        expire_unstarted_tables()
        self.assertEqual(WalletTransaction.balance_for_user(self.user), 10000)

    @patch('frontend.entry_lifecycle.remote_expiry', return_value='started')
    def test_actual_started_game_is_preserved(self, remote):
        table = self.old_table('playing')
        expire_unstarted_tables()
        table.refresh_from_db()
        self.assertEqual(table.status, 'playing')

    @patch('frontend.entry_lifecycle.remote_expiry', side_effect=OSError('offline'))
    def test_network_failure_does_not_cancel_a_game(self, remote):
        table = self.old_table('playing')
        expire_unstarted_tables()
        table.refresh_from_db()
        self.assertEqual(table.status, 'playing')

    @patch('frontend.entry_lifecycle.remote_expiry', return_value='missing')
    def test_clicked_link_without_connection_expires(self, remote):
        table = self.old_table('playing')
        expire_unstarted_tables()
        table.refresh_from_db()
        self.assertEqual(table.status, 'cancelled')
