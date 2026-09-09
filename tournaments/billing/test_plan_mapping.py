"""Plan selection through HTTP, with a simulated provider and isolated users."""
import copy
import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from . import tests as lifecycle
from .checks import billing_configuration
from .models import Payment, Receipt, Subscription, WebhookEvent
from .paypal import PayPal, ProviderError


@override_settings(**dict(lifecycle.CONFIG, PAYPAL_GOLD_PLAN_ID='P-GOLD',
                         PAYPAL_PREMIUM_PLAN_ID='P-PREMIUM', PAYPAL_VIP_PLAN_ID='P-VIP',
                         PAYPAL_PLAN_ID='P-GOLD'))
class PlanMappingTests(TestCase):
    event = lifecycle.BillingLifecycleTests.event

    def setUp(self):
        lifecycle.BillingLifecycleTests.setUp(self)
        base = self.provider.plan.return_value
        self.plans = {}
        for tier, price in [('GOLD', '49.00'), ('PREMIUM', '99.00'), ('VIP', '199.00')]:
            plan = copy.deepcopy(base)
            plan['id'] = f'P-{tier}'
            plan['billing_cycles'][0]['pricing_scheme']['fixed_price']['value'] = price
            self.plans[plan['id']] = plan
        self.provider.plan.side_effect = lambda identifier: copy.deepcopy(self.plans[identifier])
        self.provider.create.side_effect = lambda sub: (
            f'I-{sub.pk}', 'https://www.sandbox.paypal.com/approve',
        )

    def checkout(self, tier='GOLD', **extra):
        return self.client.post(reverse('billing-checkout'),
                                json.dumps(dict(tier=tier, **extra)), content_type='application/json')

    def entitlement(self):
        return self.client.get(reverse('billing-status')).json()['entitlements']

    def prepare_payment(self, sub):
        self.remote = {'id': sub.provider_id, 'plan_id': sub.plan_id, 'custom_id': str(sub.pk),
                       'start_time': self.now.isoformat(), 'status': 'ACTIVE',
                       'billing_info': {'failed_payments_count': 0}}
        self.provider.subscription.side_effect = lambda _: copy.deepcopy(self.remote)
        return {'id': f'SALE-{sub.pk}', 'state': 'completed', 'billing_agreement_id': sub.provider_id,
                'amount': {'total': str(sub.amount), 'currency': sub.currency},
                'create_time': self.now.isoformat()}

    def test_all_tiers_quote_and_activate_only_after_verified_payment(self):
        for tier, amount in [('GOLD', '49.00'), ('PREMIUM', '99.00'), ('VIP', '199.00')]:
            with self.subTest(tier=tier):
                user = get_user_model().objects.create_user(username=tier)
                self.client.force_login(user)
                quote = self.client.get(reverse('billing-plan'), {'tier': tier})
                self.assertEqual(quote.status_code, 200)
                response = self.checkout(tier, amount='0.01', currency='USD', plan_id='P-EVIL',
                                         membership=True, capabilities={'vip_benefits': True})
                self.assertEqual(response.status_code, 201, response.content)
                sub = Subscription.objects.get(pk=response.json()['id'])
                self.assertEqual((sub.plan_id, sub.tier, str(sub.amount), sub.currency),
                                 (f'P-{tier}', tier, amount, 'ILS'))
                self.assertEqual(quote.json(), dict(tier=tier, amount=amount, currency='ILS', interval='month'))
                sale = self.prepare_payment(sub)
                self.assertEqual(self.entitlement()['tier'], 'FREE')
                self.event('BILLING.SUBSCRIPTION.ACTIVATED', {'id': sub.provider_id}, f'ACT-{tier}')
                self.assertFalse(self.entitlement()['membership'])
                self.assertEqual(self.entitlement()['tier'], 'FREE')
                self.event('PAYMENT.SALE.COMPLETED', sale, f'PAID-{tier}')
                self.assertEqual(self.entitlement()['tier'], tier)
                self.assertTrue(self.entitlement()['membership'])
                user.refresh_from_db()
                self.assertFalse(user.is_staff or user.is_superuser)
        self.assertEqual(Payment.objects.count(), 3)
        self.assertEqual(Receipt.objects.count(), 3)

    def test_empty_legacy_request_uses_explicit_default_and_retries_same_purchase(self):
        quote = self.client.get(reverse('billing-plan'))
        self.assertEqual(quote.json()['tier'], 'GOLD')
        response = self.client.generic('POST', reverse('billing-checkout'), data=b'')
        self.assertEqual(response.status_code, 201)
        sub = Subscription.objects.get()
        self.assertEqual((sub.tier, str(sub.amount)), ('GOLD', quote.json()['amount']))
        retry = self.client.generic('POST', reverse('billing-checkout'), data=b'')
        self.assertEqual(retry.json()['id'], str(sub.pk))
        self.provider.create.assert_called_once()

    def test_absent_or_unmapped_default_never_guesses_a_tier(self):
        for default in ('', 'P-LEGACY'):
            with self.subTest(default=default), override_settings(PAYPAL_PLAN_ID=default):
                self.assertEqual(self.client.get(reverse('billing-plan')).status_code, 409)
                self.assertEqual(self.client.generic('POST', reverse('billing-checkout'), data=b'').status_code, 409)
        self.provider.create.assert_not_called()
        self.assertFalse(Subscription.objects.exists())

    @override_settings(PAYPAL_PLAN_ID='')
    def test_explicit_selection_needs_no_legacy_default(self):
        self.assertEqual(billing_configuration(), [])
        self.assertEqual(self.client.get(reverse('billing-plan'), {'tier': 'VIP'}).json()['tier'], 'VIP')
        self.assertEqual(self.checkout('VIP').status_code, 201)

    def test_invalid_body_or_tier_cannot_fall_back_to_default(self):
        bodies = ['{', '[]', 'null', '"VIP"', b'\xff']
        bodies += [json.dumps({'tier': value}) for value in (None, '', 'FREE', 'ADMIN', 'gold', 1, {}, [])]
        for body in bodies:
            with self.subTest(body=body):
                response = self.client.generic('POST', reverse('billing-checkout'), data=body,
                                               content_type='application/json')
                self.assertEqual(response.status_code, 400, response.content)
        for tier in ('', 'FREE', 'ADMIN'):
            self.assertEqual(self.client.get(reverse('billing-plan'), {'tier': tier}).status_code, 400)
        self.provider.plan.assert_not_called()
        self.provider.create.assert_not_called()
        self.assertFalse(Subscription.objects.exists())

    def test_invalid_mapping_is_rejected_by_checks_and_checkout(self):
        for config in [
            {'PAYPAL_GOLD_PLAN_ID': '', 'PAYPAL_PREMIUM_PLAN_ID': '', 'PAYPAL_VIP_PLAN_ID': ''},
            {'PAYPAL_VIP_PLAN_ID': 'P-GOLD'}, {'PAYPAL_GOLD_PLAN_ID': '../bad-id'},
        ]:
            with self.subTest(config=config), override_settings(**config):
                self.assertIn('billing.E004', [error.id for error in billing_configuration()])
                self.assertIn(self.checkout().status_code, (400, 409))
        with override_settings(PAYPAL_PLAN_ID='P-LEGACY'):
            self.assertIn('billing.E004', [error.id for error in billing_configuration()])
        self.provider.create.assert_not_called()
        self.assertFalse(Subscription.objects.exists())

    @override_settings(PAYPAL_VIP_PLAN_ID='')
    def test_unconfigured_tier_is_not_purchased(self):
        self.assertEqual(self.checkout('VIP').status_code, 400)
        self.provider.create.assert_not_called()

    def test_wrong_provider_plan_rejected_before_purchase(self):
        self.plans['P-VIP']['id'] = 'P-GOLD'
        self.assertEqual(self.checkout('VIP').status_code, 503)
        self.assertFalse(Subscription.objects.exists())
        self.provider.create.assert_not_called()

    def test_verified_event_for_wrong_plan_cannot_activate_tier(self):
        response = self.checkout('VIP')
        sub = Subscription.objects.get(pk=response.json()['id'])
        sale = self.prepare_payment(sub)
        self.remote['plan_id'] = 'P-GOLD'
        self.event('PAYMENT.SALE.COMPLETED', sale, expected=400)
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(WebhookEvent.objects.exists())
        self.assertEqual(self.entitlement()['tier'], 'FREE')

    def test_retry_cannot_change_tier_mapping_price_or_currency(self):
        self.provider.create.side_effect = ProviderError('timeout')
        self.assertEqual(self.checkout().status_code, 503)
        sub = Subscription.objects.get()
        self.assertEqual(self.checkout('VIP').status_code, 409)
        self.plans['P-NEW'] = copy.deepcopy(self.plans['P-GOLD'])
        self.plans['P-NEW']['id'] = 'P-NEW'
        with override_settings(PAYPAL_GOLD_PLAN_ID='P-NEW', PAYPAL_PLAN_ID='P-NEW'):
            self.assertEqual(self.checkout().status_code, 409)
        price = self.plans['P-GOLD']['billing_cycles'][0]['pricing_scheme']['fixed_price']
        price['value'] = '199.00'
        self.assertEqual(self.checkout().status_code, 409)
        price.update(value='49.00', currency_code='USD')
        self.assertEqual(self.checkout().status_code, 409)
        sub.refresh_from_db()
        self.assertEqual((sub.tier, sub.plan_id, sub.amount, sub.currency),
                         ('GOLD', 'P-GOLD', Decimal('49.00'), 'ILS'))
        self.assertEqual(Subscription.objects.count(), 1)
        self.provider.create.assert_called_once()
        self.assertEqual(self.entitlement()['tier'], 'FREE')

    def test_provider_adapter_fetches_selected_plan(self):
        provider = PayPal()
        with patch.object(provider, 'request', return_value=self.plans['P-VIP']) as request:
            provider.plan('P-VIP')
            request.assert_called_once_with('GET', '/v1/billing/plans/P-VIP')
