"""Rules for new versioned direct games; existing contracts stay immutable."""
import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from tournaments.models import DirectPlaySettings, HeadToHeadTable, WalletTransaction


class ModeRuleTests(TestCase):
    def test_creation_requires_explicit_current_format_on_every_endpoint(self):
        for path in ('/api/head-to-head/tables', '/api/head-to-head/quick-match', '/api/head-to-head/match-search'):
            for extra in ({}, {'game_format': 'legacy'}, {'game_format': None}):
                with self.subTest(path=path, extra=extra):
                    response = self.post(path, mode='match', amount=100, amounts=[100], **extra)
                    self.assertEqual(response.status_code, 400, response.content)
                    if not extra:
                        self.assertEqual(response.json()['code'], 'game_format_required')
        self.assertFalse(HeadToHeadTable.objects.exists())
        self.assertEqual(WalletTransaction.objects.count(), 2)

    def test_search_endpoints_cannot_exchange_formats(self):
        for path, name in (('/api/head-to-head/quick-match', 'match'),
                           ('/api/head-to-head/match-search', 'money')):
            with self.subTest(path=path):
                response = self.post(path, game_format=name, amounts=[100])
                self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(HeadToHeadTable.objects.exists())
        self.assertEqual(WalletTransaction.balance_for_user(self.host), 10000)

    def test_admin_change_releases_unmatched_search_and_player_can_restart(self):
        created = self.post('/api/head-to-head/quick-match', game_format='money', amounts=[100, 200])
        old_table = HeadToHeadTable.objects.get(pk=created.json()['id'])
        old_snapshot = old_table.rules_snapshot.copy()
        self.host.is_staff = True
        self.host.save()
        profiles = self.settings.format_profiles
        profiles['money']['fee_percent'] = 10
        response = self.client.put('/api/admin/direct-play/settings',
                                   json.dumps({'format_profiles': profiles}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        old_table.refresh_from_db()
        self.assertEqual(old_table.status, 'cancelled')
        self.assertEqual(old_table.rules_snapshot, old_snapshot)
        self.assertEqual(old_table.settlement['reason'], 'rules_changed')
        self.assertEqual(old_table.settlement['refund'], '6400.00')
        self.assertEqual(WalletTransaction.balance_for_user(self.host), 10000)
        lobby = self.client.get('/api/head-to-head/tables').json()
        self.assertEqual(lobby['my_tables'], [])
        self.assertEqual(lobby['my_history'][0]['settlement']['reason'], 'rules_changed')
        restarted = self.post('/api/head-to-head/quick-match', game_format='money', amounts=[100])
        self.assertEqual(restarted.status_code, 201, restarted.content)
        self.assertNotEqual(restarted.json()['id'], old_table.pk)
        self.assertEqual(restarted.json()['fee_percent'], '10.00')
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('3600'))
        self.assertEqual(old_table.wallet_transactions.filter(kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND).count(), 1)

    def test_invalid_admin_settings_leave_waiting_search_and_reserve_intact(self):
        created = self.post('/api/head-to-head/quick-match', game_format='money', amounts=[100])
        self.host.is_staff = True
        self.host.save()
        for payload in ([], None, {'format_profiles': {}}):
            with self.subTest(payload=payload):
                response = self.client.put('/api/admin/direct-play/settings', json.dumps(payload),
                                           content_type='application/json')
                self.assertEqual(response.status_code, 400, response.content)
        table = HeadToHeadTable.objects.get(pk=created.json()['id'])
        self.assertEqual(table.status, 'open')
        self.assertEqual(WalletTransaction.balance_for_user(self.host), Decimal('3600'))

    def test_lobby_retires_only_own_legacy_search_and_explains_closure(self):
        own = HeadToHeadTable.objects.create(code='LEG001', host=self.host, mode='match',
                                              game_format='legacy', is_quick_match=True, amount=100,
                                              fee_percent=5, fee_per_player=5)
        other = HeadToHeadTable.objects.create(code='LEG002', host=self.guest, mode='match',
                                                game_format='legacy', is_quick_match=True, amount=100,
                                                fee_percent=5, fee_per_player=5)
        response = self.client.get('/api/head-to-head/tables')
        self.assertEqual(response.status_code, 200)
        own.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(own.status, 'cancelled')
        self.assertEqual(other.status, 'open')
        self.assertEqual(response.json()['my_history'][0]['settlement']['reason'], 'legacy_search_closed')
        self.assertEqual(WalletTransaction.objects.count(), 2)

    def setUp(self):
        self.settings = DirectPlaySettings.load()
        self.host = User.objects.create_user('mode-host')
        self.guest = User.objects.create_user('mode-guest')
        for player in (self.host, self.guest):
            WalletTransaction.create_entry(user=player, amount=10000,
                                           kind=WalletTransaction.KIND_DEPOSIT)
        self.client.force_login(self.host)

    def post(self, path, **payload):
        return self.client.post(path, json.dumps(payload), content_type='application/json')

    def test_incompatible_formats_rejected_before_reserving_even_if_profile_allows_access(self):
        for path, payload in (
            ('/api/head-to-head/tables', dict(game_format='money', mode='match', amount=100)),
            ('/api/head-to-head/tables', dict(game_format='money', mode='friend', amount=100)),
        ):
            with self.subTest(path=path, payload=payload):
                response = self.post(path, **payload)
                self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(HeadToHeadTable.objects.exists())
        self.assertEqual(WalletTransaction.balance_for_user(self.host), 10000)
        self.assertEqual(WalletTransaction.objects.count(), 2)

    def test_match_search_preserves_settings_matches_and_reserves_fixed_stake(self):
        payload = dict(game_format='match', amounts=[100], target_points=7,
                       time_control='slow', doubling_enabled=False)
        first = self.post('/api/head-to-head/match-search', **payload)
        self.assertEqual(first.status_code, 201, first.content)
        self.assertFalse(first.json()['matched'])
        again = self.post('/api/head-to-head/match-search', **payload)
        self.assertEqual(again.json()['id'], first.json()['id'])
        self.assertEqual(WalletTransaction.balance_for_user(self.host), 9900)
        self.client.force_login(self.guest)
        second = self.post('/api/head-to-head/match-search', **payload)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertTrue(second.json()['matched'])
        self.assertEqual(second.json()['id'], first.json()['id'])
        table = HeadToHeadTable.objects.get()
        self.assertEqual((table.game_format, table.target_points, table.time_control, table.doubling_enabled),
                         ('match', 7, 'slow', False))
        self.assertEqual(WalletTransaction.balance_for_user(self.guest), 9900)

    def test_match_search_does_not_match_different_rules_or_money_games(self):
        payload = dict(game_format='match', amounts=[100], target_points=7,
                       time_control='slow', doubling_enabled=False)
        first = self.post('/api/head-to-head/match-search', **payload)
        self.assertEqual(first.status_code, 201, first.content)
        self.client.force_login(self.guest)
        for change in (dict(target_points=5), dict(time_control='normal'),
                       dict(doubling_enabled=True), dict(game_format='money')):
            with self.subTest(change=change):
                path = '/api/head-to-head/quick-match' if change.get('game_format') == 'money' else '/api/head-to-head/match-search'
                response = self.post(path, **{**payload, **change})
                self.assertEqual(response.status_code, 201, response.content)
                self.assertFalse(response.json()['matched'])
                self.assertNotEqual(response.json()['id'], first.json()['id'])

    def test_match_search_cancellation_refunds_reservation(self):
        response = self.post('/api/head-to-head/match-search', game_format='match', amounts=[100],
                             target_points=5, time_control='normal', doubling_enabled=True)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), 9900)
        cancelled = self.post(f"/api/head-to-head/tables/{response.json()['code']}/cancel")
        self.assertEqual(cancelled.status_code, 200, cancelled.content)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), 10000)

    def test_match_search_rejects_invalid_rules_and_disabled_access_without_reserving(self):
        for override in (dict(target_points=2), dict(time_control='unknown'), dict(doubling_enabled='false')):
            with self.subTest(override=override):
                response = self.post('/api/head-to-head/match-search', game_format='match', amounts=[100], **override)
                self.assertEqual(response.status_code, 400, response.content)
        self.settings.format_profiles['match']['quick'] = False
        self.settings.save()
        response = self.post('/api/head-to-head/match-search', game_format='match', amounts=[100])
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(HeadToHeadTable.objects.exists())
        self.assertEqual(WalletTransaction.balance_for_user(self.host), 10000)

    def test_quick_clients_with_different_hidden_rules_share_effective_rules_and_queue(self):
        first = self.post('/api/head-to-head/quick-match', game_format='money',
                          amounts=[100, 200], target_points=9, time_control='slow', doubling_enabled=False)
        self.assertEqual(first.status_code, 201, first.content)
        self.client.force_login(self.guest)
        second = self.post('/api/head-to-head/quick-match', game_format='money', amounts=[100])
        self.assertEqual(second.status_code, 200, second.content)
        self.assertTrue(second.json()['matched'])
        self.assertEqual(first.json()['id'], second.json()['id'])
        table = HeadToHeadTable.objects.get()
        self.assertEqual((table.game_format, table.target_points, table.time_control, table.doubling_enabled),
                         ('money', 1, 'normal', True))
        self.assertEqual(table.amount, 100)
        self.assertTrue(table.rules_snapshot['jacoby'])
        self.assertEqual(table.rules_snapshot['max_cube'], 8)
        for response in (first, second):
            self.assertEqual(response.json()['target_points'], 1)
            self.assertEqual(response.json()['time_control'], 'normal')
            self.assertIs(response.json()['doubling_enabled'], True)

    def test_quick_defaults_follow_allowed_profile_when_preferred_options_disabled(self):
        self.settings.format_profiles['money'].update(time_controls=['fast'], doubling_options=[False])
        self.settings.save()
        response = self.post('/api/head-to-head/quick-match', game_format='money', amounts=[100],
                             target_points=7, time_control='normal', doubling_enabled=True)
        self.assertEqual(response.status_code, 201, response.content)
        table = HeadToHeadTable.objects.get()
        self.assertEqual((table.target_points, table.time_control, table.doubling_enabled), (1, 'fast', False))

    def test_public_and_friend_keep_selected_match_rules(self):
        for mode in ('match', 'friend'):
            with self.subTest(mode=mode):
                response = self.post('/api/head-to-head/tables', game_format='match', mode=mode,
                                     amount=100, target_points=7, time_control='slow', doubling_enabled=False)
                self.assertEqual(response.status_code, 201, response.content)
                table = HeadToHeadTable.objects.get(pk=response.json()['id'])
                self.assertEqual((table.game_format, table.target_points, table.time_control, table.doubling_enabled),
                                 ('match', 7, 'slow', False))
                self.assertFalse(table.rules_snapshot['jacoby'])
                self.assertEqual(table.rules_snapshot['max_cube'], 64)
        self.assertEqual(
            WalletTransaction.balance_for_user(self.host),
            Decimal('9550'),
        )

    def test_match_invalid_rule_is_not_silently_replaced(self):
        for override in (dict(target_points=2), dict(time_control='unknown'), dict(doubling_enabled='false')):
            with self.subTest(override=override):
                response = self.post('/api/head-to-head/tables', game_format='match', mode='match', amount=100,
                                     **override)
                self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(HeadToHeadTable.objects.exists())

    def test_match_modes_require_explicit_rules_without_silent_defaults(self):
        full = dict(target_points=7, time_control='slow', doubling_enabled=False)
        cases = (
            ('/api/head-to-head/match-search', dict(game_format='match', amounts=[100])),
            ('/api/head-to-head/tables', dict(game_format='match', mode='match', amount=100)),
            ('/api/head-to-head/tables', dict(game_format='match', mode='friend', amount=100)),
        )
        for path, base in cases:
            for omitted in ('target_points', 'time_control', 'doubling_enabled'):
                payload = {**base, **{k: v for k, v in full.items() if k != omitted}}
                with self.subTest(path=path, mode=base.get('mode', 'match'), omitted=omitted):
                    response = self.post(path, **payload)
                    self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(HeadToHeadTable.objects.exists())
        self.assertEqual(WalletTransaction.balance_for_user(self.host), 10000)
        self.assertEqual(WalletTransaction.objects.count(), 2)

    def test_quick_money_still_succeeds_without_explicit_rules(self):
        response = self.post('/api/head-to-head/quick-match', game_format='money', amounts=[100])
        self.assertEqual(response.status_code, 201, response.content)
        table = HeadToHeadTable.objects.get()
        self.assertEqual((table.game_format, table.target_points, table.time_control, table.doubling_enabled),
                         ('money', 1, 'normal', True))

    def test_one_point_match_forces_doubling_off(self):
        response = self.post('/api/head-to-head/tables', game_format='match', mode='match',
                             amount=100, target_points=1, time_control='normal', doubling_enabled=True)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertIs(response.json()['doubling_enabled'], False)
        table = HeadToHeadTable.objects.get(pk=response.json()['id'])
        self.assertEqual(table.target_points, 1)
        self.assertIs(table.doubling_enabled, False)

    def test_one_point_match_allowed_when_profile_has_only_doubling_true(self):
        self.settings.format_profiles['match']['target_points'] = [1, 3]
        self.settings.format_profiles['match']['doubling_options'] = [True]
        self.settings.save()
        response = self.post('/api/head-to-head/tables', game_format='match', mode='match',
                             amount=100, target_points=1, time_control='normal', doubling_enabled=True)
        self.assertEqual(response.status_code, 201, response.content)
        table = HeadToHeadTable.objects.get()
        self.assertEqual(table.target_points, 1)
        self.assertIs(table.doubling_enabled, False)

    def test_longer_match_keeps_configured_doubling(self):
        response = self.post('/api/head-to-head/tables', game_format='match', mode='match',
                             amount=100, target_points=3, time_control='normal', doubling_enabled=True)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertIs(HeadToHeadTable.objects.get().doubling_enabled, True)
        self.settings.format_profiles['match']['doubling_options'] = [True]
        self.settings.save()
        bad = self.post('/api/head-to-head/tables', game_format='match', mode='match',
                        amount=100, target_points=3, time_control='normal', doubling_enabled=False)
        self.assertEqual(bad.status_code, 400, bad.content)
        self.assertEqual(HeadToHeadTable.objects.count(), 1)

    def test_one_point_match_rejects_non_boolean_doubling(self):
        response = self.post('/api/head-to-head/tables', game_format='match', mode='match',
                             amount=100, target_points=1, time_control='normal', doubling_enabled='false')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(HeadToHeadTable.objects.exists())

    def test_quick_money_keeps_doubling_on_one_point(self):
        response = self.post('/api/head-to-head/quick-match', game_format='money', amounts=[100])
        self.assertEqual(response.status_code, 201, response.content)
        table = HeadToHeadTable.objects.get()
        self.assertEqual((table.game_format, table.target_points, table.doubling_enabled),
                         ('money', 1, True))

    def test_changed_profile_does_not_rewrite_waiting_game_contract(self):
        created = self.post('/api/head-to-head/quick-match', game_format='money', amounts=[100])
        self.assertEqual(created.status_code, 201, created.content)
        table = HeadToHeadTable.objects.get()
        original_profile = table.rules_snapshot.copy()
        self.settings.format_profiles['money'].update(time_controls=['fast'], fee_percent=10, max_cube=4)
        self.settings.save()
        table.refresh_from_db()
        self.assertEqual(table.rules_snapshot, original_profile)
        self.assertEqual(table.time_control, 'normal')
        self.assertEqual(table.fee_percent, 5)

    def test_disabled_quick_profile_rejects_creation_without_reservation(self):
        self.settings.format_profiles['money']['quick'] = False
        self.settings.save()
        response = self.post('/api/head-to-head/quick-match', game_format='money', amounts=[100])
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(HeadToHeadTable.objects.exists())
        self.assertEqual(WalletTransaction.balance_for_user(self.host), 10000)
