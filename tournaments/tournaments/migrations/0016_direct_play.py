from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('tournaments', '0015_tournament_created_at'),
    ]

    operations = [
        migrations.CreateModel(
            name='DirectPlaySettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('enabled', models.BooleanField(default=True)),
                ('friend_fee_per_point', models.DecimalField(decimal_places=2, default=Decimal('50.00'), max_digits=10)),
                ('head_to_head_fee_percent', models.DecimalField(decimal_places=2, default=Decimal('5.00'), max_digits=5)),
                ('tournament_fee_percent', models.DecimalField(decimal_places=2, default=Decimal('10.00'), max_digits=5)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'verbose_name': 'Direct play settings', 'verbose_name_plural': 'Direct play settings'},
        ),
        migrations.CreateModel(
            name='HeadToHeadTable',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=6, unique=True)),
                ('mode', models.CharField(choices=[('match', 'Match play'), ('friend', 'Play with a friend')], max_length=16)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('fee_percent', models.DecimalField(decimal_places=2, max_digits=5)),
                ('fee_per_player', models.DecimalField(decimal_places=2, max_digits=10)),
                ('target_points', models.PositiveSmallIntegerField(default=1)),
                ('doubling_enabled', models.BooleanField(default=True)),
                ('status', models.CharField(choices=[('open', 'Open'), ('ready', 'Ready'), ('playing', 'Playing'), ('completed', 'Completed'), ('cancelled', 'Cancelled')], default='open', max_length=16)),
                ('external_room_id', models.CharField(blank=True, max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('guest', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='joined_head_to_head_tables', to=settings.AUTH_USER_MODEL)),
                ('host', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='hosted_head_to_head_tables', to=settings.AUTH_USER_MODEL)),
                ('winner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='won_head_to_head_tables', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ('-created_at',)},
        ),
        migrations.AddField(
            model_name='wallettransaction',
            name='head_to_head_table',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='wallet_transactions', to='tournaments.headtoheadtable'),
        ),
        migrations.AddConstraint(model_name='directplaysettings', constraint=models.CheckConstraint(check=models.Q(('friend_fee_per_point__gt', 0)), name='direct_play_friend_fee_per_point_positive')),
        migrations.AddConstraint(model_name='directplaysettings', constraint=models.CheckConstraint(check=models.Q(('head_to_head_fee_percent__gte', 0), ('head_to_head_fee_percent__lte', 100)), name='direct_play_fee_percent_range')),
        migrations.AddConstraint(model_name='directplaysettings', constraint=models.CheckConstraint(check=models.Q(('tournament_fee_percent__gte', 8), ('tournament_fee_percent__lte', 10)), name='tournament_fee_percent_range')),
        migrations.AddConstraint(model_name='headtoheadtable', constraint=models.CheckConstraint(check=models.Q(('amount__gt', 0)), name='head_to_head_amount_positive')),
        migrations.AddConstraint(model_name='headtoheadtable', constraint=models.CheckConstraint(check=models.Q(('fee_per_player__gte', 0)), name='head_to_head_fee_nonnegative')),
        migrations.AlterField(
            model_name='wallettransaction',
            name='kind',
            field=models.CharField(choices=[('deposit', 'Deposit'), ('withdrawal', 'Withdrawal'), ('tournament_entry', 'Tournament entry'), ('tournament_refund', 'Tournament refund'), ('tournament_prize', 'Tournament prize'), ('head_to_head_entry', 'Head-to-head entry'), ('friend_game_fee', 'Friend game fee'), ('head_to_head_refund', 'Head-to-head refund'), ('head_to_head_prize', 'Head-to-head prize')], max_length=32),
        ),
    ]
