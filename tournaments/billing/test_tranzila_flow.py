import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tournaments.models import WalletTransaction
from .models import CheckoutRequest, CheckoutEvent, StoreProduct
from .services import entitlement_for, has_membership
from .tranzila import ProviderError
from .tranzila_flow import prepare, verify_payment


CONFIG = dict(TRANZILA_ENABLED=True, TRANZILA_PURCHASES_ENABLED=True, TRANZILA_ENVIRONMENT='live', TRANZILA_TERMINAL='merchanttest',
              TRANZILA_APP_KEY='private-test-key', TRANZILA_APP_SECRET='private-test-secret',
              TRANZILA_RETURN_URL='https://example.test/return', TRANZILA_NOTIFY_URL='https://example.test/notify',
              TRANZILA_REPORT_MAPPING_CONFIRMED=True, TRANZILA_APPROVED_TRANSTATUS='fixture-active')


@override_settings(**CONFIG)
class TranzilaFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('buyer')
        self.staff = get_user_model().objects.create_user('operator', is_staff=True)
        from django.contrib.auth.models import Permission
        self.staff.user_permissions.add(Permission.objects.get(content_type__app_label='billing', codename='manage_payments'))
        self.product = StoreProduct.objects.create(name='Coins', kind='coins', tier='', price='10.00',
                                                  coin_quantity=500, period_months=0, active=True)
        self.row = self.order()
        self.patcher = patch('billing.tranzila_flow.Tranzila')
        self.provider = self.patcher.start().return_value
        self.addCleanup(self.patcher.stop)
        self.provider.terminal = 'merchanttest'
        self.provider.handshake.return_value = {'method': 'POST', 'action': 'https://directng.tranzila.com/merchanttest/iframenew.php', 'fields': {'thtk': 'secret-session'}}
        self.provider.lookup.return_value = self.record()

    def order(self, **changes):
        values = dict(user=self.user, actor=self.staff, catalog_product=self.product,
                      idempotency_key=uuid.uuid4(), product='coins', tier='', coin_quantity=500,
                      amount='10.00', currency='ILS', product_snapshot={'period_months': 1})
        return CheckoutRequest.objects.create(**{**values, **changes})

    def record(self, **changes):
        return {**dict(transaction_index=100, amount='10.00', currency='ILS', terminal='merchanttest',
                       checkout_id=str(self.row.pk), duplicate_key=str(self.row.pk),
                       processor_response_code='000', tranmode='A', txn_type='DEBIT', transtatus='fixture-active'), **changes}

    def test_session_is_reused_and_expired_session_does_not_start_another_payment(self):
        prepare(self.row.pk, self.user)
        prepare(self.row.pk, self.user)
        self.provider.handshake.assert_called_once()
        CheckoutRequest.objects.filter(pk=self.row.pk).update(session_expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(ProviderError):
            prepare(self.row.pk, self.user)
        self.provider.handshake.assert_called_once()

    def test_coin_fulfillment_is_atomic_and_exactly_once(self):
        prepare(self.row.pk, self.user)
        verify_payment(self.row.pk, 100)
        verify_payment(self.row.pk, 100)
        self.assertEqual(WalletTransaction.balance_for_user(self.user), Decimal('500'))
        self.assertEqual(WalletTransaction.objects.count(), 1)
        self.provider.lookup.assert_called_once_with(100)
        self.assertEqual(CheckoutEvent.objects.filter(kind='payment_verified').count(), 1)
        self.row.refresh_from_db()
        self.assertEqual(self.row.checkout_session, {})

    def test_failure_after_wallet_credit_rolls_back_the_entire_fulfillment(self):
        prepare(self.row.pk, self.user)
        with patch('billing.tranzila_flow.CheckoutEvent.objects.create', side_effect=IntegrityError('audit unavailable')):
            with self.assertRaises(IntegrityError):
                verify_payment(self.row.pk, 100)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'pending')
        self.assertIsNone(self.row.provider_reference)
        self.assertFalse(WalletTransaction.objects.exists())
        verify_payment(self.row.pk, 100)
        self.assertEqual(WalletTransaction.balance_for_user(self.user), 500)

    def test_same_provider_reference_cannot_pay_two_orders(self):
        prepare(self.row.pk, self.user)
        verify_payment(self.row.pk, 100)
        other = self.order()
        prepare(other.pk, self.user)
        self.provider.lookup.return_value = self.record(checkout_id=str(other.pk), duplicate_key=str(other.pk))
        with self.assertRaises(IntegrityError):
            verify_payment(other.pk, 100)
        self.assertEqual(WalletTransaction.objects.count(), 1)
        other.refresh_from_db()
        self.assertEqual(other.status, 'pending')

    def test_duplicate_notifications_credit_once_and_invalid_json_shape_is_rejected(self):
        prepare(self.row.pk, self.user)
        url = reverse('tranzila-notify')
        for _ in range(2):
            response = self.client.post(url, {'checkout_id': str(self.row.pk), 'index': '100'})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(WalletTransaction.objects.count(), 1)
        self.assertEqual(self.client.post(url, ['not', 'an', 'object'], content_type='application/json').status_code, 400)

    def test_wrong_provider_values_never_grant(self):
        prepare(self.row.pk, self.user)
        for changes in [dict(amount='0.01'), dict(currency='USD'), dict(checkout_id=str(uuid.uuid4())),
                        dict(terminal='other'), dict(duplicate_key='other'), dict(txn_type='CREDIT'),
                        dict(processor_response_code='001'), dict(tranmode='F'), dict(transtatus='cancelled'),
                        dict(transaction_index=101)]:
            with self.subTest(changes=changes):
                self.provider.lookup.return_value = self.record(**changes)
                with self.assertRaises(ValueError):
                    verify_payment(self.row.pk, 100)
                self.assertFalse(WalletTransaction.objects.exists())
                self.row.refresh_from_db()
                self.assertEqual(self.row.status, 'pending')

    @override_settings(TRANZILA_ENVIRONMENT='test')
    def test_test_payments_do_not_credit_live_wallet_or_membership(self):
        prepare(self.row.pk, self.user)
        verify_payment(self.row.pk, 100)
        self.assertFalse(WalletTransaction.objects.exists())
        self.assertFalse(has_membership(self.user))
        self.row.refresh_from_db()
        self.assertEqual(self.row.environment, 'sandbox')
        self.assertEqual(self.row.status, 'paid')

    def test_term_membership_uses_saved_period_and_is_resolved_by_existing_entitlement_api(self):
        self.row.product = 'subscription'; self.row.tier = 'GOLD'; self.row.coin_quantity = 0
        self.row.product_snapshot = {'period_months': 3}; self.row.save()
        prepare(self.row.pk, self.user)
        verify_payment(self.row.pk, 100)
        self.assertTrue(has_membership(self.user))
        result = entitlement_for(self.user)
        self.assertEqual(result['tier'], 'GOLD')
        self.assertGreater(result['valid_until'], timezone.now() + timedelta(days=85))
        self.assertFalse(WalletTransaction.objects.exists())

    def test_untrusted_notify_cannot_assert_success_without_lookup(self):
        prepare(self.row.pk, self.user)
        self.provider.lookup.side_effect = ProviderError('Unavailable')
        response = self.client.post(reverse('tranzila-notify'), dict(checkout_id=str(self.row.pk), index='100', Response='000', sum='10'))
        self.assertEqual(response.status_code, 503)
        self.assertFalse(WalletTransaction.objects.exists())
        self.row.refresh_from_db(); self.assertEqual(self.row.status, 'pending')

    def test_permissions_and_csrf_protect_session_and_reconciliation(self):
        stranger = get_user_model().objects.create_user('stranger')
        self.client.force_login(stranger)
        response = self.client.post(reverse('tranzila-session', args=[self.row.pk]))
        self.assertEqual(response.status_code, 404)
        response = self.client.post(reverse('api-admin-tranzila-reconcile', args=[self.row.pk]), {'transaction_index': 100}, content_type='application/json')
        self.assertEqual(response.status_code, 403)
        from django.test import Client
        csrf = Client(enforce_csrf_checks=True); csrf.force_login(self.user)
        self.assertEqual(csrf.post(reverse('tranzila-session', args=[self.row.pk])).status_code, 403)
        self.provider.handshake.assert_not_called()

    @override_settings(TRANZILA_ENABLED=False)
    def test_disabled_never_calls_provider(self):
        with self.assertRaises(ProviderError):
            prepare(self.row.pk, self.user)
        self.provider.handshake.assert_not_called()

    def test_readiness_never_leaks_credentials(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('api-admin-tranzila-readiness'))
        self.assertTrue(response.json()['ready'])
        self.assertNotContains(response, 'private-test')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
