from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('gamelink', '0002_gamelink_doubling_enabled')]

    operations = [
        migrations.AddField(
            model_name='gamelink',
            name='live_snapshot',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='gamelink',
            name='live_updated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
