import json

from django.contrib.auth.models import User
from django.test import Client, RequestFactory, TestCase

from .account_settings import change_password


class PasswordSettingsTests(TestCase):
    old_password = 'Existing-Password-527!'
    new_password = 'Replacement-Password-864!'

    def setUp(self):
        self.user = User.objects.create_user('SettingsPlayer', password=self.old_password)
        self.client.force_login(self.user)

    def change(self, **overrides):
        data = {
            'old_password': self.old_password,
            'new_password1': self.new_password,
            'new_password2': self.new_password,
            **overrides,
        }
        return self.client.post('/api/auth/password', data, content_type='application/json')

    def assert_password_unchanged(self):
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_change_keeps_current_session_and_invalidates_other_sessions(self):
        other_client = Client()
        other_client.force_login(self.user)
        session_key = self.client.session.session_key

        response = self.change()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'password_changed'})
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))
        self.assertFalse(self.user.check_password(self.old_password))
        self.assertNotEqual(self.client.session.session_key, session_key)
        self.assertEqual(self.client.get('/api/auth/me').json()['id'], self.user.pk)
        self.assertEqual(other_client.get('/api/auth/me').status_code, 401)
        self.client.logout()
        self.assertFalse(self.client.login(username=self.user.username, password=self.old_password))
        self.assertTrue(self.client.login(username=self.user.username, password=self.new_password))

    def test_current_password_and_confirmation_are_required(self):
        for overrides, field, code in (
            ({'old_password': 'Incorrect-Password-753!'}, 'old_password', 'password_incorrect'),
            ({'old_password': ''}, 'old_password', 'required'),
            ({'new_password2': 'Different-Password-259!'}, 'new_password2', 'password_mismatch'),
        ):
            with self.subTest(field=field, code=code):
                response = self.change(**overrides)
                self.assertEqual(response.status_code, 400)
                self.assertIn({'code': code}, response.json()['errors'][field])
                self.assert_password_unchanged()

    def test_new_password_uses_configured_password_validators(self):
        response = self.change(new_password1='123', new_password2='123')
        self.assertEqual(response.status_code, 400)
        codes = {error['code'] for error in response.json()['errors']['new_password2']}
        self.assertIn('password_too_short', codes)
        self.assertIn('password_entirely_numeric', codes)
        self.assert_password_unchanged()

    def test_invalid_payload_types_and_oversized_passwords_are_rejected(self):
        for payload in ('{', '[]', 'null', b'\xff'):
            with self.subTest(payload=payload):
                response = self.client.post('/api/auth/password', payload, content_type='application/json')
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {'code': 'invalid_payload'})
        for field in ('old_password', 'new_password1', 'new_password2'):
            for value, code in ((None, 'invalid_type'), ([], 'invalid_type'), ('x' * 4097, 'max_length')):
                with self.subTest(field=field, code=code):
                    response = self.change(**{field: value})
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.json()['errors'][field], [{'code': code}])
        self.assert_password_unchanged()

    def test_authentication_csrf_and_post_are_required(self):
        self.assertEqual(Client().post('/api/auth/password', {}, content_type='application/json').status_code, 401)
        self.assertEqual(self.client.get('/api/auth/password').status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post('/api/auth/password', {}, content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assert_password_unchanged()

    def test_google_only_account_cannot_create_a_password_in_this_endpoint(self):
        self.user.set_unusable_password()
        self.user.save(update_fields=['password'])
        self.client.force_login(self.user)

        self.assertFalse(self.client.get('/api/auth/me').json()['has_usable_password'])
        response = self.change()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {'code': 'password_unavailable'})
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())

    def test_in_flight_request_cannot_use_a_stale_authenticated_user(self):
        request = RequestFactory().post('/api/auth/password', json.dumps({
            'old_password': self.new_password,
            'new_password1': 'Third-Password-915!',
            'new_password2': 'Third-Password-915!',
        }), content_type='application/json')
        request.user = User.objects.get(pk=self.user.pk)
        request.session = self.client.session
        request._dont_enforce_csrf_checks = True
        self.user.set_password(self.new_password)
        self.user.save(update_fields=['password'])

        response = change_password(request)

        self.assertEqual(response.status_code, 401)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))
