from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tournaments', '0017_directplaysettings_coin_grant_amount_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='headtoheadtable',
            name='time_control',
            field=models.CharField(
                choices=[('none', 'None'), ('fast', 'Fast'), ('normal', 'Normal'), ('slow', 'Slow')],
                default='normal',
                max_length=20,
            ),
        ),
    ]
