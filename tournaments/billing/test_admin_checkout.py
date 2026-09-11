import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import CheckoutRequest, CheckoutEvent
from tournaments.models import WalletTransaction


class AdminCheckoutTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user('admin', is_staff=True)
        self.player = get_user_model().objects.create_user('player')
        self.client.force_login(self.staff)
        self.url = reverse('api-admin-checkouts')
        self.payload = dict(user_id=self.player.pk, product='coins', coin_quantity=100,
                            amount='9.90', currency='ILS', idempotency_key=str(uuid.uuid4()))

    def post(self, **changes):
        return self.client.post(self.url, {**self.payload, **changes}, content_type='application/json')

    def test_draft_audit_and_retry_do_not_credit_coins(self):
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(CheckoutRequest.objects.count(), 1)
        self.assertEqual(CheckoutEvent.objects.count(), 1)
        self.assertEqual(WalletTransaction.balance_for_user(self.player), Decimal('0'))
        data = self.client.get(self.url).json()
        self.assertEqual(data['items'][0]['status'], 'draft')
        self.assertEqual(data['items'][0]['actor'], 'admin')
        self.assertEqual(data['items'][0]['coin_quantity'], 100)
        self.assertFalse(data['provider']['checkout_enabled'])
        self.assertEqual(data['totals'], [])

    def test_reused_key_cannot_change_purchase(self):
        self.post()
        self.assertEqual(self.post(amount='20.00').status_code, 409)

    def test_invalid_units_and_products_rejected(self):
        for change in [dict(user_id=True), dict(user_id=1.9), dict(amount='NaN'), dict(amount='-1'), dict(amount='1.001'),
                       dict(coin_quantity='1.5'), dict(coin_quantity=0), dict(currency='COINS'),
                       dict(product='subscription', tier='FREE', coin_quantity=0),
                       dict(product='subscription', tier='VIP', coin_quantity=100)]:
            with self.subTest(change=change):
                self.assertEqual(self.post(**change).status_code, 400)

    def test_subscription_has_no_coin_quantity(self):
        self.assertEqual(self.post(product='subscription', tier='GOLD', coin_quantity=0).status_code, 201)
        self.assertEqual(self.client.get(self.url, {'product': 'coins'}).json()['count'], 0)
        self.assertEqual(self.client.get(self.url, {'q': 'player'}).json()['count'], 1)

    def test_client_cannot_mark_paid_or_live(self):
        self.post(status='paid', environment='live', provider_reference='fake')
        checkout = CheckoutRequest.objects.get()
        self.assertEqual(checkout.status, 'draft')
        self.assertEqual(checkout.environment, 'sandbox')
        self.assertIsNone(checkout.provider_reference)

    def test_currency_and_environment_are_never_summed_together(self):
        for currency, environment in [('ILS', 'live'), ('USD', 'live'), ('ILS', 'sandbox')]:
            CheckoutRequest.objects.create(user=self.player, actor=self.staff, idempotency_key=uuid.uuid4(),
                                           product='coins', amount='10', coin_quantity=5, currency=currency,
                                           environment=environment, status='paid')
        self.assertEqual(len(self.client.get(self.url).json()['totals']), 3)

    def test_access_and_invalid_filters(self):
        self.assertEqual(self.client.get(self.url, {'offset': -1}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {'status': 'unknown'}).status_code, 400)
        self.client.force_login(self.player)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.post().status_code, 403)
