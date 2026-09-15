# Generated for prize type text/coins
from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('tournaments', '0025_player_ratings'),
    ]

    operations = [
        migrations.AddField(
            model_name='tournament',
            name='prize_type',
            field=models.CharField(choices=[('coins', 'Coins'), ('text', 'Text')], default='coins', max_length=8),
        ),
        migrations.AddField(
            model_name='tournament',
            name='prize_text',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]
