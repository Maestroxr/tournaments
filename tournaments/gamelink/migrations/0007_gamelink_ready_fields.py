from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('gamelink', '0006_practicepurchase')]

    operations = [
        migrations.AddField(
            model_name='gamelink',
            name='p1_ready_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='gamelink',
            name='p2_ready_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
