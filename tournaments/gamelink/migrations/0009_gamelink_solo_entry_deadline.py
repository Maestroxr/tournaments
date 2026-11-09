from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('gamelink', '0008_gamelink_entry_authorization'),
    ]

    operations = [
        migrations.AddField(
            model_name='gamelink', name='solo_entry_deadline',
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
    ]
