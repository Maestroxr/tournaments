import json
from importlib import import_module
from decimal import Decimal
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from django.contrib.auth.models import User
from django.apps import apps
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings

from gamelink.views import ResultCallbackView
from gamelink.signing import verify_ticket
from tournaments.models import (
    DirectPlaySettings, HeadToHeadTable, Participant, Participation, Tournament,
    WalletTransaction,
)


class HeadToHeadApiTests(TestCase):
    def setUp(self):
        self.host = User.objects.create_user(username="host", password="pass")
        self.guest = User.objects.create_user(username="guest", password="pass")
        for user in (self.host, self.guest):
            WalletTransaction.create_entry(
                user=user, amount=Decimal("1000.00"),
                kind=WalletTransaction.KIND_DEPOSIT, note="test balance",
            )

    def create_table(self, payload):
        self.client.force_login(self.host)
        return self.client.post(
            "/api/head-to-head/tables",
            data=json.dumps(payload), content_type="application/json",
        )

    def test_game_rules_saved_published_and_enforced_for_every_mode(self):
        self.host.is_staff = True
        self.host.save()
        self.client.force_login(self.host)
        rules = DirectPlaySettings.load().game_rules
        for rule in rules.values():
            rule.update(target_points=[7], time_controls=['fast'], doubling_options=[False])
        response = self.client.put('/api/admin/direct-play/settings',
            data=json.dumps({'game_rules': rules}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['game_rules'], rules)
        self.assertEqual(self.client.get('/api/head-to-head/tables').json()['game_rules'], rules)
        for mode in ('match', 'friend', 'quick'):
            path = '/api/head-to-head/quick-match' if mode == 'quick' else '/api/head-to-head/tables'
            valid = {'mode': mode, 'amount': 100, 'target_points': 7, 'time_control': 'fast', 'doubling_enabled': False}
            for field, invalid in (('target_points', 5), ('time_control', 'normal'), ('doubling_enabled', True)):
                with self.subTest(mode=mode, field=field):
                    result = self.client.post(path, data=json.dumps({**valid, field: invalid}), content_type='application/json')
                    self.assertEqual(result.status_code, 400)
            result = self.client.post(path, data=json.dumps(valid), content_type='application/json')
            self.assertIn(result.status_code, (200, 201))

    def test_disabled_mode_blocks_creation_and_join_without_charging(self):
        created = self.create_table({'mode': 'match', 'amount': 100})
        row = DirectPlaySettings.load()
        row.game_rules['match']['enabled'] = False
        row.game_rules['quick']['enabled'] = False
        row.save()
        self.assertEqual(self.create_table({'mode': 'match', 'amount': 100}).status_code, 412)
        self.client.force_login(self.guest)
        self.assertEqual(self.client.post('/api/head-to-head/quick-match', data='{}', content_type='application/json').status_code, 412)
        self.assertEqual(self.client.post(f"/api/head-to-head/tables/{created.json()['code']}/join").status_code, 412)
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal('1000'))
        self.assertEqual(self.create_table({'mode': 'friend'}).status_code, 201)

    def test_lobby_separates_my_finished_games_into_history(self):
        created = self.create_table({'mode': 'match', 'amount': 100})
        table = HeadToHeadTable.objects.get(pk=created.json()['id'])
        table.status = HeadToHeadTable.STATUS_COMPLETED
        table.winner = self.host
        table.save(update_fields=['status', 'winner'])

        response = self.client.get('/api/head-to-head/tables')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['my_tables'], [])
        self.assertEqual(response.json()['my_history'][0]['code'], table.code)
        self.assertEqual(response.json()['my_history'][0]['winner'], self.host.username)

    def test_rule_changes_preserve_existing_table_terms(self):
        created = self.create_table({'mode': 'match', 'amount': 100, 'target_points': 5})
        row = DirectPlaySettings.load()
        row.game_rules['match'].update(target_points=[7], time_controls=['fast'], doubling_options=[False])
        row.save()
        self.client.force_login(self.guest)
        joined = self.client.post(f"/api/head-to-head/tables/{created.json()['code']}/join")
        self.assertEqual(joined.status_code, 200)
        self.assertEqual(joined.json()['target_points'], 5)
        self.assertEqual(joined.json()['time_control'], 'normal')
        self.assertTrue(joined.json()['doubling_enabled'])

    def test_game_rule_validation_rejects_empty_unknown_and_malformed_options(self):
        self.host.is_staff = True
        self.host.save()
        self.client.force_login(self.host)
        original = DirectPlaySettings.load().game_rules
        for mode, field, value in (
            ('match', 'target_points', []), ('match', 'target_points', [26]),
            ('match', 'target_points', [True]), ('match', 'target_points', [5, 5]),
            ('friend', 'target_points', [2]), ('quick', 'time_controls', []),
            ('quick', 'time_controls', ['unknown']), ('quick', 'time_controls', [{}]),
            ('friend', 'doubling_options', []), ('friend', 'doubling_options', [1]),
            ('match', 'enabled', 'false'),
        ):
            with self.subTest(mode=mode, field=field, value=value):
                rules = json.loads(json.dumps(original))
                rules[mode][field] = value
                response = self.client.put('/api/admin/direct-play/settings',
                    data=json.dumps({'game_rules': rules}), content_type='application/json')
                self.assertEqual(response.status_code, 400)
                self.assertEqual(DirectPlaySettings.load().game_rules, original)
        for rules in (None, [], {}, {'match': {}}):
            response = self.client.put('/api/admin/direct-play/settings',
                data=json.dumps({'game_rules': rules}), content_type='application/json')
            self.assertEqual(response.status_code, 400)

    def test_admin_stakes_are_persisted_published_and_enforced(self):
        self.host.is_staff = True
        self.host.save()
        self.client.force_login(self.host)
        response = self.client.put('/api/admin/direct-play/settings',
            data=json.dumps({'stake_amounts': [700, 300]}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['stake_amounts'], [300, 700])
        self.assertEqual(self.client.get('/api/head-to-head/tables').json()['stake_amounts'], [300, 700])
        for path in ('/api/head-to-head/tables', '/api/head-to-head/quick-match'):
            rejected = self.client.post(path, data=json.dumps({'mode': 'match', 'amount': 100}),
                                       content_type='application/json')
            self.assertEqual(rejected.status_code, 400)
        self.assertEqual(self.create_table({'mode': 'match', 'amount': 300}).status_code, 201)

    def test_admin_stakes_reject_invalid_values_without_saving(self):
        self.host.is_staff = True
        self.host.save()
        self.client.force_login(self.host)
        original = DirectPlaySettings.load().stake_amounts
        for amounts in (None, '100', [True], [99], [100.5], [100, 100], [100000000], [{}]):
            with self.subTest(amounts=amounts):
                response = self.client.put('/api/admin/direct-play/settings',
                    data=json.dumps({'stake_amounts': amounts}), content_type='application/json')
                self.assertEqual(response.status_code, 400)
                self.assertEqual(DirectPlaySettings.load().stake_amounts, original)

    def test_empty_stakes_disable_new_matches_and_settings_require_staff(self):
        self.client.force_login(self.host)
        self.assertEqual(self.client.put('/api/admin/direct-play/settings',
            data=json.dumps({'stake_amounts': []}), content_type='application/json').status_code, 403)
        self.host.is_staff = True
        self.host.save()
        response = self.client.put('/api/admin/direct-play/settings',
            data=json.dumps({'stake_amounts': []}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(DirectPlaySettings.load().stake_amounts, [])
        self.assertEqual(self.create_table({'mode': 'match', 'amount': 100}).status_code, 400)
        self.assertEqual(self.create_table({'mode': 'friend'}).status_code, 201)

    def test_public_table_listing_includes_all_open_manual_tables(self):
        fields = dict(host=self.host, mode=HeadToHeadTable.MODE_MATCH,
                      amount=Decimal('100.00'), fee_percent=Decimal('5.00'),
                      fee_per_player=Decimal('5.00'))
        public_tables = HeadToHeadTable.objects.bulk_create([
            HeadToHeadTable(code=f'M{number:05d}', **fields) for number in range(105)
        ])
        HeadToHeadTable.objects.create(code='QUICK1', is_quick_match=True, **fields)
        HeadToHeadTable.objects.create(code='FRIEND', **{**fields, 'mode': HeadToHeadTable.MODE_FRIEND})
        HeadToHeadTable.objects.create(code='CLOSE1', status=HeadToHeadTable.STATUS_CANCELLED, **fields)
        self.client.force_login(self.guest)

        response = self.client.get('/api/head-to-head/tables')

        self.assertEqual(response.status_code, 200)
        listed = response.json()['tables']
        self.assertEqual(len(listed), 105)
        self.assertEqual([table['code'] for table in listed],
                         [table.code for table in reversed(public_tables)])
        self.assertTrue(all(table['mode'] == 'match' and not table['is_quick_match']
                            and table['status'] == 'open' for table in listed))

    def test_admin_monitor_requires_staff(self):
        self.client.force_login(self.host)
        self.assertEqual(self.client.get('/api/admin/direct-play/tables').status_code, 403)

    def test_admin_monitor_keeps_old_waiting_players_and_includes_player_ids(self):
        waiting = HeadToHeadTable.objects.create(
            code='WAIT', mode='match', host=self.host, amount=100,
            fee_percent=5, fee_per_player=5, is_quick_match=True,
        )
        playing = HeadToHeadTable.objects.create(
            code='PLAY', mode='friend', host=self.host, guest=self.guest,
            amount=100, fee_percent=0, fee_per_player=50, status='playing',
        )
        HeadToHeadTable.objects.bulk_create([
            HeadToHeadTable(code=f'H{i:04}', mode='match', host=self.host,
                amount=100, fee_percent=5, fee_per_player=5, status='completed')
            for i in range(251)
        ])
        self.host.is_staff = True
        self.host.save(update_fields=['is_staff'])
        self.client.force_login(self.host)
        response = self.client.get('/api/admin/direct-play/tables')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['history_total'], 251)
        self.assertEqual(len(data['tables']), 252)
        rows = {row['id']: row for row in data['tables']}
        self.assertEqual(rows[waiting.id]['host_id'], self.host.id)
        self.assertIsNone(rows[waiting.id]['guest_id'])
        self.assertTrue(rows[waiting.id]['is_quick_match'])
        self.assertEqual(rows[playing.id]['guest_id'], self.guest.id)
        self.assertEqual(rows[playing.id]['time_control'], 'normal')

    def test_admin_cancel_refunds_once_and_returns_monitor_metadata(self):
        created = self.create_table({'mode': 'friend', 'target_points': 5})
        self.assertEqual(created.status_code, 201)
        table_id = created.json()['id']
        self.host.is_staff = True
        self.host.save(update_fields=['is_staff'])
        path = f'/api/admin/direct-play/tables/{table_id}/cancel'
        response = self.client.post(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['host_id'], self.host.id)
        self.assertEqual(response.json()['status'], 'cancelled')
        count = WalletTransaction.objects.filter(head_to_head_table_id=table_id,
            kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND).count()
        self.assertEqual(self.client.post(path).status_code, 409)
        self.assertEqual(WalletTransaction.objects.filter(head_to_head_table_id=table_id,
            kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND).count(), count)

    def test_friend_game_charges_fixed_50_without_percentage_or_prize(self):
        response = self.create_table({
            "mode": "friend", "amount": "999", "target_points": 5,
            "doubling_enabled": False, "time_control": "fast",
        })
        self.assertEqual(response.status_code, 201)
        table = HeadToHeadTable.objects.get()
        self.assertEqual(table.amount, Decimal("50.00"))
        self.assertEqual(table.fee_percent, Decimal("0.00"))
        self.assertEqual(table.fee_per_player, Decimal("50.00"))
        self.assertEqual(table.time_control, "fast")
        self.assertEqual(response.json()["time_control"], "fast")

        self.client.force_login(self.guest)
        joined = self.client.post(f"/api/head-to-head/tables/{table.code}/join")
        self.assertEqual(joined.status_code, 200)
        table.refresh_from_db()
        self.assertEqual(table.status, HeadToHeadTable.STATUS_READY)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal("950.00"))
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal("950.00"))
        self.assertFalse(table.wallet_transactions.filter(kind=WalletTransaction.KIND_HEAD_TO_HEAD_PRIZE).exists())

    def test_friend_invitation_can_be_previewed_before_any_coins_are_charged(self):
        self.create_table({"mode": "friend", "target_points": 7, "doubling_enabled": False, "time_control": "slow"})
        table = HeadToHeadTable.objects.get()
        self.client.force_login(self.guest)

        response = self.client.get(f"/api/head-to-head/tables/{table.code}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["fee_per_player"], "50.00")
        self.assertEqual(response.json()["target_points"], 7)
        self.assertFalse(response.json()["doubling_enabled"])
        self.assertEqual(response.json()["time_control"], "slow")
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal("1000.00"))
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal("1000.00"))

    def test_invalid_direct_play_time_control_is_rejected(self):
        response = self.create_table({"mode": "friend", "time_control": "instant"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(HeadToHeadTable.objects.exists())

    def test_join_is_atomic_when_one_player_cannot_pay(self):
        response = self.create_table({"mode": "friend"})
        table = HeadToHeadTable.objects.get()
        WalletTransaction.create_entry(
            user=self.guest, amount=Decimal("-951.00"),
            kind=WalletTransaction.KIND_WITHDRAWAL, note="leave too little",
        )
        self.client.force_login(self.guest)
        joined = self.client.post(f"/api/head-to-head/tables/{table.code}/join")
        self.assertEqual(joined.status_code, 412)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal("1000.00"))
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal("49.00"))
        self.assertFalse(table.wallet_transactions.filter(kind=WalletTransaction.KIND_FRIEND_GAME_FEE).exists())

    def test_owner_cancellation_refunds_both_players(self):
        response = self.create_table({"mode": "match", "amount": "100", "doubling_enabled": True})
        table = HeadToHeadTable.objects.get()
        self.client.force_login(self.guest)
        self.assertEqual(self.client.post(f"/api/head-to-head/tables/{table.code}/join").status_code, 200)
        self.client.force_login(self.host)
        cancelled = self.client.post(f"/api/head-to-head/tables/{table.code}/cancel")
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal("1000.00"))
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal("1000.00"))

    def test_friend_result_records_winner_without_awarding_coins(self):
        self.create_table({"mode": "friend", "time_control": "none"})
        table = HeadToHeadTable.objects.get()
        self.client.force_login(self.guest)
        self.client.post(f"/api/head-to-head/tables/{table.code}/join")
        response = ResultCallbackView()._record_direct_play(
            RequestFactory().post('/api/gamelink/result/'), table.pk,
            {"status": "completed", "room_id": "room-1", "winner_seat": "p1"},
        )
        self.assertEqual(response.status_code, 200)
        table.refresh_from_db()
        self.assertEqual(table.winner, self.host)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal("950.00"))
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal("950.00"))

    def test_match_play_winner_receives_pot_less_five_percent_of_stake(self):
        self.create_table({"mode": "match", "amount": "100"})
        table = HeadToHeadTable.objects.get()
        self.client.force_login(self.guest)
        self.client.post(f"/api/head-to-head/tables/{table.code}/join")
        response = ResultCallbackView()._record_direct_play(
            RequestFactory().post('/api/gamelink/result/'), table.pk,
            {"status": "completed", "room_id": "room-2", "winner_seat": "p2"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal("900.00"))
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal("1095.00"))

    def test_quick_match_charges_exactly_the_selected_stake(self):
        self.client.force_login(self.host)
        waiting = self.client.post(
            "/api/head-to-head/quick-match",
            data=json.dumps({"amount": "500", "target_points": 5, "doubling_enabled": True}),
            content_type="application/json",
        )
        self.assertEqual(waiting.status_code, 201)
        self.assertFalse(waiting.json()["matched"])

        self.client.force_login(self.guest)
        matched = self.client.post(
            "/api/head-to-head/quick-match",
            data=json.dumps({"amount": "500", "target_points": 5, "doubling_enabled": True}),
            content_type="application/json",
        )
        self.assertEqual(matched.status_code, 200)
        self.assertTrue(matched.json()["matched"])
        self.assertEqual(matched.json()["amount"], "500.00")
        self.assertEqual(matched.json()["fee_per_player"], "25.00")
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal("500.00"))
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal("500.00"))

    def quick_match(self, user, **payload):
        self.client.force_login(user)
        return self.client.post('/api/head-to-head/quick-match',
                                data=json.dumps(payload), content_type='application/json')

    def test_quick_match_matches_shared_stake_and_charges_only_that_stake(self):
        waiting = self.quick_match(self.host, amounts=[100, 500])
        repeated = self.quick_match(self.host, amounts=[500, 100])
        self.assertEqual(waiting.json()['code'], repeated.json()['code'])
        response = self.quick_match(self.guest, amounts=[200, 500])
        self.assertTrue(response.json()['matched'])
        self.assertEqual(response.json()['amount'], '500.00')
        self.assertEqual(response.json()['fee_per_player'], '25.00')
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('500.00'))
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal('500.00'))

    def test_quick_match_rejects_empty_invalid_and_unaffordable_sets(self):
        for amounts in ([], '100', [100, 123], [100, 'NaN']):
            self.assertEqual(self.quick_match(self.host, amounts=amounts).status_code, 400)
        self.assertEqual(self.quick_match(self.host, amounts=[100, 2000]).status_code, 412)
        self.assertFalse(HeadToHeadTable.objects.exists())

    def test_quick_match_disjoint_sets_do_not_match(self):
        self.quick_match(self.host, amounts=[100, 500])
        response = self.quick_match(self.guest, amounts=[200, 1000])
        self.assertFalse(response.json()['matched'])

    def test_quick_match_different_stakes_do_not_match(self):
        self.quick_match(self.host, amount='100')
        response = self.quick_match(self.guest, amount='500')
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.json()['matched'])
        self.assertEqual(response.json()['amount'], '500.00')
        self.assertEqual(HeadToHeadTable.objects.count(), 2)
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal('1000.00'))

    def test_quick_match_existing_search_must_have_same_stake(self):
        first = self.quick_match(self.host, amount='100')
        second = self.quick_match(self.host, amount='500')
        repeated = self.quick_match(self.host, amount='500')
        self.assertNotEqual(first.json()['code'], second.json()['code'])
        self.assertEqual(second.json()['code'], repeated.json()['code'])

    def test_quick_match_rules_must_also_match(self):
        self.quick_match(self.host, amount='500', time_control='fast')
        response = self.quick_match(self.guest, amount='500', time_control='slow')
        self.assertFalse(response.json()['matched'])

    def test_quick_match_rejects_unaffordable_selected_stake(self):
        response = self.quick_match(self.host, amount='2000')
        self.assertEqual(response.status_code, 412)
        self.assertEqual(response.json()['required'], '2000.00')
        self.assertEqual(response.json()['shortfall'], '1000.00')
        self.assertFalse(HeadToHeadTable.objects.exists())

    def test_quick_match_never_lowers_stake_when_waiting_host_spends(self):
        waiting = self.quick_match(self.host, amount='500')
        WalletTransaction.create_entry(user=self.host, amount=Decimal('-600'),
                                       kind=WalletTransaction.KIND_WITHDRAWAL)
        response = self.quick_match(self.guest, amount='500')
        self.assertFalse(response.json()['matched'])
        old = HeadToHeadTable.objects.get(code=waiting.json()['code'])
        self.assertEqual(old.status, HeadToHeadTable.STATUS_CANCELLED)
        self.assertEqual(old.amount, Decimal('500.00'))
        self.assertEqual(response.json()['amount'], '500.00')
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal('1000.00'))

    def test_quick_match_defaults_to_100_for_old_clients_and_rejects_invalid_amounts(self):
        response = self.quick_match(self.host)
        self.assertEqual(response.json()['amount'], '100.00')
        for amount in ('99', '0', '-1', 'NaN', 'Infinity'):
            with self.subTest(amount=amount):
                self.assertEqual(self.quick_match(self.guest, amount=amount).status_code, 400)

    def test_unfunded_table_cannot_award_coins(self):
        self.create_table({"mode": "match", "amount": "100"})
        table = HeadToHeadTable.objects.get()
        response = ResultCallbackView()._record_direct_play(
            RequestFactory().post('/api/gamelink/result/'), table.pk,
            {"status": "completed", "room_id": "unfunded", "winner_seat": "p1"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal("1000.00"))

    def test_duplicate_completion_awards_only_one_prize(self):
        self.create_table({"mode": "match", "amount": "100"})
        table = HeadToHeadTable.objects.get()
        self.client.force_login(self.guest)
        self.client.post(f"/api/head-to-head/tables/{table.code}/join")
        for _ in range(2):
            response = ResultCallbackView()._record_direct_play(
                RequestFactory().post('/api/gamelink/result/'), table.pk,
                {"status": "completed", "room_id": "repeat", "winner_seat": "p1"},
            )
            self.assertEqual(response.status_code, 200)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal("1095.00"))
        self.assertEqual(table.wallet_transactions.filter(kind=WalletTransaction.KIND_HEAD_TO_HEAD_PRIZE).count(), 1)

    def test_all_friend_lengths_have_fixed_fees(self):
        for points in (1, 3, 5, 7, 9):
            with self.subTest(points=points):
                response = self.create_table({"mode": "friend", "target_points": points})
                self.assertEqual(response.status_code, 201)
                self.assertEqual(Decimal(response.json()['fee_per_player']), Decimal(50))

    def test_friend_code_has_four_digits_and_preserves_leading_zero(self):
        self.client.force_login(self.host)
        with patch('frontend.api.secrets.choice', return_value='0007'):
            response = self.client.post('/api/head-to-head/tables',
                                        data=json.dumps({'mode': 'friend'}),
                                        content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['code'], '0007')
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get('/api/head-to-head/tables/0007').status_code, 200)
        self.assertEqual(self.client.post('/api/head-to-head/tables/0007/join').status_code, 200)

    def test_existing_six_character_friend_codes_still_work(self):
        self.create_table({'mode': 'friend'})
        HeadToHeadTable.objects.update(code='ABC123')
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get('/api/head-to-head/tables/abc123').status_code, 200)
        self.assertEqual(self.client.post('/api/head-to-head/tables/abc123/join').status_code, 200)

    def test_friend_code_collision_retries_without_charging(self):
        self.client.force_login(self.host)
        with patch('frontend.api.secrets.choice', return_value='0000'):
            self.client.post('/api/head-to-head/tables',
                             data=json.dumps({'mode': 'friend'}),
                             content_type='application/json')
        # Simulate another request taking a code after our allocation snapshot.
        with patch('frontend.api.models.HeadToHeadTable.objects.values_list', return_value=[]), \
                patch('frontend.api.secrets.choice', side_effect=['0000', '0001']):
            response = self.client.post('/api/head-to-head/tables',
                                        data=json.dumps({'mode': 'friend'}),
                                        content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['code'], '0001')
        self.assertEqual(HeadToHeadTable.objects.count(), 2)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('1000.00'))

    def test_friend_code_exhaustion_returns_controlled_error(self):
        with patch('frontend.api.models.HeadToHeadTable.objects.values_list',
                   return_value=[f'{number:04d}' for number in range(10000)]):
            response = self.create_table({'mode': 'friend'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['code'], 'friend_codes_unavailable')
        self.assertFalse(HeadToHeadTable.objects.exists())

    def test_disabled_lobby_cannot_charge_an_existing_table(self):
        self.create_table({"mode": "match", "amount": "100"})
        table = HeadToHeadTable.objects.get()
        settings_row = DirectPlaySettings.load()
        settings_row.enabled = False
        settings_row.save()
        self.client.force_login(self.guest)
        self.assertEqual(self.client.post(f"/api/head-to-head/tables/{table.code}/join").status_code, 412)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal("1000.00"))

    def test_nan_stake_is_rejected(self):
        self.assertEqual(self.create_table({"mode": "match", "amount": "NaN"}).status_code, 400)

    def test_cannot_open_a_table_without_enough_coins(self):
        WalletTransaction.create_entry(user=self.host, amount=Decimal('-0.01'),
                                       kind=WalletTransaction.KIND_TOURNAMENT_ENTRY)
        response = self.create_table({"mode": "match", "amount": "1000"})
        self.assertEqual(response.status_code, 412)
        self.assertEqual(Decimal(response.json()['shortfall']), Decimal('0.01'))
        self.assertFalse(HeadToHeadTable.objects.exists())

    def test_exact_stake_balance_is_enough_and_not_charged_until_join(self):
        self.assertEqual(self.create_table({"mode": "match", "amount": "1000"}).status_code, 201)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('1000.00'))
        table = HeadToHeadTable.objects.get()
        self.client.force_login(self.guest)
        self.assertEqual(self.client.post(f'/api/head-to-head/tables/{table.code}/join').status_code, 200)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('0.00'))

    def test_host_spending_after_creation_cannot_charge_the_guest(self):
        self.create_table({"mode": "friend", "target_points": 9})
        table = HeadToHeadTable.objects.get()
        WalletTransaction.create_entry(user=self.host, amount=Decimal('-951'), kind=WalletTransaction.KIND_WITHDRAWAL)
        self.client.force_login(self.guest)
        response = self.client.post(f'/api/head-to-head/tables/{table.code}/join')
        self.assertEqual(response.status_code, 412)
        self.assertEqual(response.json()['code'], 'opponent_insufficient_coins')
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal('1000.00'))

    def test_friend_creation_requires_the_full_fee(self):
        WalletTransaction.create_entry(user=self.host, amount=Decimal('-951'), kind=WalletTransaction.KIND_WITHDRAWAL)
        response = self.create_table({"mode": "friend", "target_points": 9})
        self.assertEqual(response.status_code, 412)
        self.assertEqual(Decimal(response.json()['shortfall']), Decimal('1.00'))

    def test_recurring_bonus_can_only_be_claimed_once_per_interval(self):
        self.client.force_login(self.host)
        status = self.client.get("/api/wallet/recurring-bonus")
        self.assertTrue(status.json()["available"])
        claimed = self.client.post("/api/wallet/recurring-bonus")
        self.assertEqual(claimed.status_code, 200)
        self.assertEqual(Decimal(claimed.json()["balance"]), Decimal("1400.00"))
        second = self.client.post("/api/wallet/recurring-bonus")
        self.assertEqual(second.status_code, 409)

    def test_tournament_prize_pool_is_entries_less_configured_fee(self):
        tournament = Tournament.objects.create(
            name="Fee tournament", podium_spec=[], entry_fee=Decimal("100.00"),
            platform_fee_percent=Decimal("10.00"),
        )
        for user in (self.host, self.guest):
            WalletTransaction.create_entry(
                user=user, amount=Decimal("-100.00"),
                kind=WalletTransaction.KIND_TOURNAMENT_ENTRY,
                tournament=tournament,
            )
        participant = Participant.get_or_create_for_user(self.host)
        Participation.objects.create(
            tournament=tournament, participant=participant, slot_id=0, podium_position=0,
        )
        self.assertEqual(tournament.effective_prize_money, Decimal("180.00"))
        tournament.award_prize_money()
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal("1080.00"))

    @override_settings(
        GAMELINK_ENABLED=True,
        GAMELINK_BACKGAMMON_URL="https://game.example/backgammon",
        GAMELINK_TICKET_SECRET="direct-play-ticket-secret-at-least-32-characters",
    )
    def test_funded_player_can_open_the_game_with_a_signed_ticket(self):
        self.create_table({"mode": "friend", "time_control": "none"})
        table = HeadToHeadTable.objects.get()
        self.client.force_login(self.guest)
        self.client.post(f"/api/head-to-head/tables/{table.code}/join")
        self.client.force_login(self.host)
        response = self.client.post(f"/t/head-to-head/{table.code}/play")
        self.assertEqual(response.status_code, 302)
        token = parse_qs(urlparse(response['Location']).query)['ticket'][0]
        payload = verify_ticket(token)
        self.assertEqual(payload['trn'], 0)
        self.assertEqual(payload['fix'], -table.pk)
        self.assertEqual(payload['seat'], 'p1')
        self.assertEqual(payload['tc'], 'none')
        table.refresh_from_db()
        self.assertEqual(table.status, HeadToHeadTable.STATUS_PLAYING)


class DirectPlayAdminApiTests(TestCase):
    def test_fixed_fee_migration_replaces_custom_old_rate_with_50(self):
        settings_row = DirectPlaySettings.load()
        settings_row.friend_game_fee = Decimal('125.00')
        settings_row.save()
        migration = import_module('tournaments.migrations.0019_fixed_friend_game_fee')
        migration.initialize_fixed_friend_fee(apps, connection.schema_editor())
        settings_row.refresh_from_db()
        self.assertEqual(settings_row.friend_game_fee, Decimal('50.00'))

    def test_admin_can_change_friend_fee_and_percentages(self):
        admin = User.objects.create_user(username="admin", password="pass", is_staff=True)
        self.client.force_login(admin)
        response = self.client.put(
            "/api/admin/direct-play/settings",
            data=json.dumps({
                "enabled": True,
                "friend_game_fee": "60",
                "head_to_head_fee_percent": "4.5",
                "tournament_fee_percent": "10",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        settings_row = DirectPlaySettings.load()
        self.assertEqual(settings_row.friend_fee_for(5), Decimal("60.00"))
        self.assertEqual(settings_row.head_to_head_fee_percent, Decimal("4.50"))
