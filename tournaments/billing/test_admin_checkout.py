import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse

from .models import CheckoutRequest, CheckoutEvent, StoreProduct
from .test_tranzila_flow import CONFIG
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

    @override_settings(**CONFIG)
    def test_player_orders_and_verified_purchase_details_are_visible_to_staff(self):
        product = StoreProduct.objects.get(tier='GOLD')
        now = timezone.now()
        row = CheckoutRequest.objects.create(user=self.player, actor=self.player, idempotency_key=uuid.uuid4(),
            catalog_product=product, product_snapshot={'name': 'Quarterly Gold', 'period_months': 3},
            product='subscription', tier='GOLD', amount='80.00', currency='ILS', environment='live',
            status='paid', paid_at=now, valid_until=now, provider_terminal='merchanttest', provider_transaction_index='1234')
        CheckoutEvent.objects.create(checkout=row, kind='payment_verified')
        response = self.client.get(self.url)
        data = response.json()
        self.assertEqual(data['status_counts']['paid'], 1)
        self.assertEqual(data['status_counts']['pending'], 0)
        item = data['items'][0]
        self.assertEqual(item['actor'], 'player')
        self.assertEqual(item['name'], 'Quarterly Gold')
        self.assertEqual(item['period_months'], 3)
        self.assertEqual(item['paid_at'], now.isoformat())
        self.assertEqual(item['valid_until'], now.isoformat())
        self.assertFalse(item['can_prepare'])
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        for query in (str(row.pk), 'merchanttest/1234', '1234'):
            self.assertEqual(self.client.get(self.url, {'q': query}).json()['count'], 1)
        self.assertEqual(self.client.get(self.url, {'status': 'pending'}).json()['status_counts']['paid'], 0)

    @override_settings(**CONFIG)
    def test_pending_payments_requiring_reconciliation_never_offer_another_payment(self):
        product = StoreProduct.objects.get(tier='GOLD')
        row = CheckoutRequest.objects.create(user=self.player, actor=self.staff, idempotency_key=uuid.uuid4(),
            catalog_product=product, product='subscription', tier='GOLD', amount='80.00', currency='ILS', status='pending',
            checkout_session={'fields': {'thtk': 'private-session-token'}})
        response = self.client.get(self.url)
        item = response.json()['items'][0]
        self.assertEqual(item['id'], str(row.pk))
        self.assertTrue(item['recovery_required'])
        self.assertFalse(item['can_prepare'])
        self.assertNotContains(response, 'private-session-token')

    @override_settings(**CONFIG)
    def test_readiness_distinguishes_purchase_pause_and_last_verified_payment(self):
        url = reverse('api-admin-tranzila-readiness')
        self.assertIsNone(self.client.get(url).json()['last_verified_at'])
        now = timezone.now()
        CheckoutRequest.objects.create(user=self.player, actor=self.staff, idempotency_key=uuid.uuid4(),
            product='coins', coin_quantity=500, amount='10', currency='ILS', status='paid', paid_at=now,
            provider_terminal='merchanttest', environment='live')
        with override_settings(TRANZILA_PURCHASES_ENABLED=False):
            state = self.client.get(url).json()
        self.assertTrue(state['ready'])
        self.assertFalse(state['purchases_enabled'])
        self.assertEqual(state['last_verified_at'], now.isoformat())
        with override_settings(TRANZILA_ENVIRONMENT='test'):
            self.assertIsNone(self.client.get(url).json()['last_verified_at'])
        self.client.force_login(self.player)
        self.assertEqual(self.client.get(url).status_code, 403)
