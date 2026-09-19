from django.contrib.auth.models import User
from django.test import Client, TestCase

from tournaments.models import UserContact


class ProfileUsernameTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('Original', password='Secret-735!')
        UserContact.objects.create(user=self.user, phone_number='0501234567')
        self.client.force_login(self.user)

    def update(self, data):
        return self.client.put('/api/auth/profile', data, content_type='application/json')

    def test_rename_preserves_account_phone_and_session(self):
        response = self.update({'username': ' NewName42 ', 'is_staff': True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['username'], 'NewName42')
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'NewName42')
        self.assertFalse(self.user.is_staff)
        self.assertEqual(UserContact.objects.get(user=self.user).phone_number, '0501234567')
        self.assertEqual(self.client.get('/api/auth/me').json()['id'], self.user.pk)
        self.client.logout()
        self.assertTrue(self.client.login(username='NewName42', password='Secret-735!'))

    def test_invalid_and_taken_names_do_not_change_account(self):
        User.objects.create_user('Taken')
        for name in ['', '   ', 'bad name', 'a' * 151, 'TAKEN', None, 123, 'שם']:
            with self.subTest(name=name):
                response = self.update({'username': name, 'phone_number': '0507654321'})
                self.assertEqual(response.status_code, 400)
                self.assertIn('username', response.json()['errors'])
                self.user.refresh_from_db()
                self.assertEqual(self.user.username, 'Original')
                self.assertEqual(UserContact.objects.get(user=self.user).phone_number, '0501234567')

    def test_same_name_and_phone_only_remain_supported(self):
        self.assertEqual(self.update({'username': 'Original'}).status_code, 200)
        self.assertEqual(self.update({'phone_number': '0507654321'}).status_code, 200)

    def test_authentication_csrf_and_payload_validation(self):
        self.assertEqual(self.update([]).status_code, 400)
        self.assertEqual(self.update({}).status_code, 400)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.put('/api/auth/profile', {'username': 'NewName'}, content_type='application/json').status_code, 403)
        self.client.logout()
        self.assertEqual(self.update({'username': 'NewName'}).status_code, 401)
