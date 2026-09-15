import json
import time
import uuid
import json as js
from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from tournaments.models import HeadToHeadTable, WalletTransaction
from gamelink.models import DirectPlayRematch
from gamelink.signing import sign_result_body

@override_settings(GAMELINK_ENABLED=True)
class RematchTournamentTests(TestCase):
    def setUp(self):
        self.host = User.objects.create_user(username='host', password='x')
        self.guest = User.objects.create_user(username='guest', password='x')
        for u in (self.host, self.guest):
            WalletTransaction.create_entry(user=u, amount=10000, kind=WalletTransaction.KIND_DEPOSIT, note='init')

    def _table(self, status='completed'):
        # use unique code per call to avoid collisions within same test
        code = uuid.uuid4().hex[:6].upper()
        t = HeadToHeadTable.objects.create(
            code=code, host=self.host, guest=self.guest, mode='match', game_format='money',
            amount=100, fee_percent=5, fee_per_player=5, target_points=1, time_control='normal',
            doubling_enabled=True, status=status, external_room_id='room-1',
            rules_snapshot={'max_cube': 64, 'target_points': [1], 'time_controls': ['normal'], 'doubling_options': [True], 'loss_limit_multiplier': 8, 'jacoby': True, 'stake_amounts': [100]},
            is_quick_match=True, quick_stakes=['100']
        )
        return t

    def _post_rematch(self, *, table, action, seat='p1', nonce=None):
        body = {
            'v': 1,
            'action': action,
            'source_table_id': table.pk,
            'room_id': table.external_room_id,
            'actor_seat': seat,
        }
        raw = js.dumps(body, separators=(',', ':'), sort_keys=True).encode()
        timestamp = str(int(time.time()))
        nonce = nonce if nonce is not None else uuid.uuid4().hex
        sig = sign_result_body(raw, timestamp, nonce)
        return self.client.post(
            '/api/gamelink/rematch/',
            data=raw,
            content_type='application/json',
            HTTP_X_GAMELINK_TIMESTAMP=timestamp,
            HTTP_X_GAMELINK_NONCE=nonce,
            HTTP_X_GAMELINK_SIGNATURE=sig,
        )

    def test_bad_hmac_rejected(self):
        body = {'v': 1, 'action': 'request', 'source_table_id': 1, 'room_id': 'room-1', 'actor_seat': 'p1'}
        raw = js.dumps(body, separators=(',', ':'), sort_keys=True).encode()
        ts = str(int(time.time()))
        nonce = uuid.uuid4().hex
        sig = sign_result_body(raw, ts, nonce)
        sig = 'v1=' + '00' * 32
        resp = self.client.post('/api/gamelink/rematch/', data=raw, content_type='application/json',
                                HTTP_X_GAMELINK_TIMESTAMP=ts, HTTP_X_GAMELINK_NONCE=nonce, HTTP_X_GAMELINK_SIGNATURE=sig)
        self.assertEqual(resp.status_code, 401)

    def test_replay_nonce_rejected(self):
        t = self._table(status='completed')
        body = {'v': 1, 'action': 'request', 'source_table_id': t.pk, 'room_id': 'room-1', 'actor_seat': 'p1'}
        raw = js.dumps(body, separators=(',', ':'), sort_keys=True).encode()
        ts = str(int(time.time()))
        nonce = uuid.uuid4().hex
        sig = sign_result_body(raw, ts, nonce)
        first = self.client.post('/api/gamelink/rematch/', data=raw, content_type='application/json',
                                 HTTP_X_GAMELINK_TIMESTAMP=ts, HTTP_X_GAMELINK_NONCE=nonce, HTTP_X_GAMELINK_SIGNATURE=sig)
        self.assertNotEqual(first.status_code, 401)
        second = self.client.post('/api/gamelink/rematch/', data=raw, content_type='application/json',
                                  HTTP_X_GAMELINK_TIMESTAMP=ts, HTTP_X_GAMELINK_NONCE=nonce, HTTP_X_GAMELINK_SIGNATURE=sig)
        self.assertEqual(second.status_code, 401)

    def test_completed_source_required(self):
        t = self._table(status='playing')
        resp = self._post_rematch(table=t, action='request', seat='p1')
        self.assertEqual(resp.status_code, 409)

    def test_requester_insufficient_rejected(self):
        t = self._table(status='completed')
        WalletTransaction.create_entry(user=self.host, amount=-10000, kind=WalletTransaction.KIND_WITHDRAWAL, note='drain')
        resp = self._post_rematch(table=t, action='request', seat='p1')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json().get('code'), 'requester_not_eligible')
        self.assertFalse(DirectPlayRematch.objects.filter(source_table=t).exists())

    def test_opponent_insufficient_rejected(self):
        t = self._table(status='completed')
        WalletTransaction.create_entry(user=self.guest, amount=-10000, kind=WalletTransaction.KIND_WITHDRAWAL, note='drain')
        resp = self._post_rematch(table=t, action='request', seat='p1')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json().get('code'), 'opponent_not_eligible')
        self.assertFalse(DirectPlayRematch.objects.filter(source_table=t).exists())

    def test_request_reserves_zero_funds(self):
        t = self._table(status='completed')
        host_before = WalletTransaction.balance_for_user(self.host)
        guest_before = WalletTransaction.balance_for_user(self.guest)
        resp = self._post_rematch(table=t, action='request', seat='p1')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'pending')
        self.assertEqual(WalletTransaction.balance_for_user(self.host), host_before)
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), guest_before)
        self.assertEqual(DirectPlayRematch.objects.filter(source_table=t).count(), 1)
        rem = DirectPlayRematch.objects.get(source_table=t)
        self.assertEqual(rem.status, 'pending')

    def test_accept_rechecks_balances(self):
        t = self._table(status='completed')
        resp = self._post_rematch(table=t, action='request', seat='p1')
        self.assertEqual(resp.status_code, 200)
        count_before = HeadToHeadTable.objects.count()
        WalletTransaction.create_entry(user=self.guest, amount=-10000, kind=WalletTransaction.KIND_WITHDRAWAL, note='drain responder')
        resp2 = self._post_rematch(table=t, action='accept', seat='p2')
        self.assertEqual(resp2.status_code, 409)
        self.assertEqual(resp2.json().get('code'), 'requester_not_eligible')
        rem = DirectPlayRematch.objects.get(source_table=t)
        self.assertIsNone(rem.new_table)
        self.assertEqual(HeadToHeadTable.objects.count(), count_before)
        # no new reservations on new table (still only source)
        self.assertEqual(HeadToHeadTable.objects.count(), 1)

    def test_active_other_game_rejects(self):
        t = self._table(status='completed')
        resp = self._post_rematch(table=t, action='request', seat='p1')
        self.assertEqual(resp.status_code, 200)
        # create another active table for guest
        HeadToHeadTable.objects.create(
            code=uuid.uuid4().hex[:6].upper(), host=self.guest, guest=self.host, mode='match', game_format='money',
            amount=100, fee_percent=5, fee_per_player=5, target_points=1, time_control='normal',
            doubling_enabled=True, status=HeadToHeadTable.STATUS_PLAYING, external_room_id='other-room',
            rules_snapshot=t.rules_snapshot, is_quick_match=True, quick_stakes=['100']
        )
        count_before = HeadToHeadTable.objects.count()
        resp2 = self._post_rematch(table=t, action='accept', seat='p2')
        self.assertEqual(resp2.status_code, 409)
        rem = DirectPlayRematch.objects.get(source_table=t)
        self.assertIsNone(rem.new_table)
        self.assertEqual(HeadToHeadTable.objects.count(), count_before)

    def test_accept_creates_one_new_table(self):
        t = self._table(status='completed')
        self._post_rematch(table=t, action='request', seat='p1')
        count_before = HeadToHeadTable.objects.count()
        resp = self._post_rematch(table=t, action='accept', seat='p2')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'created')
        self.assertEqual(HeadToHeadTable.objects.count(), count_before + 1)
        rem = DirectPlayRematch.objects.get(source_table=t)
        self.assertEqual(rem.status, 'created')
        self.assertIsNotNone(rem.new_table)
        self.assertNotEqual(rem.new_table.pk, t.pk)

    def test_accept_reserves_new_funds(self):
        t = self._table(status='completed')
        self._post_rematch(table=t, action='request', seat='p1')
        host_before = WalletTransaction.balance_for_user(self.host)
        guest_before = WalletTransaction.balance_for_user(self.guest)
        resp = self._post_rematch(table=t, action='accept', seat='p2')
        self.assertEqual(resp.status_code, 200)
        rem = DirectPlayRematch.objects.get(source_table=t)
        new_table = rem.new_table
        self.assertIsNotNone(new_table)
        # both balances lower
        self.assertLess(WalletTransaction.balance_for_user(self.host), host_before)
        self.assertLess(WalletTransaction.balance_for_user(self.guest), guest_before)
        from frontend.game_formats import required_reserve, held
        self.assertEqual(held(new_table, self.host), required_reserve(new_table))
        self.assertEqual(held(new_table, self.guest), required_reserve(new_table))
        # reservations belong to new_table
        self.assertTrue(new_table.wallet_transactions.filter(user=self.host).exists())
        self.assertTrue(new_table.wallet_transactions.filter(user=self.guest).exists())
        self.assertFalse(t.wallet_transactions.filter(user=self.host, amount__lt=0).count() > 1 or t.wallet_transactions.filter(user=self.guest, amount__lt=0).count() > 1 and new_table.pk == t.pk)

    def test_old_settlement_untouched(self):
        t = self._table(status='completed')
        old = {'transfer': '123.45', 'reservation_released': True, 'marker': 'old-source'}
        t.settlement = old
        t.save(update_fields=['settlement'])
        self._post_rematch(table=t, action='request', seat='p1')
        self._post_rematch(table=t, action='accept', seat='p2')
        t.refresh_from_db()
        self.assertEqual(t.settlement, old)

    def test_new_table_has_no_external_room_id(self):
        t = self._table(status='completed')
        self._post_rematch(table=t, action='request', seat='p1')
        resp = self._post_rematch(table=t, action='accept', seat='p2')
        self.assertEqual(resp.status_code, 200)
        rem = DirectPlayRematch.objects.get(source_table=t)
        new_table = rem.new_table
        self.assertIn(new_table.external_room_id, ('', None))
        self.assertEqual(new_table.status, HeadToHeadTable.STATUS_READY)

    def test_new_settlement_is_fresh(self):
        t = self._table(status='completed')
        t.settlement = {'transfer': '999', 'reservation_released': True, 'marker': 'old'}
        t.save(update_fields=['settlement'])
        self._post_rematch(table=t, action='request', seat='p1')
        resp = self._post_rematch(table=t, action='accept', seat='p2')
        self.assertEqual(resp.status_code, 200)
        rem = DirectPlayRematch.objects.get(source_table=t)
        new_settlement = rem.new_table.settlement
        self.assertNotEqual(new_settlement, t.settlement)
        self.assertIn('dynamic_max_cube', new_settlement)
        self.assertIn('dynamic_reserve_multiplier', new_settlement)
        self.assertIn('dynamic_max_exposure', new_settlement)
        self.assertNotIn('transfer', new_settlement)
        self.assertNotIn('reservation_released', new_settlement)
        self.assertNotIn('marker', new_settlement)

    def test_two_tickets_returned(self):
        t = self._table(status='completed')
        self._post_rematch(table=t, action='request', seat='p1')
        resp = self._post_rematch(table=t, action='accept', seat='p2')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('tickets', data)
        self.assertIn('p1', data['tickets'])
        self.assertIn('p2', data['tickets'])
        self.assertTrue(isinstance(data['tickets']['p1'], str) and len(data['tickets']['p1']) > 10)
        self.assertTrue(isinstance(data['tickets']['p2'], str) and len(data['tickets']['p2']) > 10)
        self.assertNotEqual(data['tickets']['p1'], data['tickets']['p2'])

    def test_decline_creates_nothing(self):
        t = self._table(status='completed')
        count_before = HeadToHeadTable.objects.count()
        host_before = WalletTransaction.balance_for_user(self.host)
        guest_before = WalletTransaction.balance_for_user(self.guest)
        self._post_rematch(table=t, action='request', seat='p1')
        resp = self._post_rematch(table=t, action='decline', seat='p2')
        self.assertEqual(resp.status_code, 200)
        rem = DirectPlayRematch.objects.get(source_table=t)
        self.assertEqual(rem.status, 'declined')
        self.assertIsNone(rem.new_table)
        self.assertEqual(HeadToHeadTable.objects.count(), count_before)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), host_before)
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), guest_before)

    def test_cancel_creates_nothing(self):
        t = self._table(status='completed')
        count_before = HeadToHeadTable.objects.count()
        host_before = WalletTransaction.balance_for_user(self.host)
        guest_before = WalletTransaction.balance_for_user(self.guest)
        self._post_rematch(table=t, action='request', seat='p1')
        resp = self._post_rematch(table=t, action='cancel', seat='p1')
        self.assertEqual(resp.status_code, 200)
        rem = DirectPlayRematch.objects.get(source_table=t)
        self.assertEqual(rem.status, 'cancelled')
        self.assertIsNone(rem.new_table)
        self.assertEqual(HeadToHeadTable.objects.count(), count_before)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), host_before)
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), guest_before)

    def test_duplicate_accept_cannot_create_second_table(self):
        t = self._table(status='completed')
        self._post_rematch(table=t, action='request', seat='p1')
        resp = self._post_rematch(table=t, action='accept', seat='p2')
        self.assertEqual(resp.status_code, 200)
        rem = DirectPlayRematch.objects.get(source_table=t)
        first_pk = rem.new_table.pk
        count_before = HeadToHeadTable.objects.count()
        resp2 = self._post_rematch(table=t, action='accept', seat='p2')
        # second accept must not create another table
        self.assertEqual(HeadToHeadTable.objects.count(), count_before)
        rem.refresh_from_db()
        self.assertEqual(rem.new_table.pk, first_pk)

    def test_simultaneous_requests_collapse(self):
        t = self._table(status='completed')
        self._post_rematch(table=t, action='request', seat='p1')
        count_before = HeadToHeadTable.objects.count()
        resp = self._post_rematch(table=t, action='request', seat='p2')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'created')
        self.assertEqual(DirectPlayRematch.objects.filter(source_table=t).count(), 1)
        rem = DirectPlayRematch.objects.get(source_table=t)
        self.assertEqual(rem.status, 'created')
        self.assertIsNotNone(rem.new_table)
        self.assertEqual(HeadToHeadTable.objects.count(), count_before + 1)

    def test_requester_disconnect_cancels_pending(self):
        t = self._table(status='completed')
        self._post_rematch(table=t, action='request', seat='p1')
        resp = self._post_rematch(table=t, action='disconnect', seat='p1')
        self.assertEqual(resp.status_code, 200)
        rem = DirectPlayRematch.objects.get(source_table=t)
        self.assertEqual(rem.status, 'cancelled')
        self.assertIsNone(rem.new_table)

    def test_responder_disconnect_cancels_pending(self):
        t = self._table(status='completed')
        self._post_rematch(table=t, action='request', seat='p1')
        resp = self._post_rematch(table=t, action='disconnect', seat='p2')
        self.assertEqual(resp.status_code, 200)
        rem = DirectPlayRematch.objects.get(source_table=t)
        self.assertEqual(rem.status, 'cancelled')
        self.assertIsNone(rem.new_table)

    def test_disconnect_without_pending_is_noop(self):
        t = self._table(status='completed')
        resp = self._post_rematch(table=t, action='disconnect', seat='p1')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'no_pending')
        self.assertFalse(DirectPlayRematch.objects.filter(source_table=t).exists())

    def test_disconnect_after_created_does_not_destroy_rematch(self):
        t = self._table(status='completed')
        self._post_rematch(table=t, action='request', seat='p1')
        self._post_rematch(table=t, action='accept', seat='p2')
        rem = DirectPlayRematch.objects.get(source_table=t)
        first_pk = rem.new_table.pk
        resp = self._post_rematch(table=t, action='disconnect', seat='p1')
        self.assertEqual(resp.status_code, 200)
        rem.refresh_from_db()
        self.assertEqual(rem.status, 'created')
        self.assertEqual(rem.new_table.pk, first_pk)
        self.assertTrue(HeadToHeadTable.objects.filter(pk=first_pk).exists())
