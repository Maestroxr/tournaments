from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('tournaments', '0023_game_formats')]

    operations = [
        migrations.AddField(
            model_name='headtoheadtable', name='live_snapshot',
            field=models.JSONField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='headtoheadtable', name='live_updated_at',
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]
