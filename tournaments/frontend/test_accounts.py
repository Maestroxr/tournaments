from datetime import timedelta
from urllib.parse import parse_qs
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .models import AccountEmail
from tournaments.models import UserContact


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', ACCOUNT_FRONTEND_URL='https://website.example')
class AccountJourneyTests(TestCase):
    def post(self, path, data, client=None):
        return (client or self.client).post('/api/auth/' + path, data, content_type='application/json')

    def signup(self):
        response = self.post('signup', {'username': 'Alice', 'email': 'Alice@example.com',
            'phone_number': '050-123-4567',
            'password1': 'Another-Good-Secret-735!', 'password2': 'Another-Good-Secret-735!'})
        self.assertEqual(response.status_code, 201, response.content)
        return User.objects.get(username='Alice')

    def link(self):
        query = mail.outbox[-1].body.split('#', 1)[1].splitlines()[0]
        return {key: values[0] for key, values in parse_qs(query).items()}

    def test_signup_verify_reset_and_session_revocation(self):
        user = self.signup()
        self.assertFalse(user.is_active)
        self.assertEqual(self.post('login', {'username': 'Alice', 'password': 'Another-Good-Secret-735!'}).status_code, 401)
        verify = self.link()
        self.assertEqual(self.post('verify/confirm', verify).status_code, 200)
        self.assertEqual(self.post('verify/confirm', verify).status_code, 400)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertEqual(self.post('login', {'username': 'Alice', 'password': 'Another-Good-Secret-735!'}).status_code, 200)
        AccountEmail.objects.update(last_sent_at=timezone.now() - timedelta(minutes=2))
        self.assertEqual(self.post('reset/request', {'email': 'ALICE@example.com'}).status_code, 200)
        reset = self.link()
        reset.update(new_password1='Replacement-Secret-825!', new_password2='Replacement-Secret-825!')
        self.assertEqual(self.post('reset/confirm', reset, Client()).status_code, 200)
        self.assertEqual(self.post('reset/confirm', reset, Client()).status_code, 400)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.assertEqual(self.post('login', {'username': 'Alice', 'password': 'Replacement-Secret-825!'}).status_code, 200)
        self.assertEqual(User.objects.get(username='Alice').pk, user.pk)

    def test_unknown_address_does_not_disclose_account_or_send_mail(self):
        user = self.signup()
        known = self.post('reset/request', {'email': user.email})
        unknown = self.post('reset/request', {'email': 'missing@example.com'})
        self.assertEqual(known.json(), unknown.json())
        self.assertEqual(len(mail.outbox), 1)

    def prepare_reset(self):
        user = self.signup()
        self.assertEqual(self.post('verify/confirm', self.link()).status_code, 200)
        AccountEmail.objects.update(last_sent_at=None)
        self.assertEqual(self.post('reset/request', {'email': user.email}).status_code, 200)
        return user, self.link()

    def test_reset_rejects_expired_and_tampered_links_without_changing_password(self):
        user, token = self.prepare_reset()
        data = {**token, 'new_password1': 'Replacement-Secret-825!', 'new_password2': 'Replacement-Secret-825!'}
        self.assertEqual(self.post('reset/confirm', {**data, 'token': token['token'] + 'x'}).status_code, 400)
        with override_settings(PASSWORD_RESET_TIMEOUT=-1):
            self.assertEqual(self.post('reset/confirm', data).status_code, 400)
        user.refresh_from_db()
        self.assertTrue(user.check_password('Another-Good-Secret-735!'))

    def test_reset_validates_password_and_allows_retry_with_same_link(self):
        user, token = self.prepare_reset()
        for first, second in [('short', 'short'), ('123456789', '123456789'), ('Replacement-Secret-825!', 'Different-Secret-825!')]:
            response = self.post('reset/confirm', {**token, 'new_password1': first, 'new_password2': second})
            self.assertEqual(response.status_code, 400)
            self.assertIn('errors', response.json())
        self.assertEqual(self.post('reset/confirm', {**token, 'new_password1': 'Replacement-Secret-825!', 'new_password2': 'Replacement-Secret-825!'}).status_code, 200)
        self.assertEqual(self.post('login', {'username': user.username, 'password': 'Another-Good-Secret-735!'}).status_code, 401)
        self.assertEqual(self.post('login', {'username': user.username, 'password': 'Replacement-Secret-825!'}).status_code, 200)

    def test_reset_cooldown_and_inactive_account_do_not_send_mail(self):
        user, _ = self.prepare_reset()
        count = len(mail.outbox)
        self.post('reset/request', {'email': user.email})
        self.assertEqual(len(mail.outbox), count)
        AccountEmail.objects.update(last_sent_at=timezone.now() - timedelta(seconds=61))
        self.post('reset/request', {'email': user.email})
        self.assertEqual(len(mail.outbox), count + 1)
        AccountEmail.objects.update(last_sent_at=None)
        User.objects.filter(pk=user.pk).update(is_active=False)
        self.post('reset/request', {'email': user.email})
        self.assertEqual(len(mail.outbox), count + 1)

    def test_signup_requires_a_phone_number(self):
        response = self.post('signup', {'username': 'NoPhone', 'email': 'no-phone@example.com',
            'password1': 'Another-Good-Secret-735!', 'password2': 'Another-Good-Secret-735!'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('phone_number', response.json()['errors'])

    def test_signup_rejects_mixed_alphabet_username(self):
        response = self.post('signup', {'username': 'CקרGםד', 'email': 'new@example.com',
            'phone_number': '0501234567', 'password1': 'Another-Good-Secret-735!',
            'password2': 'Another-Good-Secret-735!'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('username', response.json()['errors'])
        self.assertFalse(User.objects.filter(email='new@example.com').exists())

    def test_legacy_user_can_complete_phone_number_from_profile(self):
        user = User.objects.create_user('legacy', password='Another-Good-Secret-735!')
        self.client.force_login(user)
        self.assertEqual(self.client.post('/api/tournaments/999/join').status_code, 412)
        response = self.client.put('/api/auth/profile', {'phone_number': '050-123-4567'}, content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(UserContact.objects.get(user=user).phone_number, '050-123-4567')

    def test_expired_tampered_and_wrong_purpose_tokens_are_rejected(self):
        self.signup()
        data = self.link()
        self.assertEqual(self.post('reset/confirm', data).status_code, 400)
        self.assertEqual(self.post('verify/confirm', {**data, 'token': data['token'] + 'x'}).status_code, 400)
        with override_settings(PASSWORD_RESET_TIMEOUT=-1):
            self.assertEqual(self.post('verify/confirm', data).status_code, 400)

    def test_csrf_required_for_account_mutations(self):
        client = Client(enforce_csrf_checks=True)
        for path in ['login', 'logout', 'signup', 'verify/request', 'verify/confirm', 'reset/request', 'reset/confirm']:
            self.assertEqual(self.post(path, {}, client).status_code, 403, path)

    def test_resend_cooldown_and_email_failure_is_retryable(self):
        self.signup()
        self.post('verify/request', {'email': 'alice@example.com'})
        self.assertEqual(len(mail.outbox), 1)
        AccountEmail.objects.update(last_sent_at=None)
        with patch('frontend.accounts.send_mail', side_effect=OSError('mail unavailable')):
            self.assertEqual(self.post('verify/request', {'email': 'alice@example.com'}).status_code, 200)
        self.post('verify/request', {'email': 'alice@example.com'})
        self.assertEqual(len(mail.outbox), 2)


class AdministratorBoundaryTests(TestCase):
    def test_operator_cannot_take_over_admin_or_promote_player(self):
        operator = User.objects.create_user('operator', is_staff=True)
        root = User.objects.create_superuser('root', password='root-secret')
        player = User.objects.create_user('player')
        self.client.force_login(operator)
        for user in [operator, root]:
            response = self.client.put(f'/api/admin/users/{user.pk}', {'new_password': 'Takeover-Secret-914!'}, content_type='application/json')
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.put(f'/api/admin/users/{player.pk}', {'is_staff': True}, content_type='application/json').status_code, 403)
        self.assertEqual(self.client.delete(f'/api/admin/users/{root.pk}').status_code, 403)
        self.assertEqual(self.client.post(f'/users/{root.pk}/delete').status_code, 403)

    def test_only_superuser_can_grant_staff(self):
        root = User.objects.create_superuser('root', password='root-secret')
        player = User.objects.create_user('player')
        UserContact.objects.create(user=player, phone_number='050-123-4567')
        self.client.force_login(root)
        self.assertEqual(self.client.put(f'/api/admin/users/{player.pk}', {'is_staff': True}, content_type='application/json').status_code, 200)
        player.refresh_from_db()
        self.assertTrue(player.is_staff)
