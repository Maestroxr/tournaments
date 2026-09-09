from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from tournaments.models import WalletTransaction


class TransferControlsTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='transfer-admin', is_staff=True)
        self.alice = User.objects.create_user(username='alice')
        self.bob = User.objects.create_user(username='bob')
        self.client.force_login(self.staff)

    def test_note_is_required_before_any_balance_change(self):
        url = reverse('api-admin-user-wallet', kwargs={'pk': self.alice.pk})
        for note in (None, '', '   ', 12, 'x' * 256):
            with self.subTest(note=note):
                response = self.client.post(url, {'action': 'deposit', 'amount': '10', 'note': note}, content_type='application/json')
                self.assertEqual(response.status_code, 400)
        self.assertFalse(WalletTransaction.objects.exists())
        response = self.client.post(url, {'action': 'deposit', 'amount': '10', 'note': '  Verified correction  '}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WalletTransaction.objects.get().note, 'Verified correction')
        self.assertEqual(WalletTransaction.balance_for_user(self.alice), Decimal('10'))

    def test_user_filter_is_exact_and_pagination_is_stable(self):
        ids = []
        for i in range(3):
            entry = WalletTransaction.create_entry(user=self.alice, amount=Decimal('1'), kind=WalletTransaction.KIND_DEPOSIT, actor=self.staff, note=f'Alice {i}')
            ids.append(entry.pk)
        WalletTransaction.create_entry(user=self.bob, amount=Decimal('4'), kind=WalletTransaction.KIND_DEPOSIT, actor=self.staff, note='alice')
        url = reverse('api-admin-wallet-transactions')
        first = self.client.get(url, {'user_id': self.alice.pk, 'limit': 2}).json()
        second = self.client.get(url, {'user_id': self.alice.pk, 'limit': 2, 'offset': 2}).json()
        self.assertEqual(first['count'], 3)
        self.assertEqual([entry['id'] for entry in first['items'] + second['items']], list(reversed(ids)))
        self.assertEqual(self.client.get(url, {'user_id': 'invalid'}).status_code, 400)
        self.assertEqual(self.client.get(url, {'offset': 'invalid'}).status_code, 400)

    def test_nonstaff_cannot_list_transfers(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse('api-admin-wallet-transactions')).status_code, 403)
