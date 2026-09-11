import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, RequestFactory
from django.core.exceptions import ValidationError

from tournaments.models import DirectPlaySettings, HeadToHeadTable, WalletTransaction
from gamelink.views import ResultCallbackView
from frontend.game_formats import required_reserve


class GameFormatTests(TestCase):
    def setUp(self):
        self.settings = DirectPlaySettings.load()
        self.host = User.objects.create_user('format-host')
        self.guest = User.objects.create_user('format-guest')
        for user in (self.host, self.guest):
            WalletTransaction.create_entry(user=user, amount=10000, kind=WalletTransaction.KIND_DEPOSIT)

    def create(self, **changes):
        self.client.force_login(self.host)
        payload = dict(game_format='money', mode='match', amount=100, target_points=1,
                       time_control='normal', doubling_enabled=True)
        payload.update(changes)
        return self.client.post('/api/head-to-head/tables', json.dumps(payload), content_type='application/json')

    def funded(self, **changes):
        response = self.create(**changes)
        self.assertEqual(response.status_code, 201, response.content)
        table = HeadToHeadTable.objects.get(pk=response.json()['id'])
        self.client.force_login(self.guest)
        joined = self.client.post(f'/api/head-to-head/tables/{table.code}/join')
        self.assertEqual(joined.status_code, 200, joined.content)
        table.refresh_from_db()
        return table

    def result(self, table, **changes):
        body = dict(status='completed', room_id='format-room', winner_seat='p1',
                    financial_result=dict(format='money', cube=2, win_type='gammon'))
        body.update(changes)
        return ResultCallbackView()._record_direct_play(RequestFactory().post('/api/gamelink/result/'), table.pk, body)

    def balance(self, user):
        return WalletTransaction.balance_for_user(user)

    def test_money_reserves_max_loss_and_settles_cube_gammon_once(self):
        table = self.funded()
        self.assertEqual(self.balance(self.host), 9200)
        self.assertEqual(self.balance(self.guest), 9200)
        self.assertEqual(self.result(table).status_code, 200)
        self.assertEqual(self.balance(self.host), 10380)
        self.assertEqual(self.balance(self.guest), 9600)
        self.assertEqual(self.result(table).status_code, 200)
        self.assertEqual(self.balance(self.host), 10380)
        table.refresh_from_db()
        self.assertEqual(table.settlement['transfer'], '400.00')

    def test_loss_limit_caps_backgammon(self):
        table = self.funded()
        self.assertEqual(self.result(table, financial_result=dict(format='money', cube=8, win_type='backgammon')).status_code, 200)
        self.assertEqual(self.balance(self.guest), 9200)
        self.assertEqual(self.balance(self.host), 10760)

    def test_jacoby_and_fixed_match(self):
        for name, jacoby, expected in [('money', True, 100), ('money', False, 300), ('match', False, 100)]:
            with self.subTest(name=name, jacoby=jacoby):
                row = DirectPlaySettings.load()
                row.format_profiles[name]['jacoby'] = jacoby
                row.save()
                before = self.balance(self.host)
                table = self.funded(game_format=name, target_points=5 if name == 'match' else 1)
                response = self.result(table, financial_result=dict(format=name, cube=1 if name == 'money' else 64, win_type='backgammon'))
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(self.balance(self.host), before + Decimal(expected) * Decimal('.95'))

    def test_private_has_same_financial_contract_and_cancellation_refunds(self):
        table = self.funded(mode='friend')
        self.assertEqual(len(table.code), 4)
        self.assertEqual(self.balance(self.host), 9200)
        self.client.force_login(self.host)
        self.assertEqual(self.client.post(f'/api/head-to-head/tables/{table.code}/cancel').status_code, 200)
        self.assertEqual(self.balance(self.host), 10000)
        self.assertEqual(self.balance(self.guest), 10000)
        self.assertEqual(self.result(table).status_code, 409)

    def test_insufficient_reserve_rolls_back_table_and_join(self):
        response = self.create(amount=2000)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(HeadToHeadTable.objects.exists())
        created = self.create()
        WalletTransaction.create_entry(user=self.guest, amount=-9500, kind=WalletTransaction.KIND_HEAD_TO_HEAD_ENTRY)
        self.client.force_login(self.guest)
        result = self.client.post(f"/api/head-to-head/tables/{created.json()['code']}/join")
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.balance(self.guest), 500)
        self.assertIsNone(HeadToHeadTable.objects.get().guest_id)

    def test_invalid_results_leave_reserves_untouched(self):
        table = self.funded()
        for result in (None, {}, dict(format='money', cube=64, win_type='single'), dict(format='money', cube=True, win_type='single')):
            self.assertEqual(self.result(table, financial_result=result).status_code, 409)
            self.assertEqual(self.balance(self.host), 9200)
            self.assertEqual(self.balance(self.guest), 9200)

    def test_snapshot_is_immutable_but_disabled_format_blocks_join(self):
        response = self.create()
        table = HeadToHeadTable.objects.get(pk=response.json()['id'])
        self.settings.format_profiles['money'].update(loss_limit_multiplier=16, fee_percent=10, enabled=False)
        self.settings.save()
        self.client.force_login(self.guest)
        self.assertEqual(self.client.post(f'/api/head-to-head/tables/{table.code}/join').status_code, 400)
        self.settings.format_profiles['money']['enabled'] = True
        self.settings.save()
        self.assertEqual(self.client.post(f'/api/head-to-head/tables/{table.code}/join').status_code, 200)
        table.refresh_from_db()
        self.assertEqual(required_reserve(table), 800)
        self.assertEqual(table.fee_percent, 5)

    def test_quick_intersection_reserves_max_and_refunds_unused(self):
        payload = dict(game_format='money', amounts=[100, 500], target_points=1, time_control='normal', doubling_enabled=True)
        self.client.force_login(self.host)
        a = self.client.post('/api/head-to-head/quick-match', json.dumps(payload), content_type='application/json')
        self.assertEqual(a.status_code, 201, a.content)
        self.assertEqual(self.balance(self.host), 6000)
        again = self.client.post('/api/head-to-head/quick-match', json.dumps(payload), content_type='application/json')
        self.assertEqual(again.json()['id'], a.json()['id'])
        self.assertEqual(self.balance(self.host), 6000)
        self.client.force_login(self.guest)
        payload['amounts'] = [100]
        b = self.client.post('/api/head-to-head/quick-match', json.dumps(payload), content_type='application/json')
        self.assertTrue(b.json()['matched'])
        table = HeadToHeadTable.objects.get(pk=b.json()['id'])
        self.assertEqual(self.result(table).status_code, 200)
        self.assertEqual(self.balance(self.host), 10380)

    def test_admin_profiles_roundtrip_and_incompatible_rules_rejected(self):
        self.host.is_staff = True
        self.host.save()
        self.client.force_login(self.host)
        profiles = self.settings.format_profiles
        profiles['money']['stake_amounts'] = [300, 700]
        response = self.client.put('/api/admin/direct-play/settings', json.dumps(dict(format_profiles=profiles)), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.client.get('/api/head-to-head/tables').json()['format_profiles']['money']['stake_amounts'], [300, 700])
        profiles['money']['target_points'] = [5]
        response = self.client.put('/api/admin/direct-play/settings', json.dumps(dict(format_profiles=profiles)), content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_malformed_creation_returns_validation_error(self):
        self.client.force_login(self.host)
        for payload in ([], None, 'money', 100):
            response = self.client.post('/api/head-to-head/tables', json.dumps(payload), content_type='application/json')
            self.assertEqual(response.status_code, 400)
        self.assertFalse(HeadToHeadTable.objects.exists())
