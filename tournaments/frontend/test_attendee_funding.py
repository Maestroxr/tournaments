from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from tournaments.models import Tournament, UserContact, WalletTransaction


class AttendeeFundingTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='organizer', is_staff=True)
        self.player = User.objects.create_user(username='player')
        UserContact.objects.create(user=self.player, phone_number='0501234567')
        self.client.force_login(self.staff)
        response = self.client.post(reverse('api-admin-tournaments'), data={
            'name': 'Club tournament', 'template': 'knockout', 'min_players': 2,
            'max_players': 8, 'open_registration': True, 'entry_fee': '50.00',
        }, content_type='application/json')
        self.assertEqual(response.status_code, 201, response.content)
        self.tournament = Tournament.objects.get(pk=response.json()['id'])
        self.url = reverse('api-admin-tournament-attendees', kwargs={'pk': self.tournament.pk})
        WalletTransaction.create_entry(user=self.player, amount=Decimal('20.00'),
                                       kind=WalletTransaction.KIND_DEPOSIT, actor=self.staff)

    def test_available_users_include_actual_balance_and_default_zero(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        balances = {u['id']: Decimal(u['balance']) for u in response.json()['available']}
        self.assertEqual(balances[self.player.pk], Decimal('20.00'))
        self.assertEqual(balances[self.staff.pk], Decimal('0.00'))

    def test_insufficient_balance_returns_shortfall_without_charging(self):
        response = self.client.post(self.url, {'user_id': self.player.pk}, content_type='application/json')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()['code'], 'insufficient_funds')
        self.assertEqual(Decimal(response.json()['shortfall']), Decimal('30.00'))
        self.assertEqual(WalletTransaction.balance_for_user(self.player), Decimal('20.00'))
        self.assertEqual(self.tournament.participations.count(), 0)

    def test_top_up_then_register_charges_once_and_keeps_registration_open(self):
        response = self.client.post(reverse('api-admin-user-wallet', kwargs={'pk': self.player.pk}),
                                    {'action': 'deposit', 'amount': '30.00', 'note': 'Tournament top-up'}, content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Decimal(response.json()['balance']), Decimal('50.00'))
        self.assertEqual(self.tournament.participations.count(), 0)
        response = self.client.post(self.url, {'user_id': self.player.pk}, content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.tournament.participations.count(), 1)
        self.assertEqual(WalletTransaction.balance_for_user(self.player), Decimal('0.00'))
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.state, 'open')
        response = self.client.post(self.url, {'user_id': self.player.pk}, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(WalletTransaction.balance_for_user(self.player), Decimal('0.00'))

    def test_nonstaff_cannot_read_balances_or_credit_wallets(self):
        self.client.force_login(self.player)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        response = self.client.post(reverse('api-admin-user-wallet', kwargs={'pk': self.player.pk}),
                                    {'action': 'deposit', 'amount': '30.00'}, content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(WalletTransaction.balance_for_user(self.player), Decimal('20.00'))
