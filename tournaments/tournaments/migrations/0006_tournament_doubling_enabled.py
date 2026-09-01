from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tournaments", "0005_merge_20260831_1736"),
    ]

    operations = [
        migrations.AddField(
            model_name="tournament",
            name="doubling_enabled",
            field=models.BooleanField(default=True),
        ),
    ]
