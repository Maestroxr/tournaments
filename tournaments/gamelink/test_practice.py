import json
import uuid
from decimal import Decimal
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import urlparse, parse_qs

from django.contrib.auth.models import User
from django.core import signing
from django.test import TestCase, override_settings
from tournaments.models import DirectPlaySettings, WalletTransaction
from gamelink.models import PracticePurchase


@override_settings(GAMELINK_ENABLED=True, GAMELINK_BACKGAMMON_URL='https://game.example',
    GAMELINK_TICKET_SECRET='practice-test-secret', GAMELINK_ISSUER='club', GAMELINK_AUDIENCE='game')
class PracticeEntryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('practice-test-user')
        self.client.force_login(self.user)
        self.room = str(uuid.uuid4())
        self.data = {'request_id': str(uuid.uuid4()), 'difficulty': 'medium',
            'target_points': 5, 'time_control': 'normal', 'doubling_enabled': True, 'fee': '50.00'}
        WalletTransaction.create_entry(user=self.user, amount=200, kind='deposit')

    def prepare(self, base, token):
        data = signing.loads(token, key='practice-test-secret', salt='gamelink.practice.v1')
        self.assertEqual(data['purpose'], 'prepare')
        self.assertEqual(data['tp'], 5)
        return {'room_id': self.room, 'purchase_id': data['purchase_id']}

    def start(self):
        return self.client.post('/api/practice/', self.data, content_type='application/json')

    def test_payment_once_and_signed_settings_on_retry(self):
        with patch('gamelink.practice.prepare_room', side_effect=self.prepare):
            response = self.start()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.start().status_code, 200)
        ticket = parse_qs(urlparse(response.json()['url']).query)['ticket'][0]
        data = signing.loads(ticket, key='practice-test-secret', salt='gamelink.practice.v1')
        self.assertEqual((data['purpose'], data['tp'], data['tc'], data['dbl']), ('enter', 5, 'normal', True))
        self.assertEqual(WalletTransaction.balance_for_user(self.user), Decimal('150'))
        self.assertEqual(WalletTransaction.objects.filter(kind='ai_game_fee').count(), 1)
        self.assertTrue(PracticePurchase.objects.get(pk=self.data['request_id']).paid)

    def test_resume_with_new_request_does_not_charge_again(self):
        original = self.data['request_id']
        with patch('gamelink.practice.prepare_room', side_effect=self.prepare):
            self.assertEqual(self.start().status_code, 200)
        self.data['request_id'] = str(uuid.uuid4())
        with patch('gamelink.practice.prepare_room', return_value={'room_id': self.room, 'purchase_id': original}):
            self.assertEqual(self.start().status_code, 200)
        self.assertEqual(WalletTransaction.balance_for_user(self.user), Decimal('150'))

    def test_unavailable_does_not_charge_and_same_request_can_retry(self):
        with patch('gamelink.practice.prepare_room', side_effect=URLError('offline')):
            self.assertEqual(self.start().status_code, 503)
        self.assertEqual(WalletTransaction.balance_for_user(self.user), Decimal('200'))
        with patch('gamelink.practice.prepare_room', side_effect=self.prepare):
            self.assertEqual(self.start().status_code, 200)
        self.assertEqual(WalletTransaction.objects.filter(kind='ai_game_fee').count(), 1)

    def test_insufficient_funds_no_ticket_or_charge(self):
        WalletTransaction.create_entry(user=self.user, amount=-180, kind='withdrawal')
        with patch('gamelink.practice.prepare_room', side_effect=self.prepare):
            response = self.start()
        self.assertEqual(response.status_code, 402)
        self.assertNotIn('url', response.json())
        self.assertFalse(WalletTransaction.objects.filter(kind='ai_game_fee').exists())

    def test_admin_price_and_quote_validation(self):
        row = DirectPlaySettings.load()
        row.ai_game_fee = Decimal('75')
        row.save()
        self.assertEqual(self.client.get('/api/practice/').json()['fee'], '75.00')
        self.assertEqual(self.start().status_code, 409)
        self.data['fee'] = '75'
        with patch('gamelink.practice.prepare_room', side_effect=self.prepare):
            self.assertEqual(self.start().status_code, 200)
        self.assertEqual(WalletTransaction.balance_for_user(self.user), Decimal('125'))

    def test_invalid_settings_and_foreign_request(self):
        self.data['target_points'] = 2
        self.assertEqual(self.start().status_code, 400)
        self.data['target_points'] = 5
        with patch('gamelink.practice.prepare_room', side_effect=self.prepare):
            self.assertEqual(self.start().status_code, 200)
        other = User.objects.create_user('other-practice')
        self.client.force_login(other)
        self.assertEqual(self.start().status_code, 403)

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.start().status_code, 302)

    def test_price_edit_requires_staff_and_rejects_negative(self):
        url = '/api/admin/direct-play/settings'
        self.assertEqual(self.client.put(url, {'ai_game_fee': '70'}, content_type='application/json').status_code, 403)
        self.user.is_staff = True
        self.user.save(update_fields=['is_staff'])
        response = self.client.put(url, {'ai_game_fee': '70'}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['ai_game_fee'], '70.00')
        self.assertEqual(self.client.put(url, {'ai_game_fee': '-1'}, content_type='application/json').status_code, 400)
        self.assertEqual(DirectPlaySettings.load().ai_game_fee, Decimal('70'))

    def test_zero_price_does_not_create_zero_value_wallet_entry(self):
        row = DirectPlaySettings.load()
        row.ai_game_fee = 0
        row.save()
        self.data['fee'] = '0'
        with patch('gamelink.practice.prepare_room', side_effect=self.prepare):
            self.assertEqual(self.start().status_code, 200)
        self.assertFalse(WalletTransaction.objects.filter(kind='ai_game_fee').exists())
