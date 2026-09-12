import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tournaments.models import WalletTransaction
from .models import CheckoutEvent, CheckoutRequest, StoreProduct
from .test_tranzila_flow import CONFIG
from .tranzila_flow import prepare


@override_settings(**CONFIG)
class PlayerCheckoutTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('player')
        self.other = get_user_model().objects.create_user('other')
        self.client.force_login(self.user)
        self.product = StoreProduct.objects.create(name='500 coins', kind='coins', price='12.50',
            currency='ILS', coin_quantity=500, period_months=0, active=True)
        self.key = str(uuid.uuid4())
        self.url = reverse('tranzila-orders')

    def post(self, **changes):
        return self.client.post(self.url, {'product_id': self.product.pk,
            'idempotency_key': self.key, **changes}, content_type='application/json')

    def test_catalog_only_lists_active_paid_products_and_no_credentials(self):
        self.product.active = False
        self.product.save()
        response = self.client.get(reverse('billing-catalog'))
        self.assertEqual(response.json()['items'], [])
        self.assertTrue(response.json()['enabled'])
        self.assertNotContains(response, 'private-test')
        self.assertEqual(response['Cache-Control'], 'private, no-store')

    def test_server_snapshot_and_retry_survive_catalog_change_and_disabled_purchases(self):
        first = self.post()
        self.assertEqual(first.status_code, 201, first.content)
        StoreProduct.objects.filter(pk=self.product.pk).update(price='99.00', coin_quantity=5, active=False)
        with override_settings(TRANZILA_ENABLED=False):
            retry = self.post()
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json()['id'], first.json()['id'])
        self.assertEqual(retry.json()['amount'], '12.50')
        self.assertEqual(retry.json()['coin_quantity'], 500)
        row = CheckoutRequest.objects.get()
        self.assertEqual(row.user_id, self.user.pk)
        self.assertEqual(row.actor_id, self.user.pk)
        self.assertEqual(row.product_snapshot['price'], '12.50')
        self.assertEqual(CheckoutEvent.objects.count(), 1)
        self.assertFalse(WalletTransaction.objects.exists())

    def test_cannot_supply_price_user_status_or_entitlements(self):
        for changes in [{'amount': '0.01'}, {'user_id': self.other.pk}, {'status': 'paid'},
                        {'coin_quantity': 9999}, {'environment': 'live'}, {'tier': 'VIP'},
                        {'product_id': True}, {'idempotency_key': 'bad'}]:
            with self.subTest(changes=changes):
                self.assertEqual(self.post(**changes).status_code, 400)
        self.assertFalse(CheckoutRequest.objects.exists())

    def test_conflicting_retry_key_never_exposes_another_players_order(self):
        self.post()
        self.assertEqual(self.post(product_id=9999).status_code, 409)
        self.client.force_login(self.other)
        response = self.post()
        self.assertEqual(response.status_code, 409)
        self.assertNotIn('id', response.json())
        self.assertEqual(self.client.get(self.url).json()['items'], [])

    def test_second_tab_cannot_start_another_unresolved_purchase(self):
        first = self.post().json()
        response = self.post(idempotency_key=str(uuid.uuid4()))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['order_id'], first['id'])
        self.assertEqual(CheckoutRequest.objects.count(), 1)

    def test_owner_can_cancel_only_unprepared_drafts(self):
        row = self.post().json()
        url = reverse('tranzila-cancel-draft', args=[row['id']])
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(url).json()['status'], 'cancelled')
        self.assertEqual(self.client.post(url).json()['status'], 'cancelled')
        self.assertEqual(CheckoutEvent.objects.filter(kind='draft_cancelled').count(), 1)
        self.assertEqual(self.post(idempotency_key=str(uuid.uuid4())).status_code, 201)

    def test_pending_expired_order_is_recoverable_and_cannot_be_cancelled_or_replaced(self):
        identifier = self.post().json()['id']
        with patch('billing.tranzila_flow.Tranzila') as adapter:
            adapter.return_value.terminal = CONFIG['TRANZILA_TERMINAL']
            adapter.return_value.handshake.return_value = {'fields': {'thtk': 'do-not-expose'}}
            prepare(identifier, self.user)
        CheckoutRequest.objects.filter(pk=identifier).update(session_expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.post(reverse('tranzila-cancel-draft', args=[identifier])).status_code, 409)
        self.assertEqual(self.post(idempotency_key=str(uuid.uuid4())).status_code, 409)
        with override_settings(TRANZILA_ENABLED=False):
            response = self.client.get(self.url)
            status = self.client.get(reverse('tranzila-order-status', args=[identifier]))
        self.assertTrue(response.json()['items'][0]['recovery_required'])
        self.assertFalse(response.json()['items'][0]['can_pay'])
        self.assertFalse(response.json()['items'][0]['can_cancel'])
        self.assertNotContains(response, 'do-not-expose')
        self.assertEqual(status.json()['id'], identifier)
        self.assertEqual(status['Cache-Control'], 'private, no-store')

    def test_order_status_is_owner_only_even_for_staff(self):
        identifier = self.post().json()['id']
        self.other.is_staff = True
        self.other.save()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('tranzila-order-status', args=[identifier])).status_code, 404)

    def test_authentication_and_csrf(self):
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(csrf.post(self.url, {}, content_type='application/json').status_code, 403)
        identifier = self.post().json()['id']
        self.assertEqual(csrf.post(reverse('tranzila-cancel-draft', args=[identifier])).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.assertEqual(self.client.get(reverse('billing-catalog')).status_code, 401)
        self.assertEqual(self.post().status_code, 401)

    @override_settings(TRANZILA_ENABLED=False)
    def test_disabled_prevents_new_orders_but_catalog_still_loads(self):
        self.assertEqual(self.post().status_code, 503)
        data = self.client.get(reverse('billing-catalog')).json()
        self.assertFalse(data['enabled'])
        self.assertEqual(data['items'][0]['price'], '12.50')
        self.assertFalse(CheckoutRequest.objects.exists())

    def test_fixed_membership_period_comes_from_catalog(self):
        plan = StoreProduct.objects.get(kind='subscription', tier='GOLD')
        plan.price = '80.00'
        plan.period_months = 3
        plan.active = True
        plan.save()
        data = self.post(product_id=plan.pk).json()
        self.assertEqual(data['tier'], 'GOLD')
        self.assertEqual(data['period_months'], 3)
        self.assertEqual(data['coin_quantity'], 0)

    def test_pausing_player_purchases_does_not_disable_inflight_verification(self):
        from .tranzila_flow import verify_payment
        identifier = self.post().json()['id']
        with patch('billing.tranzila_flow.Tranzila') as adapter:
            provider = adapter.return_value
            provider.terminal = CONFIG['TRANZILA_TERMINAL']
            provider.handshake.return_value = {'fields': {'thtk': 'session'}}
            prepare(identifier, self.user)
            provider.lookup.return_value = dict(transaction_index=100, amount='12.50', currency='ILS',
                terminal=CONFIG['TRANZILA_TERMINAL'], checkout_id=identifier, duplicate_key=identifier,
                processor_response_code='000', tranmode='A', txn_type='DEBIT', transtatus=CONFIG['TRANZILA_APPROVED_TRANSTATUS'])
            with override_settings(TRANZILA_PURCHASES_ENABLED=False):
                self.assertFalse(self.client.get(reverse('billing-catalog')).json()['enabled'])
                self.assertEqual(self.client.post(reverse('tranzila-session', args=[identifier])).status_code, 503)
                verify_payment(identifier, 100)
                self.assertEqual(self.post(idempotency_key=str(uuid.uuid4())).status_code, 503)
        self.assertEqual(WalletTransaction.balance_for_user(self.user), 500)
