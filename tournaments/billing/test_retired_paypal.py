"""Retired provider routes cannot mutate records or contact a provider."""
import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Payment, Receipt, Refund, Subscription, WebhookEvent


@override_settings(TRANZILA_ENABLED=False)
class RetiredPayPalTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='legacy-owner')
        self.sub = Subscription.objects.create(
            user=self.user, plan_id='P-OLD', provider_id='I-OLD', tier='GOLD',
            amount='29.00', currency='ILS', status='approval_pending',
            approval_url='https://www.sandbox.paypal.com/approve',
        )
        self.payment = Payment.objects.create(
            subscription=self.sub, provider_id='SALE-OLD', amount='29.00', currency='ILS',
            paid_at=timezone.now() - timedelta(days=1), period_end=timezone.now() + timedelta(days=5),
        )
        self.record = Receipt.objects.create(user=self.user, payment=self.payment,
            data={'environment': 'sandbox', 'provider': 'PayPal', 'amount': '29.00'})

    def test_retired_routes_are_inert_for_anonymous_member_and_staff(self):
        routes = [('billing-plan', []), ('billing-checkout', []),
                  ('billing-cancel', [self.sub.pk]), ('billing-refund', [self.payment.pk]),
                  ('billing-webhook', [])]
        models = [Subscription, Payment, Receipt, Refund, WebhookEvent]
        before = [list(model.objects.values()) for model in models]
        client = Client(enforce_csrf_checks=True)
        with patch('urllib.request.urlopen', side_effect=AssertionError('No provider calls allowed')):
            for identity in ('anonymous', 'member', 'staff'):
                if identity != 'anonymous':
                    self.user.is_staff = identity == 'staff'
                    self.user.save(update_fields=['is_staff'])
                    client.force_login(self.user)
                for name, args in routes:
                    for method in ('get', 'post'):
                        with self.subTest(identity=identity, route=name, method=method):
                            response = getattr(client, method)(reverse(name, args=args))
                            self.assertEqual(response.status_code, 410)
            response = client.post(reverse('billing-webhook'), json.dumps({
                'id': 'FORGED', 'event_type': 'PAYMENT.SALE.COMPLETED',
                'resource': {'id': 'NEW', 'billing_agreement_id': 'I-OLD'},
            }), content_type='application/json')
            self.assertEqual(response.status_code, 410)
        self.assertEqual(before, [list(model.objects.values()) for model in models])

    def test_history_and_existing_access_remain_private_with_purchases_disabled(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('billing-status'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['enabled'])
        self.assertTrue(data['entitlements']['membership'])
        self.assertEqual(data['entitlements']['tier'], 'GOLD')
        self.assertEqual(data['subscription']['approval_url'], '')
        self.assertEqual(data['receipts'][0]['id'], str(self.record.pk))
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        url = reverse('billing-receipt', args=[self.record.pk])
        response = self.client.get(url)
        self.assertEqual(response.json()['provider'], 'PayPal')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        other = get_user_model().objects.create_user(username='other-owner')
        self.client.force_login(other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(reverse('billing-status')).json()['receipts'], [])
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.get(reverse('billing-status')).status_code, 401)
