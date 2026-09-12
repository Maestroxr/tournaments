"""Populate the local test store without enabling payment processing."""
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from billing.catalog import validate
from billing.models import StoreProduct


class Command(BaseCommand):
    help = 'Add example memberships and coin packages to a development test store.'

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG or settings.TRANZILA_ENVIRONMENT != 'test':
            raise CommandError('Demo products require DEBUG and the test payment environment.')

        for tier, price in [('GOLD', '50.00'), ('PREMIUM', '99.00'), ('VIP', '149.00')]:
            product = StoreProduct.objects.select_for_update().get(kind='subscription', tier=tier)
            if product.active:
                continue
            # Keep existing prices and permissions configured by the administrator.
            if product.price == 0:
                product.price = Decimal(price)
                product.currency = 'ILS'
            product.active = True
            product.version += 1
            validate(product)
            product.save()

        for quantity, price in [(500, '10.00'), (1500, '25.00'), (3500, '50.00')]:
            name = f'{quantity:,} קויינס — דוגמה'
            if StoreProduct.objects.filter(kind='coins', name=name).exists():
                continue
            product = StoreProduct(
                name=name, kind='coins', tier='', price=Decimal(price), currency='ILS',
                coin_quantity=quantity, period_months=0, active=True,
            )
            validate(product)
            product.save()

        self.stdout.write(self.style.SUCCESS('Demo store products are ready. Payment settings are unchanged.'))
