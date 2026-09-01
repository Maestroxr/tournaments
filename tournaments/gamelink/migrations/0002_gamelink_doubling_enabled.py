from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gamelink", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="gamelink",
            name="doubling_enabled",
            field=models.BooleanField(default=True),
        ),
    ]
