from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tournaments', '0027_directplaysettings_ai_game_fee_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='tournament',
            name='gift_received_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
