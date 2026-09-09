import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('gamelink', '0003_gamelink_live_snapshot')]

    operations = [
        migrations.CreateModel(
            name='AdminGameCommand',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('body', models.JSONField()),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('delivered', 'Delivered'), ('failed', 'Failed')], default='pending', max_length=16)),
                ('attempts', models.PositiveIntegerField(default=0)),
                ('last_error', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('delivered_at', models.DateTimeField(blank=True, null=True)),
                ('game_link', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='admin_commands', to='gamelink.gamelink')),
            ],
            options={'ordering': ('created_at',)},
        ),
    ]
