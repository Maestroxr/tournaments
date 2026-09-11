import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .catalog import serialize
from .models import CheckoutRequest, StoreProduct, StoreProductAudit
from .services import capabilities_for


class CatalogTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user('catalog-admin', is_staff=True)
        self.player = get_user_model().objects.create_user('catalog-player')
        self.client.force_login(self.staff)
        self.url = reverse('api-admin-store-catalog')

    def create_coins(self, **overrides):
        return self.client.post(self.url, dict(name='Starter', kind='coins', tier='', price='19.90',
                                               currency='ILS', coin_quantity=500, period_months=0,
                                               capabilities={}, active=True, **overrides), content_type='application/json')

    def patch(self, product, **changes):
        payload = {**serialize(product), **changes}
        return self.client.patch(reverse('api-admin-store-product', args=[product.pk]), payload, content_type='application/json')

    def test_seed_preserves_existing_rights_and_does_not_invent_paid_prices(self):
        data = self.client.get(self.url).json()
        self.assertEqual(len(data['items']), 4)
        self.assertTrue(capabilities_for('VIP')['vip_benefits'])
        self.assertEqual(capabilities_for('FREE')['analysis'], 'none')
        self.assertFalse(StoreProduct.objects.exclude(tier='FREE').filter(active=True).exists())

    def test_edit_plan_changes_effective_permissions_and_audits_actor(self):
        plan = StoreProduct.objects.get(tier='GOLD')
        capabilities = {**plan.capabilities, 'analysis': 'full', 'live_lessons': True}
        response = self.patch(plan, price='39.90', active=True, capabilities=capabilities)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(capabilities_for('GOLD')['analysis'], 'full')
        audit = StoreProductAudit.objects.get()
        self.assertEqual(audit.actor_id, self.staff.pk)
        self.assertEqual(audit.before['price'], '0.00')
        self.assertEqual(audit.after['price'], '39.90')
        self.assertEqual(self.patch(plan, price='45.00').status_code, 409)

    def test_price_units_and_permissions_validation(self):
        plan = StoreProduct.objects.get(tier='GOLD')
        for changes in [dict(price='NaN'), dict(price='-1'), dict(price='1.001'), dict(active=True),
                        dict(capabilities={'is_staff': True}), dict(period_months=2), dict(active='false'),
                        dict(coin_quantity=1), dict(kind='coins')]:
            with self.subTest(changes=changes):
                self.assertEqual(self.patch(plan, **changes).status_code, 400)
        free = StoreProduct.objects.get(tier='FREE')
        self.assertEqual(self.patch(free, price='10').status_code, 400)

    def test_catalog_checkout_snapshots_server_price_and_retries_after_edit(self):
        created = self.create_coins()
        self.assertEqual(created.status_code, 201, created.content)
        product = StoreProduct.objects.get(pk=created.json()['id'])
        payload = dict(user_id=self.player.pk, catalog_product_id=product.pk,
                       idempotency_key=str(uuid.uuid4()), amount='0.01', coin_quantity=99999)
        url = reverse('api-admin-checkouts')
        self.assertEqual(self.client.post(url, payload, content_type='application/json').status_code, 201)
        checkout = CheckoutRequest.objects.get()
        self.assertEqual(checkout.amount, Decimal('19.90'))
        self.assertEqual(checkout.coin_quantity, 500)
        self.assertEqual(self.patch(product, price='25.00', coin_quantity=700, active=False).status_code, 200)
        checkout.refresh_from_db()
        self.assertEqual(checkout.product_snapshot['price'], '19.90')
        self.assertEqual(self.client.post(url, payload, content_type='application/json').status_code, 200)
        payload['idempotency_key'] = str(uuid.uuid4())
        self.assertEqual(self.client.post(url, payload, content_type='application/json').status_code, 400)

    def test_disabled_plan_preserves_member_capabilities(self):
        plan = StoreProduct.objects.get(tier='VIP')
        self.assertFalse(plan.active)
        self.assertTrue(capabilities_for('VIP')['vip_benefits'])

    def test_non_staff_cannot_read_or_edit(self):
        self.client.force_login(self.player)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.create_coins().status_code, 403)
        self.assertEqual(self.patch(StoreProduct.objects.get(tier='GOLD'), price='10').status_code, 403)
