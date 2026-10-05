from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('frontend', '0010_tournament_reminder_delivery'),
        ('tournaments', '0033_tournament_entry_deadline_paused'),
    ]
    operations = [
        migrations.CreateModel(
            name='FixturePushDelivery',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('opponent_waiting', 'Opponent waiting')], max_length=24)),
                ('attempts', models.PositiveSmallIntegerField(default=0)),
                ('next_attempt_at', models.DateTimeField()),
                ('lease_token', models.UUIDField(blank=True, null=True)),
                ('last_failure_at', models.DateTimeField(blank=True, null=True)),
                ('delivered_at', models.DateTimeField(blank=True, null=True)),
                ('discarded_at', models.DateTimeField(blank=True, null=True)),
                ('fixture', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tournaments.fixture')),
                ('subscription', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='frontend.pushsubscription')),
            ],
        ),
        migrations.AddConstraint(
            model_name='fixturepushdelivery',
            constraint=models.UniqueConstraint(fields=('subscription', 'fixture', 'kind'), name='unique_fixture_push_device_event'),
        ),
    ]
