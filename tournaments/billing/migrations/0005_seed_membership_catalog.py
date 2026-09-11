from django.db import migrations


def seed(apps, schema_editor):
    Product = apps.get_model('billing', 'StoreProduct')
    capabilities = {
        'online_play': True, 'tournaments': True, 'weekly_cup': True,
        'monthly_cup': True, 'grand_championship': True, 'rating': 'basic',
        'pr': 'none', 'analysis': 'none', 'courses': 'none', 'live_lessons': False,
        'ai': 'limited', 'vip_benefits': False,
    }
    overrides = {
        'FREE': {},
        'GOLD': {'rating': 'full', 'pr': 'basic', 'analysis': 'basic', 'courses': 'partial', 'ai': 'more'},
        'PREMIUM': {'pr': 'advanced', 'analysis': 'full', 'courses': 'full', 'live_lessons': True, 'ai': 'unlimited'},
        'VIP': {'pr': 'full', 'vip_benefits': True},
    }
    for tier, changes in overrides.items():
        capabilities = {**capabilities, **changes}
        Product.objects.get_or_create(kind='subscription', tier=tier, defaults={
            'name': tier.title(), 'price': '0.00', 'currency': 'ILS',
            'coin_quantity': 0, 'period_months': 1, 'active': tier == 'FREE',
            'capabilities': capabilities,
        })


class Migration(migrations.Migration):
    dependencies = [('billing', '0004_storeproduct_checkoutrequest_product_snapshot_and_more')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
