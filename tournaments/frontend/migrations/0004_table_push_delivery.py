from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('frontend', '0003_google_identity'), ('tournaments', '0023_game_formats')]

    operations = [
        migrations.CreateModel(
            name='TablePushDelivery',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('guest_joined', 'Guest joined'), ('host_entered', 'Host entered')], max_length=20)),
                ('attempts', models.PositiveSmallIntegerField(default=0)),
                ('next_attempt_at', models.DateTimeField()),
                ('delivered_at', models.DateTimeField(blank=True, null=True)),
                ('discarded_at', models.DateTimeField(blank=True, null=True)),
                ('subscription', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='frontend.pushsubscription')),
                ('table', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tournaments.headtoheadtable')),
            ],
        ),
        migrations.AddConstraint(
            model_name='tablepushdelivery',
            constraint=models.UniqueConstraint(fields=('subscription', 'table', 'kind'), name='unique_table_push_per_device_event'),
        ),
    ]
