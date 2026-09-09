import copy
import json
from datetime import datetime, timedelta, timezone as tz
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from gamelink.models import LinkedAccount

from .checks import billing_configuration
from .models import Payment, Receipt, Refund, Subscription, WebhookEvent
from .paypal import PayPal, ProviderError
from .services import TIER_PARENTS, capabilities_for, entitlement_for, has_membership, month_after


CONFIG = dict(
    BILLING_ENABLED=True, PAYPAL_ENVIRONMENT='sandbox', PAYPAL_CLIENT_ID='test-client',
    PAYPAL_CLIENT_SECRET='test-secret', PAYPAL_WEBHOOK_ID='WH-TEST', PAYPAL_PLAN_ID='P-MONTHLY',
    PAYPAL_GOLD_PLAN_ID='P-MONTHLY', PAYPAL_PREMIUM_PLAN_ID='', PAYPAL_VIP_PLAN_ID='',
    BILLING_RETURN_URL='https://example.test/tournaments/subscription',
)


@override_settings(**CONFIG)
class BillingLifecycleTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='member')
        self.client.force_login(self.user)
        self.provider_patch = patch('billing.services.PayPal')
        self.provider = self.provider_patch.start().return_value
        self.addCleanup(self.provider_patch.stop)
        self.webhook_patch = patch('billing.views.PayPal', return_value=self.provider)
        self.webhook_patch.start()
        self.addCleanup(self.webhook_patch.stop)
        self.provider.verify.return_value = True
        self.provider.plan.return_value = {
            'id': 'P-MONTHLY', 'status': 'ACTIVE', 'payment_preferences': {'auto_bill_outstanding': False},
            'billing_cycles': [{'tenure_type': 'REGULAR', 'total_cycles': 0,
                'frequency': {'interval_unit': 'MONTH', 'interval_count': 1},
                'pricing_scheme': {'fixed_price': {'value': '29.00', 'currency_code': 'ILS'}}}],
        }
        self.provider.create.return_value = ('I-SUB', 'https://www.sandbox.paypal.com/approve')
        self.now = timezone.now().replace(microsecond=0)

    def purchase(self):
        response = self.client.post(reverse('billing-checkout'), json.dumps({'tier': 'GOLD', 'amount': '0.01', 'plan_id': 'EVIL'}), content_type='application/json')
        self.assertEqual(response.status_code, 201, response.content)
        sub = Subscription.objects.get(pk=response.json()['id'])
        self.remote = {'id': sub.provider_id, 'plan_id': sub.plan_id, 'custom_id': str(sub.pk),
                       'start_time': (self.now - timedelta(days=90)).isoformat(),
                       'status': 'ACTIVE', 'billing_info': {'failed_payments_count': 0}}
        self.provider.subscription.side_effect = lambda _: copy.deepcopy(self.remote)
        return sub

    def event(self, kind, resource, identifier='EV-1', expected=200):
        response = self.client.post(reverse('billing-webhook'), json.dumps({
            'id': identifier, 'event_type': kind, 'resource': resource,
        }), content_type='application/json')
        self.assertEqual(response.status_code, expected, response.content)
        return response

    def sale(self, identifier='SALE-1', paid_at=None):
        return {'id': identifier, 'state': 'completed', 'billing_agreement_id': 'I-SUB',
                'amount': {'total': '29.00', 'currency': 'ILS'},
                'create_time': (paid_at or self.now).isoformat()}

    def test_full_purchase_renewal_failure_recovery_cancellation_and_expiry(self):
        sub = self.purchase()
        self.assertFalse(has_membership(self.user))
        self.event('BILLING.SUBSCRIPTION.ACTIVATED', {'id': 'I-SUB'})
        self.assertFalse(has_membership(self.user), 'Activation is not proof of payment')
        self.event('PAYMENT.SALE.COMPLETED', self.sale(), 'EV-PAID')
        self.assertTrue(has_membership(self.user))
        first_end = Payment.objects.get().period_end
        self.remote['billing_info']['failed_payments_count'] = 1
        self.event('BILLING.SUBSCRIPTION.PAYMENT.FAILED', {'id': 'I-SUB'}, 'EV-FAILED')
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'past_due')
        with patch('billing.services.timezone.now', return_value=first_end + timedelta(seconds=1)):
            self.assertFalse(has_membership(self.user))
        self.remote['billing_info']['failed_payments_count'] = 0
        renewal = first_end + timedelta(days=1)
        self.event('PAYMENT.SALE.COMPLETED', self.sale('SALE-2', renewal), 'EV-RENEW')
        with patch('billing.services.timezone.now', return_value=renewal + timedelta(seconds=1)):
            self.assertTrue(has_membership(self.user))
            self.client.force_login(self.user)  # The simulated month also expires Django sessions.
            response = self.client.post(reverse('billing-cancel', args=[sub.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(has_membership(self.user), 'Cancellation preserves the paid period')
            self.client.post(reverse('billing-cancel', args=[sub.pk]))
            self.provider.cancel.assert_called_once()
        self.event('BILLING.SUBSCRIPTION.ACTIVATED', {'id': 'I-SUB'}, 'EV-LATE')
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'cancelled')
        with patch('billing.services.timezone.now', return_value=Payment.objects.get(provider_id='SALE-2').period_end):
            self.assertFalse(has_membership(self.user))
        self.assertEqual(Payment.objects.count(), 2)
        self.assertEqual(Receipt.objects.count(), 2)

    def test_duplicate_checkout_ignores_client_price_and_returns_same_purchase(self):
        sub = self.purchase()
        second = self.client.post(reverse('billing-checkout'), json.dumps({'tier': 'GOLD'}), content_type='application/json')
        self.assertEqual(second.json()['id'], str(sub.pk))
        self.assertEqual(sub.amount, Decimal('29.00'))
        self.assertEqual(sub.plan_id, 'P-MONTHLY')
        self.provider.create.assert_called_once()

    def test_duplicate_event_and_distinct_events_for_same_sale_never_extend_access(self):
        self.purchase()
        first = self.event('PAYMENT.SALE.COMPLETED', self.sale())
        end = Payment.objects.get().period_end
        duplicate = self.event('PAYMENT.SALE.COMPLETED', self.sale())
        self.event('PAYMENT.SALE.COMPLETED', self.sale(), 'EV-DIFFERENT')
        self.assertEqual(first.json()['result'], 'processed')
        self.assertEqual(duplicate.json()['result'], 'duplicate')
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(Receipt.objects.count(), 1)
        self.assertEqual(Payment.objects.get().period_end, end)
        self.provider.create.assert_called_once()

    def test_timeout_keeps_checkout_id_for_retry(self):
        self.provider.create.side_effect = ProviderError('timeout')
        self.assertEqual(self.client.post(reverse('billing-checkout'), json.dumps({'tier': 'GOLD'}), content_type='application/json').status_code, 503)
        key = Subscription.objects.get().pk
        self.provider.create.side_effect = None
        self.purchase()
        self.assertEqual(Subscription.objects.get().pk, key)
        self.assertEqual([call.args[0].pk for call in self.provider.create.call_args_list], [key, key])

    def test_stale_uncertain_checkout_never_recreates_charge(self):
        self.provider.create.side_effect = ProviderError('timeout')
        self.client.post(reverse('billing-checkout'), json.dumps({'tier': 'GOLD'}), content_type='application/json')
        Subscription.objects.update(created_at=self.now - timedelta(hours=73))
        self.assertEqual(self.client.post(reverse('billing-checkout'), json.dumps({'tier': 'GOLD'}), content_type='application/json').status_code, 409)
        self.provider.create.assert_called_once()

    def test_checkout_cannot_create_another_active_subscription(self):
        self.purchase()
        self.event('PAYMENT.SALE.COMPLETED', self.sale())
        self.assertEqual(self.client.post(reverse('billing-checkout'), json.dumps({'tier': 'GOLD'}), content_type='application/json').status_code, 409)
        self.provider.create.assert_called_once()

    def test_bad_signature_cannot_grant_or_mark_event(self):
        self.purchase()
        self.provider.verify.return_value = False
        self.event('PAYMENT.SALE.COMPLETED', self.sale(), expected=400)
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(WebhookEvent.objects.exists())

    def test_price_currency_and_ownership_mismatch_rejected_atomically(self):
        self.purchase()
        for field, value in [('total', '0.01'), ('currency', 'USD'), ('total', 'NaN')]:
            sale = self.sale()
            sale['amount'][field] = value
            self.event('PAYMENT.SALE.COMPLETED', sale, expected=400)
        self.remote['custom_id'] = 'another-user'
        self.event('PAYMENT.SALE.COMPLETED', self.sale(), expected=400)
        self.assertFalse(WebhookEvent.objects.exists())
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(Receipt.objects.exists())

    def test_provider_failure_leaves_event_retryable(self):
        self.purchase()
        self.provider.subscription.side_effect = ProviderError('offline')
        self.event('PAYMENT.SALE.COMPLETED', self.sale(), expected=503)
        self.assertFalse(WebhookEvent.objects.exists())
        self.provider.subscription.side_effect = lambda _: self.remote
        self.event('PAYMENT.SALE.COMPLETED', self.sale())
        self.assertTrue(has_membership(self.user))

    def refund_resource(self, identifier='REF-1', amount='29.00'):
        return {'id': identifier, 'sale_id': 'SALE-1', 'state': 'completed',
                'amount': {'total': amount, 'currency': 'ILS'}, 'create_time': self.now.isoformat()}

    def test_full_refund_revokes_access_once_and_creates_credit_receipt(self):
        self.purchase()
        self.event('PAYMENT.SALE.COMPLETED', self.sale())
        self.event('PAYMENT.SALE.REFUNDED', self.refund_resource(), 'EV-REF')
        self.event('PAYMENT.SALE.REFUNDED', self.refund_resource(), 'EV-REF-2')
        self.event('PAYMENT.SALE.COMPLETED', self.sale(), 'EV-LATE-SALE')
        self.assertFalse(has_membership(self.user))
        self.assertEqual(Payment.objects.get().refunded_amount, Decimal('29.00'))
        self.assertEqual(Refund.objects.count(), 1)
        self.assertEqual(Receipt.objects.count(), 2)

    def test_partial_refunds_sum_once_and_full_total_revokes(self):
        self.purchase()
        self.event('PAYMENT.SALE.COMPLETED', self.sale())
        self.event('PAYMENT.SALE.REFUNDED', self.refund_resource(amount='10.00'), 'EV-R1')
        self.assertTrue(has_membership(self.user))
        self.event('PAYMENT.SALE.REFUNDED', self.refund_resource('REF-2', '19.00'), 'EV-R2')
        self.assertFalse(has_membership(self.user))

    def test_refund_of_previous_month_does_not_revoke_new_payment(self):
        self.purchase()
        self.event('PAYMENT.SALE.COMPLETED', self.sale(paid_at=self.now - timedelta(days=40)))
        self.event('PAYMENT.SALE.COMPLETED', self.sale('SALE-2'), 'EV-NEW')
        self.event('PAYMENT.SALE.REFUNDED', self.refund_resource(), 'EV-REF')
        self.assertTrue(has_membership(self.user))

    def test_refund_before_sale_is_retried(self):
        self.purchase()
        self.event('PAYMENT.SALE.REFUNDED', self.refund_resource(), 'EV-REF', expected=503)
        self.assertFalse(WebhookEvent.objects.exists())
        self.event('PAYMENT.SALE.COMPLETED', self.sale())
        self.event('PAYMENT.SALE.REFUNDED', self.refund_resource(), 'EV-REF')
        self.assertFalse(has_membership(self.user))

    def test_reversal_stays_revoked_after_late_completed_notification(self):
        self.purchase()
        self.event('PAYMENT.SALE.COMPLETED', self.sale())
        self.event('PAYMENT.SALE.REVERSED', self.sale(), 'EV-REVERSED')
        self.event('PAYMENT.SALE.COMPLETED', self.sale(), 'EV-LATE')
        self.assertFalse(has_membership(self.user))

    def test_staff_refund_is_idempotent_and_user_cannot_refund(self):
        self.purchase()
        self.event('PAYMENT.SALE.COMPLETED', self.sale())
        payment = Payment.objects.get()
        url = reverse('billing-refund', args=[payment.pk])
        self.assertEqual(self.client.post(url).status_code, 403)
        self.user.is_staff = True
        self.user.save()
        self.provider.refund.return_value = self.refund_resource()
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(self.client.post(url).status_code, 200)
        self.provider.refund.assert_called_once()
        self.assertFalse(has_membership(self.user))

    def test_pending_refund_does_not_revoke_until_confirmed(self):
        self.purchase()
        self.event('PAYMENT.SALE.COMPLETED', self.sale())
        self.user.is_staff = True
        self.user.save()
        pending = self.refund_resource()
        pending['state'] = 'pending'
        self.provider.refund.return_value = pending
        self.client.post(reverse('billing-refund', args=[Payment.objects.get().pk]))
        self.assertTrue(has_membership(self.user))
        self.event('PAYMENT.SALE.REFUNDED', self.refund_resource(), 'EV-REF')
        self.assertFalse(has_membership(self.user))

    def test_cancel_timeout_recovers_provider_confirmed_cancellation(self):
        sub = self.purchase()
        self.provider.cancel.side_effect = ProviderError('timeout')
        self.assertEqual(self.client.post(reverse('billing-cancel', args=[sub.pk])).status_code, 503)
        sub.refresh_from_db()
        self.assertTrue(sub.cancel_requested)
        self.remote['status'] = 'CANCELLED'
        self.assertEqual(self.client.post(reverse('billing-cancel', args=[sub.pk])).status_code, 200)
        self.provider.cancel.assert_called_once()

    def test_receipts_are_private_and_survive_disabled_checkout(self):
        sub = self.purchase()
        self.event('PAYMENT.SALE.COMPLETED', self.sale())
        url = reverse('billing-receipt', args=[Receipt.objects.get().pk])
        with override_settings(BILLING_ENABLED=False):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['environment'], 'sandbox')
        other = get_user_model().objects.create_user(username='other')
        self.client.force_login(other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(reverse('billing-cancel', args=[sub.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('billing-status')).json()['receipts'], [])

    def test_authentication_and_csrf(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('billing-status')).status_code, 401)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(reverse('billing-checkout')).status_code, 403)

    def test_database_prevents_multiple_open_subscriptions(self):
        self.purchase()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Subscription.objects.create(user=self.user, plan_id='P-OTHER', amount=10, currency='ILS')

    def test_unrelated_events_are_acknowledged(self):
        response = self.event('CATALOG.PRODUCT.CREATED', {'id': 'PROD-1'})
        self.assertEqual(response.json()['result'], 'ignored')

    def test_receipt_failure_rolls_back_payment_and_event(self):
        self.purchase()
        with patch('billing.services.receipt_for', side_effect=ProviderError('receipt unavailable')):
            self.event('PAYMENT.SALE.COMPLETED', self.sale(), expected=503)
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(WebhookEvent.objects.exists())
        self.event('PAYMENT.SALE.COMPLETED', self.sale())
        self.assertTrue(has_membership(self.user))

    def test_invalid_plan_is_not_purchased(self):
        self.provider.plan.return_value['billing_cycles'][0]['frequency']['interval_unit'] = 'DAY'
        self.assertEqual(self.client.post(reverse('billing-checkout'), json.dumps({'tier': 'GOLD'}), content_type='application/json').status_code, 503)
        self.provider.create.assert_not_called()


class EntitlementResolverTests(TestCase):
    def subscription(self, user, tier=None):
        return Subscription.objects.create(
            user=user, plan_id='P-TEST', amount=Decimal('29.00'), currency='ILS',
            status='cancelled', tier=tier,
        )

    def payment(self, subscription, identifier, *, paid_at=None, period_end=None, **kwargs):
        now = timezone.now()
        return Payment.objects.create(
            provider_id=identifier, subscription=subscription, amount=Decimal('29.00'), currency='ILS',
            paid_at=paid_at or now - timedelta(minutes=1), period_end=period_end or now + timedelta(days=1),
            **kwargs,
        )

    def test_free_without_paid_access_has_the_free_catalog(self):
        user = get_user_model().objects.create_user(username='free')
        entitlement = entitlement_for(user)
        self.assertFalse(entitlement['membership'])
        self.assertEqual(entitlement['tier'], 'FREE')
        self.assertIsNone(entitlement['valid_until'])
        self.assertEqual(entitlement['capabilities'], capabilities_for('FREE'))

    def test_mapped_paid_tiers_and_cumulative_catalog(self):
        expected = {
            'GOLD': {'rating': 'full', 'pr': 'basic', 'analysis': 'basic', 'courses': 'partial', 'live_lessons': False, 'ai': 'more', 'vip_benefits': False},
            'PREMIUM': {'rating': 'full', 'pr': 'advanced', 'analysis': 'full', 'courses': 'full', 'live_lessons': True, 'ai': 'unlimited', 'vip_benefits': False},
            'VIP': {'rating': 'full', 'pr': 'full', 'analysis': 'full', 'courses': 'full', 'live_lessons': True, 'ai': 'unlimited', 'vip_benefits': True},
        }
        self.assertEqual(TIER_PARENTS, {'FREE': None, 'GOLD': 'FREE', 'PREMIUM': 'GOLD', 'VIP': 'PREMIUM'})
        for tier, capabilities in expected.items():
            with self.subTest(tier=tier):
                user = get_user_model().objects.create_user(username=tier.lower())
                self.payment(self.subscription(user, tier), f'SALE-{tier}')
                entitlement = entitlement_for(user)
                self.assertTrue(entitlement['membership'])
                self.assertEqual(entitlement['tier'], tier)
                self.assertEqual({key: entitlement['capabilities'][key] for key in capabilities}, capabilities)
                self.assertTrue(entitlement['capabilities']['online_play'])
                self.assertTrue(entitlement['capabilities']['tournaments'])
                self.assertTrue(entitlement['capabilities']['weekly_cup'])
                self.assertTrue(entitlement['capabilities']['monthly_cup'])
                self.assertTrue(entitlement['capabilities']['grand_championship'])

    def test_cancelled_subscription_keeps_tier_until_paid_period_ends(self):
        user = get_user_model().objects.create_user(username='cancelled-tier')
        self.payment(self.subscription(user, 'GOLD'), 'SALE-CANCELLED')
        entitlement = entitlement_for(user)
        self.assertTrue(entitlement['membership'])
        self.assertEqual(entitlement['tier'], 'GOLD')

    def test_expiry_full_refund_and_reversal_revoke_but_partial_refund_does_not(self):
        user = get_user_model().objects.create_user(username='revoked-tier')
        subscription = self.subscription(user, 'VIP')
        expired = self.payment(subscription, 'SALE-EXPIRED', period_end=timezone.now() - timedelta(seconds=1))
        full_refund = self.payment(subscription, 'SALE-REFUNDED', refunded_amount=Decimal('29.00'))
        reversed_payment = self.payment(subscription, 'SALE-REVERSED', reversed=True)
        self.assertFalse(entitlement_for(user)['membership'])
        self.assertEqual(entitlement_for(user)['tier'], 'FREE')
        partial = self.payment(subscription, 'SALE-PARTIAL', refunded_amount=Decimal('1.00'))
        entitlement = entitlement_for(user)
        self.assertTrue(entitlement['membership'])
        self.assertEqual(entitlement['tier'], 'VIP')
        self.assertEqual(partial.refunded_amount, Decimal('1.00'))

    def test_effective_tier_comes_from_the_selected_payment_with_a_deterministic_tie(self):
        user = get_user_model().objects.create_user(username='overlap-tier')
        now = timezone.now().replace(microsecond=0)
        older_subscription = self.subscription(user, 'GOLD')
        newer_subscription = self.subscription(user, 'VIP')
        older_subscription.created_at = now - timedelta(seconds=1)
        older_subscription.save(update_fields=['created_at'])
        newer_subscription.created_at = now
        newer_subscription.save(update_fields=['created_at'])
        linked_identity = LinkedAccount.external_id_for(user)
        self.payment(older_subscription, 'SALE-LONGER', paid_at=now - timedelta(days=1), period_end=now + timedelta(days=2))
        self.payment(newer_subscription, 'SALE-SHORTER', paid_at=now, period_end=now + timedelta(days=1))
        self.assertEqual(entitlement_for(user)['tier'], 'GOLD')
        self.client.force_login(user)
        response = self.client.get(reverse('billing-status'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['subscription']['tier'], 'VIP')
        self.assertEqual(response.json()['entitlements']['tier'], 'GOLD')
        self.assertEqual(response.json()['entitlements']['valid_until'], (now + timedelta(days=2)).isoformat())
        self.assertEqual(response.json()['entitlements']['capabilities']['pr'], 'basic')
        first = self.payment(older_subscription, 'SALE-TIE-1', paid_at=now, period_end=now + timedelta(days=3))
        second = self.payment(newer_subscription, 'SALE-TIE-2', paid_at=now, period_end=now + timedelta(days=3))
        entitlement = entitlement_for(user)
        self.assertGreater(second.pk, first.pk)
        self.assertEqual(entitlement['tier'], 'VIP')
        self.assertEqual(entitlement['valid_until'], second.period_end)
        self.assertEqual(get_user_model().objects.filter(pk=user.pk).count(), 1)
        self.assertEqual(LinkedAccount.external_id_for(user), linked_identity)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_unmapped_legacy_payment_keeps_membership_but_has_free_effective_tier(self):
        user = get_user_model().objects.create_user(username='legacy-tier')
        subscription = self.subscription(user)
        self.payment(subscription, 'SALE-LEGACY')
        self.client.force_login(user)
        response = self.client.get(reverse('billing-status'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['entitlements']['membership'])
        self.assertEqual(response.json()['entitlements']['tier'], 'FREE')
        self.assertEqual(response.json()['subscription']['tier'], None)
        self.assertFalse(user.is_staff)


@override_settings(**CONFIG)
class PayPalAdapterTests(TestCase):
    def test_signature_verification_requires_all_headers_and_success(self):
        provider = PayPal()
        headers = {name: 'test' for name in ('PAYPAL-AUTH-ALGO', 'PAYPAL-CERT-URL', 'PAYPAL-TRANSMISSION-ID', 'PAYPAL-TRANSMISSION-SIG', 'PAYPAL-TRANSMISSION-TIME')}
        with patch.object(provider, 'request', return_value={'verification_status': 'FAILURE'}) as request:
            self.assertFalse(provider.verify({}, {}))
            request.assert_not_called()
            self.assertFalse(provider.verify(headers, {'id': 'EV-1'}))
            self.assertEqual(request.call_args.args[2]['webhook_id'], 'WH-TEST')
            request.return_value = {'verification_status': 'SUCCESS'}
            self.assertTrue(provider.verify(headers, {'id': 'EV-1'}))

    def test_oauth_and_idempotency_header_sent_to_sandbox(self):
        provider = PayPal()
        with patch.object(provider, '_send', side_effect=[{'access_token': 'token'}, {'id': 'I-SUB'}]) as send:
            provider.request('POST', '/v1/billing/subscriptions', {'plan_id': 'P-MONTHLY'}, 'stable-id')
            self.assertEqual(send.call_args.args[3]['PayPal-Request-Id'], 'stable-id')
            self.assertEqual(send.call_args.args[3]['Authorization'], 'Bearer token')
            self.assertEqual(provider.base, 'https://api-m.sandbox.paypal.com')

    def test_live_mode_is_refused_even_if_checks_are_skipped(self):
        with override_settings(PAYPAL_ENVIRONMENT='live'):
            with self.assertRaises(ProviderError):
                PayPal()
            self.assertTrue(any(error.id == 'billing.E001' for error in billing_configuration()))

    def test_month_end_and_leap_year(self):
        self.assertEqual(month_after(datetime(2028, 1, 31, tzinfo=tz.utc)), datetime(2028, 2, 29, tzinfo=tz.utc))
        self.assertEqual(month_after(datetime(2026, 12, 31, tzinfo=tz.utc)), datetime(2027, 1, 31, tzinfo=tz.utc))
