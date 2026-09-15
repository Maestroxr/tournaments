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
from frontend.models import PushSubscription, TablePushDelivery


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

    def legacy_table(self, payload):
        """Historical persisted terms: legacy creation is deliberately unavailable."""
        mode = payload.get('mode', 'match')
        amount = Decimal('50.00') if mode == 'friend' else Decimal(str(payload.get('amount', 100)))
        fee = Decimal('0.00') if mode == 'friend' else Decimal('5.00')
        return HeadToHeadTable.objects.create(
            code=f"L{HeadToHeadTable.objects.count():05d}", game_format='legacy',
            host=self.host, mode=mode, amount=amount, fee_percent=fee,
            fee_per_player=amount if mode == 'friend' else amount * fee / 100,
            target_points=payload.get('target_points', 1),
            time_control=payload.get('time_control', 'normal'),
            doubling_enabled=payload.get('doubling_enabled', True),
        )

    def test_legacy_rules_remain_published_but_cannot_enable_legacy_creation(self):
        self.host.is_staff = True
        self.host.save()
        self.client.force_login(self.host)
        rules = DirectPlaySettings.load().game_rules
        for rule in rules.values():
            rule.update(target_points=[7], time_controls=['fast'], doubling_options=[False])
        response = self.client.put('/api/admin/direct-play/settings',
            data=json.dumps({'game_rules': rules}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/api/head-to-head/tables').json()['game_rules'], rules)
        for mode in ('match', 'friend', 'quick'):
            path = '/api/head-to-head/quick-match' if mode == 'quick' else '/api/head-to-head/tables'
            result = self.client.post(path, data=json.dumps({'mode': mode, 'amount': 100,
                'target_points': 7, 'time_control': 'fast', 'doubling_enabled': False}),
                content_type='application/json')
            self.assertEqual(result.status_code, 400)
            self.assertEqual(result.json()['code'], 'game_format_required')
        self.assertFalse(HeadToHeadTable.objects.exists())
        self.assertEqual(WalletTransaction.objects.count(), 2)

    def test_disabled_legacy_mode_blocks_existing_join_without_charging(self):
        table = self.legacy_table({'mode': 'match', 'amount': 100})
        row = DirectPlaySettings.load()
        row.game_rules['match']['enabled'] = False
        row.save()
        self.client.force_login(self.guest)
        self.assertEqual(self.client.post(f'/api/head-to-head/tables/{table.code}/join').status_code, 412)
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal('1000'))

    def test_lobby_separates_my_finished_games_into_history(self):
        table = self.legacy_table({'mode': 'match', 'amount': 100})
        table.status = HeadToHeadTable.STATUS_COMPLETED
        table.winner = self.host
        table.save(update_fields=['status', 'winner'])

        self.client.force_login(self.host)
        response = self.client.get('/api/head-to-head/tables')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['my_tables'], [])
        self.assertEqual(response.json()['my_history'][0]['code'], table.code)
        self.assertEqual(response.json()['my_history'][0]['winner'], self.host.username)

    def test_rule_changes_preserve_existing_legacy_table_terms(self):
        table = self.legacy_table({'mode': 'match', 'amount': 100, 'target_points': 5})
        row = DirectPlaySettings.load()
        row.game_rules['match'].update(target_points=[7], time_controls=['fast'], doubling_options=[False])
        row.save()
        self.client.force_login(self.guest)
        joined = self.client.post(f"/api/head-to-head/tables/{table.code}/join")
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

    def test_legacy_admin_stakes_are_persisted_without_reopening_legacy_creation(self):
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
        self.assertEqual(self.create_table({'mode': 'match', 'amount': 300}).json()['code'], 'game_format_required')
        self.assertFalse(HeadToHeadTable.objects.exists())

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

    def test_legacy_empty_stakes_remain_valid_and_settings_require_staff(self):
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
        self.assertEqual(self.create_table({'mode': 'friend'}).json()['code'], 'game_format_required')

    def test_public_table_listing_includes_all_open_manual_tables(self):
        match_fields = dict(host=self.host, mode=HeadToHeadTable.MODE_MATCH, game_format='match',
                      amount=Decimal('100.00'), fee_percent=Decimal('5.00'),
                      fee_per_player=Decimal('5.00'))
        public_tables = HeadToHeadTable.objects.bulk_create([
            HeadToHeadTable(code=f'M{number:05d}', **match_fields) for number in range(105)
        ])
        money_fields = dict(host=self.host, mode=HeadToHeadTable.MODE_MATCH, game_format='money',
                      amount=Decimal('100.00'), fee_percent=Decimal('5.00'),
                      fee_per_player=Decimal('5.00'))
        HeadToHeadTable.objects.create(code='QUICK1', is_quick_match=True, **money_fields)
        HeadToHeadTable.objects.create(code='FRIEND', **{**match_fields, 'mode': HeadToHeadTable.MODE_FRIEND})
        HeadToHeadTable.objects.create(code='CLOSE1', status=HeadToHeadTable.STATUS_CANCELLED, **match_fields)
        self.client.force_login(self.guest)

        response = self.client.get('/api/head-to-head/tables')

        self.assertEqual(response.status_code, 200)
        listed = response.json()['tables']
        # Both Match and Money/Doubling open tables are visible in Open Games
        self.assertEqual(len(listed), 106)
        self.assertEqual([table['code'] for table in listed],
                         [table.code for table in reversed(public_tables + [HeadToHeadTable.objects.get(code='QUICK1')])])
        self.assertTrue(all(table['mode'] == 'match' and table['game_format'] in ('match', 'money')
                             and table['status'] == 'open' and table['guest'] is None for table in listed))

    def test_match_search_visible_in_public_tables(self):
        table = HeadToHeadTable.objects.create(
            code='SEARCH1', host=self.host, mode=HeadToHeadTable.MODE_MATCH, game_format='match',
            amount=Decimal('100.00'), fee_percent=Decimal('5.00'), fee_per_player=Decimal('5.00'),
            is_quick_match=True, status=HeadToHeadTable.STATUS_OPEN,
        )
        self.client.force_login(self.guest)
        response = self.client.get('/api/head-to-head/tables')
        self.assertEqual(response.status_code, 200)
        codes = [t['code'] for t in response.json()['tables']]
        self.assertIn(table.code, codes)
        entry = next(t for t in response.json()['tables'] if t['code'] == table.code)
        self.assertEqual(entry['game_format'], 'match')
        self.assertTrue(entry['is_quick_match'])

    def test_match_search_joinable_by_other_player(self):
        table = HeadToHeadTable.objects.create(
            code='SEARCH2', host=self.host, mode=HeadToHeadTable.MODE_MATCH, game_format='match',
            amount=Decimal('100.00'), fee_percent=Decimal('5.00'), fee_per_player=Decimal('5.00'),
            rules_snapshot=self._profile('match'),
            is_quick_match=True, status=HeadToHeadTable.STATUS_OPEN,
        )
        # Simulate the reservation that search-generated Match tables hold.
        WalletTransaction.create_entry(user=self.host, amount=Decimal('-100.00'), kind=WalletTransaction.KIND_HEAD_TO_HEAD_ENTRY, head_to_head_table=table, note='test reserve')
        self.client.force_login(self.guest)
        response = self.client.post(f'/api/head-to-head/tables/{table.code}/join')
        self.assertEqual(response.status_code, 200)
        table.refresh_from_db()
        self.assertEqual(table.guest_id, self.guest.id)
        self.assertEqual(table.status, HeadToHeadTable.STATUS_READY)

    def _profile(self, name):
        from tournaments.models import DirectPlaySettings
        return DirectPlaySettings.load().format_profiles[name]

    def test_match_search_self_join_rejected(self):
        table = HeadToHeadTable.objects.create(
            code='SEARCH3', host=self.host, mode=HeadToHeadTable.MODE_MATCH, game_format='match',
            amount=Decimal('100.00'), fee_percent=Decimal('5.00'), fee_per_player=Decimal('5.00'),
            rules_snapshot=self._profile('match'),
            is_quick_match=True, status=HeadToHeadTable.STATUS_OPEN,
        )
        self.client.force_login(self.host)
        response = self.client.post(f'/api/head-to-head/tables/{table.code}/join')
        self.assertEqual(response.status_code, 400)
        self.assertIn('own table', response.json()['detail'].lower())

    def test_money_quick_visible_in_open_games_but_direct_join_blocked(self):
        table = HeadToHeadTable.objects.create(
            code='MONEY1', host=self.host, mode=HeadToHeadTable.MODE_MATCH, game_format='money',
            amount=Decimal('100.00'), fee_percent=Decimal('5.00'), fee_per_player=Decimal('5.00'),
            rules_snapshot=self._profile('money'),
            is_quick_match=True, status=HeadToHeadTable.STATUS_OPEN, quick_stakes=['100'],
        )
        self.client.force_login(self.guest)
        response = self.client.get('/api/head-to-head/tables')
        self.assertEqual(response.status_code, 200)
        codes = [t['code'] for t in response.json()['tables']]
        # Money/Doubling games are now visible in Open Games together with Match games
        self.assertIn(table.code, codes)
        entry = next(t for t in response.json()['tables'] if t['code'] == table.code)
        self.assertEqual(entry['game_format'], 'money')
        join = self.client.post(f'/api/head-to-head/tables/{table.code}/join')
        self.assertEqual(join.status_code, 409)
        self.assertEqual(join.json()['detail'], 'Quick Match tables can only be joined through matchmaking.')
        table.refresh_from_db()
        self.assertIsNone(table.guest_id)
        self.assertEqual(table.status, HeadToHeadTable.STATUS_OPEN)

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
        table = self.legacy_table({'mode': 'friend', 'target_points': 5})
        table_id = table.pk
        self.client.force_login(self.host)
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

    def test_legacy_friend_join_charges_stored_fixed_fee_without_prize(self):
        table = self.legacy_table({
            "mode": "friend", "amount": "999", "target_points": 5,
            "doubling_enabled": False, "time_control": "fast",
        })
        self.assertEqual(table.amount, Decimal("50.00"))
        self.assertEqual(table.fee_percent, Decimal("0.00"))
        self.assertEqual(table.fee_per_player, Decimal("50.00"))
        self.assertEqual(table.time_control, "fast")

        self.client.force_login(self.guest)
        joined = self.client.post(f"/api/head-to-head/tables/{table.code}/join")
        self.assertEqual(joined.status_code, 200)
        table.refresh_from_db()
        self.assertEqual(table.status, HeadToHeadTable.STATUS_READY)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal("950.00"))
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal("950.00"))
        self.assertFalse(table.wallet_transactions.filter(kind=WalletTransaction.KIND_HEAD_TO_HEAD_PRIZE).exists())

    def test_friend_invitation_can_be_previewed_before_any_coins_are_charged(self):
        table = self.legacy_table({"mode": "friend", "target_points": 7, "doubling_enabled": False, "time_control": "slow"})
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
        response = self.create_table({"mode": "friend", "game_format": "match", "amount": 100, "time_control": "instant"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(HeadToHeadTable.objects.exists())

    def test_join_is_atomic_when_one_player_cannot_pay(self):
        table = self.legacy_table({"mode": "friend"})
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
        table = self.legacy_table({"mode": "match", "amount": "100", "doubling_enabled": True})
        self.client.force_login(self.guest)
        self.assertEqual(self.client.post(f"/api/head-to-head/tables/{table.code}/join").status_code, 200)
        self.client.force_login(self.host)
        cancelled = self.client.post(f"/api/head-to-head/tables/{table.code}/cancel")
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal("1000.00"))
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal("1000.00"))

    def test_legacy_friend_result_records_winner_without_awarding_coins(self):
        table = self.legacy_table({"mode": "friend", "time_control": "none"})
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

    def test_legacy_match_winner_receives_pot_less_stored_fee(self):
        table = self.legacy_table({"mode": "match", "amount": "100"})
        self.client.force_login(self.guest)
        self.client.post(f"/api/head-to-head/tables/{table.code}/join")
        response = ResultCallbackView()._record_direct_play(
            RequestFactory().post('/api/gamelink/result/'), table.pk,
            {"status": "completed", "room_id": "room-2", "winner_seat": "p2"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal("900.00"))
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal("1095.00"))

    def test_legacy_quick_creation_rejected_without_writes(self):
        for payload in ({}, {'amount': 500}, {'amounts': [100, 500]},
                        {'amount': 500, 'target_points': 5, 'doubling_enabled': True}):
            with self.subTest(payload=payload):
                self.client.force_login(self.host)
                response = self.client.post('/api/head-to-head/quick-match',
                    data=json.dumps(payload), content_type='application/json')
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['code'], 'game_format_required')
        self.assertFalse(HeadToHeadTable.objects.exists())
        self.assertEqual(WalletTransaction.objects.count(), 2)

    def match_search(self, user, **payload):
        self.client.force_login(user)
        return self.client.post('/api/head-to-head/match-search',
            data=json.dumps({'game_format': 'match', **payload}), content_type='application/json')

    def test_match_search_matches_shared_stake_and_charges_only_that_stake(self):
        waiting = self.match_search(self.host, amounts=[100, 500])
        repeated = self.match_search(self.host, amounts=[500, 100])
        self.assertEqual(waiting.json()['code'], repeated.json()['code'])
        response = self.match_search(self.guest, amounts=[200, 500])
        self.assertTrue(response.json()['matched'])
        self.assertEqual(response.json()['amount'], '500.00')
        self.assertEqual(response.json()['fee_per_player'], '25.00')
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('500.00'))
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal('500.00'))

    def test_match_search_rejects_empty_invalid_and_unaffordable_sets(self):
        for amounts in ([], '100', [100, 123], [100, 'NaN']):
            self.assertEqual(self.match_search(self.host, amounts=amounts).status_code, 400)
        self.assertEqual(self.match_search(self.host, amounts=[100, 2000]).status_code, 400)
        self.assertFalse(HeadToHeadTable.objects.exists())

    def test_match_search_disjoint_sets_do_not_match(self):
        self.match_search(self.host, amounts=[100, 500])
        response = self.match_search(self.guest, amounts=[200, 1000])
        self.assertFalse(response.json()['matched'])

    def test_match_search_different_stakes_do_not_match(self):
        self.match_search(self.host, amount='100')
        response = self.match_search(self.guest, amount='500')
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.json()['matched'])
        self.assertEqual(response.json()['amount'], '500.00')
        self.assertEqual(HeadToHeadTable.objects.count(), 2)
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal('500.00'))

    def test_match_search_existing_search_must_have_same_stake(self):
        first = self.match_search(self.host, amount='100')
        second = self.match_search(self.host, amount='500')
        repeated = self.match_search(self.host, amount='500')
        self.assertNotEqual(first.json()['code'], second.json()['code'])
        self.assertEqual(second.json()['code'], repeated.json()['code'])

    def test_match_search_rules_must_also_match(self):
        self.match_search(self.host, amount='500', time_control='fast')
        response = self.match_search(self.guest, amount='500', time_control='slow')
        self.assertFalse(response.json()['matched'])

    def test_match_search_rejects_unaffordable_selected_stake(self):
        response = self.match_search(self.host, amount='2000')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(HeadToHeadTable.objects.exists())
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('1000.00'))

    def test_match_search_uses_reserved_stake_after_waiting_host_spends_available_balance(self):
        waiting = self.match_search(self.host, amount='500')
        WalletTransaction.create_entry(user=self.host, amount=Decimal('-500'),
                                       kind=WalletTransaction.KIND_WITHDRAWAL)
        response = self.match_search(self.guest, amount='500')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['matched'])
        table = HeadToHeadTable.objects.get(code=waiting.json()['code'])
        self.assertEqual(table.status, HeadToHeadTable.STATUS_READY)
        self.assertEqual(table.amount, Decimal('500.00'))
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal('500.00'))
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('0.00'))

    def test_match_search_requires_explicit_valid_stake(self):
        response = self.match_search(self.host)
        self.assertEqual(response.status_code, 400)
        for amount in ('99', '0', '-1', 'NaN', 'Infinity'):
            with self.subTest(amount=amount):
                self.assertEqual(self.match_search(self.guest, amount=amount).status_code, 400)
        self.assertFalse(HeadToHeadTable.objects.exists())
        self.assertEqual(WalletTransaction.objects.count(), 2)

    def test_unfunded_table_cannot_award_coins(self):
        table = self.legacy_table({"mode": "match", "amount": "100"})
        response = ResultCallbackView()._record_direct_play(
            RequestFactory().post('/api/gamelink/result/'), table.pk,
            {"status": "completed", "room_id": "unfunded", "winner_seat": "p1"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal("1000.00"))

    def test_duplicate_completion_awards_only_one_prize(self):
        table = self.legacy_table({"mode": "match", "amount": "100"})
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

    def test_legacy_friend_creation_rejected_for_every_historical_length(self):
        for points in (1, 3, 5, 7, 9):
            with self.subTest(points=points):
                response = self.create_table({'mode': 'friend', 'target_points': points})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['code'], 'game_format_required')
        self.assertFalse(HeadToHeadTable.objects.exists())
        self.assertEqual(WalletTransaction.objects.count(), 2)

    def test_friend_code_has_four_digits_and_preserves_leading_zero(self):
        self.client.force_login(self.host)
        with patch('frontend.api.secrets.choice', return_value='0007'):
            response = self.client.post('/api/head-to-head/tables',
                                        data=json.dumps({'mode': 'friend', 'game_format': 'match', 'amount': 100}),
                                        content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['code'], '0007')
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get('/api/head-to-head/tables/0007').status_code, 200)
        self.assertEqual(self.client.post('/api/head-to-head/tables/0007/join').status_code, 200)

    def test_existing_six_character_friend_codes_still_work(self):
        table = self.legacy_table({'mode': 'friend'})
        HeadToHeadTable.objects.update(code='ABC123')
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get('/api/head-to-head/tables/abc123').status_code, 200)
        self.assertEqual(self.client.post('/api/head-to-head/tables/abc123/join').status_code, 200)

    def test_friend_code_collision_retries_without_duplicate_reservation(self):
        self.client.force_login(self.host)
        with patch('frontend.api.secrets.choice', return_value='0000'):
            self.client.post('/api/head-to-head/tables',
                             data=json.dumps({'mode': 'friend', 'game_format': 'match', 'amount': 100}),
                             content_type='application/json')
        # Simulate another request taking a code after our allocation snapshot.
        with patch('frontend.api.models.HeadToHeadTable.objects.values_list', return_value=[]), \
                patch('frontend.api.secrets.choice', side_effect=['0000', '0001']):
            response = self.client.post('/api/head-to-head/tables',
                                        data=json.dumps({'mode': 'friend', 'game_format': 'match', 'amount': 100}),
                                        content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['code'], '0001')
        self.assertEqual(HeadToHeadTable.objects.count(), 2)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('500.00'))

    def test_friend_code_exhaustion_returns_controlled_error(self):
        with patch('frontend.api.models.HeadToHeadTable.objects.values_list',
                   return_value=[f'{number:04d}' for number in range(10000)]):
            response = self.create_table({'mode': 'friend', 'game_format': 'match', 'amount': 100})
        self.assertEqual(response.status_code, 503)
        self.assertFalse(HeadToHeadTable.objects.exists())
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('1000.00'))

    def test_disabled_lobby_cannot_charge_an_existing_table(self):
        table = self.legacy_table({"mode": "match", "amount": "100"})
        settings_row = DirectPlaySettings.load()
        settings_row.enabled = False
        settings_row.save()
        self.client.force_login(self.guest)
        self.assertEqual(self.client.post(f"/api/head-to-head/tables/{table.code}/join").status_code, 412)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal("1000.00"))

    def test_nan_stake_is_rejected(self):
        self.assertEqual(self.create_table({"mode": "match", "game_format": "match", "amount": "NaN"}).status_code, 400)

    def test_cannot_open_a_modern_table_without_enough_coins(self):
        WalletTransaction.create_entry(user=self.host, amount=Decimal('-0.01'),
                                       kind=WalletTransaction.KIND_TOURNAMENT_ENTRY)
        response = self.create_table({'mode': 'match', 'game_format': 'match', 'amount': 1000})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(HeadToHeadTable.objects.exists())
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('999.99'))

    def test_exact_stake_balance_is_reserved_when_modern_table_created(self):
        response = self.create_table({'mode': 'match', 'game_format': 'match', 'amount': 1000})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('0.00'))
        table = HeadToHeadTable.objects.get()
        self.client.force_login(self.guest)
        self.assertEqual(self.client.post(f'/api/head-to-head/tables/{table.code}/join').status_code, 200)
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal('0.00'))

    def test_host_spending_after_creation_cannot_charge_the_guest(self):
        table = self.legacy_table({"mode": "friend", "target_points": 9})
        WalletTransaction.create_entry(user=self.host, amount=Decimal('-951'), kind=WalletTransaction.KIND_WITHDRAWAL)
        self.client.force_login(self.guest)
        response = self.client.post(f'/api/head-to-head/tables/{table.code}/join')
        self.assertEqual(response.status_code, 412)
        self.assertEqual(response.json()['code'], 'opponent_insufficient_coins')
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal('1000.00'))

    def test_legacy_friend_creation_is_rejected_before_balance_validation(self):
        WalletTransaction.create_entry(user=self.host, amount=Decimal('-951'), kind=WalletTransaction.KIND_WITHDRAWAL)
        response = self.create_table({'mode': 'friend', 'target_points': 9})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'game_format_required')
        self.assertFalse(HeadToHeadTable.objects.exists())
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('49.00'))

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
        WEB_PUSH_PUBLIC_KEY='test-public',
        WEB_PUSH_PRIVATE_KEY='test-private',
        WEB_PUSH_SUBJECT='mailto:operator@example.com',
    )
    def test_funded_player_can_open_the_game_with_a_signed_ticket(self):
        table = self.legacy_table({"mode": "friend", "time_control": "none"})
        self.client.force_login(self.guest)
        self.client.post(f"/api/head-to-head/tables/{table.code}/join")
        PushSubscription.objects.create(
            user=self.guest,
            endpoint_hash='guest-push-device',
            endpoint='https://fcm.googleapis.com/fcm/send/guest-push-device',
            p256dh='test-key',
            auth='test-auth',
        )
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
        self.assertTrue(TablePushDelivery.objects.filter(
            table=table,
            kind=TablePushDelivery.KIND_HOST_ENTERED,
            subscription__user=self.guest,
        ).exists())

    def test_versioned_friend_one_point_cost_and_doubling_disabled(self):
        self.client.force_login(self.host)
        payload = {
            'mode': 'friend',
            'game_format': 'match',
            'target_points': 1,
            'time_control': 'normal',
            'doubling_enabled': True,
        }
        response = self.client.post('/api/head-to-head/tables', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(Decimal(data['amount']), Decimal('50.00'))
        self.assertEqual(Decimal(data['fee_per_player']), Decimal('50.00'))
        self.assertEqual(Decimal(data['fee_percent']), Decimal('0.00'))
        self.assertFalse(data['doubling_enabled'])
        table = HeadToHeadTable.objects.get(code=data['code'])
        self.assertEqual(table.amount, Decimal('50.00'))
        self.assertEqual(table.fee_per_player, Decimal('50.00'))
        self.assertEqual(table.fee_percent, Decimal('0.00'))
        self.assertEqual(table.target_points, 1)
        self.assertFalse(table.doubling_enabled)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('950.00'))

    def test_versioned_friend_five_point_cost(self):
        self.client.force_login(self.host)
        payload = {
            'mode': 'friend',
            'game_format': 'match',
            'target_points': 5,
            'time_control': 'normal',
            'doubling_enabled': True,
        }
        response = self.client.post('/api/head-to-head/tables', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(Decimal(data['amount']), Decimal('250.00'))
        self.assertEqual(Decimal(data['fee_per_player']), Decimal('250.00'))
        self.assertEqual(Decimal(data['fee_percent']), Decimal('0.00'))
        self.assertTrue(data['doubling_enabled'])
        table = HeadToHeadTable.objects.get(code=data['code'])
        self.assertEqual(table.amount, Decimal('250.00'))
        self.assertEqual(table.fee_per_player, Decimal('250.00'))
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('750.00'))

    def test_versioned_friend_join_reserves_correct_amount(self):
        self.client.force_login(self.host)
        payload = {
            'mode': 'friend',
            'game_format': 'match',
            'target_points': 5,
            'time_control': 'normal',
            'doubling_enabled': True,
        }
        response = self.client.post('/api/head-to-head/tables', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 201)
        code = response.json()['code']
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('750.00'))
        self.client.force_login(self.guest)
        joined = self.client.post(f'/api/head-to-head/tables/{code}/join')
        self.assertEqual(joined.status_code, 200, joined.content)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('750.00'))
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal('750.00'))
        table = HeadToHeadTable.objects.get(code=code)
        self.assertEqual(table.status, HeadToHeadTable.STATUS_READY)

    def test_versioned_friend_completion_no_prize(self):
        self.client.force_login(self.host)
        payload = {
            'mode': 'friend',
            'game_format': 'match',
            'target_points': 5,
            'time_control': 'normal',
            'doubling_enabled': True,
        }
        response = self.client.post('/api/head-to-head/tables', data=json.dumps(payload), content_type='application/json')
        code = response.json()['code']
        table = HeadToHeadTable.objects.get(code=code)
        self.client.force_login(self.guest)
        self.client.post(f'/api/head-to-head/tables/{code}/join')
        table.refresh_from_db()
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('750.00'))
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal('750.00'))
        response = ResultCallbackView()._record_direct_play(
            RequestFactory().post('/api/gamelink/result/'), table.pk,
            {"status": "completed", "room_id": "room-friend-5", "winner_seat": "p1"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        table.refresh_from_db()
        self.assertEqual(table.winner, self.host)
        self.assertEqual(table.status, HeadToHeadTable.STATUS_COMPLETED)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('750.00'))
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal('750.00'))
        self.assertFalse(table.wallet_transactions.filter(kind=WalletTransaction.KIND_HEAD_TO_HEAD_PRIZE).exists())
        self.assertEqual(table.settlement.get('transfer'), "0.00")
        self.assertEqual(table.settlement.get('fee'), "0.00")

    def test_versioned_friend_cancellation_refunds(self):
        self.client.force_login(self.host)
        payload = {
            'mode': 'friend',
            'game_format': 'match',
            'target_points': 5,
            'time_control': 'normal',
            'doubling_enabled': True,
        }
        response = self.client.post('/api/head-to-head/tables', data=json.dumps(payload), content_type='application/json')
        code = response.json()['code']
        self.client.force_login(self.guest)
        self.client.post(f'/api/head-to-head/tables/{code}/join')
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('750.00'))
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal('750.00'))
        table = HeadToHeadTable.objects.get(code=code)
        self.client.force_login(self.host)
        cancelled = self.client.post(f'/api/head-to-head/tables/{code}/cancel')
        self.assertEqual(cancelled.status_code, 200, cancelled.content)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('1000.00'))
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), Decimal('1000.00'))
        table.refresh_from_db()
        self.assertEqual(table.status, HeadToHeadTable.STATUS_CANCELLED)


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
        self.assertEqual(settings_row.friend_fee_for(5), Decimal("300.00"))
        self.assertEqual(settings_row.head_to_head_fee_percent, Decimal("4.50"))
