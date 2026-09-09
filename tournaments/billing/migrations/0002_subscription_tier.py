# Generated manually for the product-tier entitlement catalog.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='subscription',
            name='tier',
            field=models.CharField(blank=True, choices=[('FREE', 'Free'), ('GOLD', 'Gold'), ('PREMIUM', 'Premium'), ('VIP', 'VIP')], max_length=16, null=True),
        ),
    ]
