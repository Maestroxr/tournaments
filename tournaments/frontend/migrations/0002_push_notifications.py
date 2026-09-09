from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('frontend', '0001_initial'), ('tournaments', '0015_tournament_created_at'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='PushSubscription', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('endpoint_hash', models.CharField(max_length=64, unique=True)),
            ('endpoint', models.URLField(max_length=2048)),
            ('p256dh', models.CharField(max_length=128)),
            ('auth', models.CharField(max_length=64)),
            ('language', models.CharField(default='he', max_length=2)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='push_subscriptions', to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.CreateModel(name='PushDelivery', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('attempts', models.PositiveSmallIntegerField(default=0)),
            ('next_attempt_at', models.DateTimeField()),
            ('delivered_at', models.DateTimeField(blank=True, null=True)),
            ('discarded_at', models.DateTimeField(blank=True, null=True)),
            ('fixture', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tournaments.fixture')),
            ('subscription', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='frontend.pushsubscription')),
        ]),
        migrations.AddConstraint(model_name='pushdelivery', constraint=models.UniqueConstraint(fields=('subscription', 'fixture'), name='unique_match_push_per_device')),
    ]
