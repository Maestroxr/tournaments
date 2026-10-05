from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('tournaments', '0032_headtoheadtable_guest_ready_at_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='tournament',
            name='entry_deadline_paused',
            field=models.BooleanField(default=False),
        ),
    ]
