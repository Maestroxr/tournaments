from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('tournaments', '0035_game_mode_settings'),
    ]

    operations = [
        migrations.CreateModel(
            name='AdminWalletAdjustment',
            fields=[
                ('operation_id', models.UUIDField(editable=False, primary_key=True, serialize=False)),
                ('action', models.CharField(choices=[('deposit', 'Deposit'), ('withdraw', 'Withdraw')], max_length=8)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('note', models.CharField(max_length=255)),
                ('response', models.JSONField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='admin_wallet_adjustments_created', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='admin_wallet_adjustments', to=settings.AUTH_USER_MODEL)),
                ('transaction', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='admin_adjustment', to='tournaments.wallettransaction')),
            ],
            options={'constraints': [
                models.CheckConstraint(check=models.Q(amount__gt=0), name='admin_wallet_adjustment_amount_positive'),
            ]},
        ),
    ]
