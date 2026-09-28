import time
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.test import TestCase, override_settings

from tournaments.models import UserContact, WalletTransaction
from .models import AccountEmail, GoogleIdentity


@override_settings(
    GOOGLE_CLIENT_ID='test-client.apps.googleusercontent.com',
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)
class SignupBonusTests(TestCase):
    def signup(self, method):
        if method == 'google':
            nonce = self.client.post('/api/auth/google/config').json()['nonce']
            claims = {'sub': 'bonus-player', 'email': 'player@gmail.com',
                      'email_verified': True, 'nonce': nonce}
            with patch('frontend.google_auth.verify_credential', return_value=claims):
                return self.client.post('/api/auth/google', {'credential': 'signed-token'},
                                        content_type='application/json')
        if method == 'legacy_google':
            session = self.client.session
            session['google_pending'] = {'subject': 'bonus-player', 'email': 'player@gmail.com',
                                         'verified': True, 'issued': time.time()}
            session.save()
            return self.client.post('/api/auth/google/complete', {
                'username': 'Player', 'phone_number': '0501234567', 'password': 'River!Board942',
            }, content_type='application/json')
        return self.client.post('/api/auth/signup', {
            'username': 'Player', 'email': 'player@gmail.com', 'phone_number': '0501234567',
            'password1': 'River!Board942', 'password2': 'River!Board942',
        }, content_type='application/json')

    def assert_signup_bonus(self, method):
        response = self.signup(method)
        self.assertEqual(response.status_code, 201 if method == 'password' else 200, response.content)
        user = User.objects.get()
        entry = user.wallet_transactions.get()
        self.assertEqual(entry.kind, WalletTransaction.KIND_DEPOSIT)
        self.assertEqual(entry.note, 'בונוס הרשמה')
        self.assertEqual(entry.amount, Decimal('1000.00'))
        self.assertEqual(entry.balance_after, Decimal('1000.00'))
        self.assertEqual(Decimal(self.client.get('/api/auth/me').json()['balance']), Decimal('1000.00'))

        self.client.logout()
        repeated = self.signup(method)
        expected_status = {'password': 400, 'google': 200, 'legacy_google': 400}[method]
        self.assertEqual(repeated.status_code, expected_status, repeated.content)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(user.wallet_transactions.count(), 1)
        self.assertEqual(WalletTransaction.balance_for_user(user), Decimal('1000.00'))

    def test_password_signup_grants_1000_coins_once(self):
        self.assert_signup_bonus('password')
        response = self.client.post('/api/auth/login', {
            'username': 'Player', 'password': 'River!Board942',
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(self.client.get('/api/auth/me').json()['balance']), Decimal('1000.00'))
        self.assertEqual(WalletTransaction.objects.count(), 1)

    def test_google_signup_grants_1000_coins_once(self):
        self.assert_signup_bonus('google')

    def test_legacy_google_signup_grants_1000_coins_once(self):
        self.assert_signup_bonus('legacy_google')
        self.assertEqual(self.signup('google').status_code, 200)
        self.assertEqual(WalletTransaction.objects.count(), 1)

    def test_existing_accounts_do_not_receive_signup_bonus_on_login(self):
        user = User.objects.create_user('Existing', password='River!Board942')
        GoogleIdentity.objects.create(user=user, subject='bonus-player')
        response = self.client.post('/api/auth/login', {
            'username': 'Existing', 'password': 'River!Board942',
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.client.logout()
        self.assertEqual(self.signup('google').status_code, 200)
        self.assertFalse(WalletTransaction.objects.exists())
        self.assertEqual(self.client.get('/api/auth/me').json()['balance'], '0.00')

    def test_bonus_failure_rolls_back_account_creation(self):
        for method in ['password', 'google', 'legacy_google']:
            with self.subTest(method=method):
                with patch('tournaments.models.WalletTransaction.create_entry',
                           side_effect=IntegrityError('bonus write failed')):
                    response = self.signup(method)
                self.assertEqual(response.status_code, 400 if method == 'password' else 409)
                self.assertFalse(User.objects.exists())
                self.assertFalse(AccountEmail.objects.exists())
                self.assertFalse(GoogleIdentity.objects.exists())
                self.assertFalse(UserContact.objects.exists())
                self.assertFalse(WalletTransaction.objects.exists())
                self.assertNotIn('_auth_user_id', self.client.session)
