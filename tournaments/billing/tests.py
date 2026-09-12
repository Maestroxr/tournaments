from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from gamelink.models import LinkedAccount

from .models import Payment, Subscription
from .services import TIER_PARENTS, capabilities_for, entitlement_for


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
