from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('gamelink', '0007_gamelink_ready_fields'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='gamelink', name='entry_authorized_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='gamelink', name='entry_player1',
            field=models.ForeignKey(blank=True, null=True, related_name='+',
                                    on_delete=django.db.models.deletion.SET_NULL,
                                    to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='gamelink', name='entry_player2',
            field=models.ForeignKey(blank=True, null=True, related_name='+',
                                    on_delete=django.db.models.deletion.SET_NULL,
                                    to=settings.AUTH_USER_MODEL),
        ),
    ]
