from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, SimpleTestCase, TestCase, override_settings

from .models import AccountEmail, GoogleIdentity
from tournaments.models import UserContact


@override_settings(GOOGLE_CLIENT_ID='test-client.apps.googleusercontent.com')
class GoogleSignatureTests(SimpleTestCase):
    def test_real_verifier_checks_signature_issuer_audience_and_expiry(self):
        import time
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from google.auth import crypt, jwt
        from .google_auth import verify_credential

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        signer = crypt.RSASigner.from_string(private, key_id='test-key')
        now = int(time.time())
        claims = {'sub': 'subject', 'iss': 'https://accounts.google.com', 'aud': 'test-client.apps.googleusercontent.com', 'iat': now, 'exp': now + 600}
        with patch('google.oauth2.id_token._fetch_certs', return_value={'test-key': public}):
            valid = jwt.encode(signer, claims).decode()
            self.assertEqual(verify_credential(valid)['sub'], 'subject')
            for change in [{'aud': 'another-app'}, {'iss': 'https://attacker.example'}, {'iat': now - 1200, 'exp': now - 600}]:
                with self.assertRaises(ValueError):
                    verify_credential(jwt.encode(signer, {**claims, **change}).decode())
            parts = valid.split('.')
            parts[2] = ('A' if parts[2][0] != 'A' else 'B') + parts[2][1:]
            with self.assertRaises(ValueError):
                verify_credential('.'.join(parts))


@override_settings(GOOGLE_CLIENT_ID='test-client.apps.googleusercontent.com', EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class GoogleAuthTests(TestCase):
    def post(self, path, data=None, client=None):
        return (client or self.client).post('/api/auth/google' + path, data or {}, content_type='application/json')

    def authenticate(self, **overrides):
        nonce = self.post('/config').json()['nonce']
        claims = {'sub': 'google-subject-1', 'email': 'player@gmail.com', 'email_verified': True, 'nonce': nonce}
        claims.update(overrides)
        with patch('frontend.google_auth.verify_credential', return_value=claims):
            return self.post('', {'credential': 'signed-google-token'})

    def complete(self, **data):
        return self.post('/complete', {'username': 'player', 'phone_number': '050-123-4567', **data})

    def test_new_account_requires_profile_then_creates_verified_passwordless_account(self):
        response = self.authenticate()
        self.assertEqual(response.json()['status'], 'profile_required')
        self.assertFalse(User.objects.exists())
        self.assertEqual(self.complete().json()['status'], 'authenticated')
        user = User.objects.get(username='Player')
        self.assertFalse(user.has_usable_password())
        self.assertTrue(user.is_active)
        self.assertIsNotNone(user.account_email.verified_at)
        self.assertEqual(user.google_identity.subject, 'google-subject-1')
        self.assertEqual(UserContact.objects.get(user=user).phone_number, '050-123-4567')
        self.assertEqual(self.client.get('/api/auth/me').status_code, 200)
        self.assertEqual(self.complete().status_code, 400)

    def test_returning_user_is_identified_by_subject_even_when_email_changes(self):
        self.authenticate()
        self.complete()
        self.client.logout()
        self.assertEqual(self.authenticate(email='changed@gmail.com').json()['status'], 'authenticated')
        self.assertEqual(User.objects.count(), 1)

    def test_inactive_user_cannot_sign_in(self):
        self.authenticate()
        self.complete()
        User.objects.update(is_active=False)
        self.client.logout()
        self.assertEqual(self.authenticate().status_code, 403)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_existing_email_is_not_automatically_linked(self):
        User.objects.create_user('existing', email='PLAYER@gmail.com')
        self.assertEqual(self.authenticate().status_code, 409)
        self.assertFalse(GoogleIdentity.objects.exists())
        self.assertNotIn('google_pending', self.client.session)

    def test_nonce_is_required_matches_and_cannot_be_reused(self):
        self.assertEqual(self.post('', {'credential': 'token'}).status_code, 400)
        self.assertEqual(self.authenticate(nonce='wrong').status_code, 401)
        self.assertEqual(self.authenticate().status_code, 200)
        self.client.session.flush()
        self.assertEqual(self.post('', {'credential': 'token'}).status_code, 400)

    def test_two_open_tabs_keep_independent_challenges_and_reject_replay(self):
        first = self.post('/config').json()['nonce']
        second = self.post('/config').json()['nonce']
        for nonce in [first, second]:
            claims = {'nonce': nonce, 'sub': 'same-subject', 'email': 'player@gmail.com', 'email_verified': True}
            with patch('frontend.google_auth.verify_credential', return_value=claims):
                self.assertEqual(self.post('', {'credential': 'token'}).status_code, 200)
                self.assertIn(self.post('', {'credential': 'token'}).status_code, [400, 401])

    def test_nonce_is_bound_to_browser_session(self):
        nonce = self.post('/config').json()['nonce']
        other = Client()
        self.post('/config', client=other)
        with patch('frontend.google_auth.verify_credential', return_value={'nonce': nonce}):
            self.assertEqual(self.post('', {'credential': 'token'}, client=other).status_code, 401)

    def test_invalid_signature_audience_or_expiry_rejection(self):
        for reason in ['signature', 'audience', 'expired']:
            self.post('/config')
            with patch('frontend.google_auth.verify_credential', side_effect=ValueError(reason)):
                self.assertEqual(self.post('', {'credential': 'token'}).status_code, 401)
        self.assertFalse(User.objects.exists())

    def test_unverified_email_rejected(self):
        self.assertEqual(self.authenticate(email_verified=False).status_code, 401)

    def test_non_google_email_needs_email_verification(self):
        self.authenticate(email='player@example.com')
        self.assertEqual(self.complete().json()['status'], 'verification_required')
        self.assertFalse(User.objects.get().is_active)
        self.assertIsNone(AccountEmail.objects.get().verified_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_profile_validation_and_expiry(self):
        self.authenticate()
        self.assertEqual(self.complete(username='CקרGםד').status_code, 400)
        self.assertEqual(self.complete(phone_number='').status_code, 400)
        self.assertEqual(self.complete(username='').status_code, 400)
        self.assertFalse(User.objects.exists())
        session = self.client.session
        pending = session['google_pending']
        pending['issued'] -= 601
        session['google_pending'] = pending
        session.save()
        self.assertEqual(self.complete().json()['code'], 'expired')

    def test_identity_and_email_races_do_not_create_orphan_users(self):
        self.authenticate()
        other = User.objects.create_user('other', email='other@gmail.com')
        GoogleIdentity.objects.create(user=other, subject='google-subject-1')
        self.assertEqual(self.complete().status_code, 409)
        self.assertEqual(User.objects.count(), 1)

    def test_csrf_required_for_all_endpoints(self):
        client = Client(enforce_csrf_checks=True)
        for path in ['/config', '', '/complete']:
            self.assertEqual(self.post(path, client=client).status_code, 403)

    @override_settings(GOOGLE_CLIENT_ID='')
    def test_disabled_configuration(self):
        self.assertEqual(self.post('/config').json(), {'enabled': False})
        self.assertEqual(self.post('').status_code, 503)
        self.assertEqual(self.complete().status_code, 503)
