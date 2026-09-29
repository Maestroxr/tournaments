from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tournaments', '0028_tournament_gift_received_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='usercontact',
            name='phone_verified',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='usercontact',
            name='phone_verified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
