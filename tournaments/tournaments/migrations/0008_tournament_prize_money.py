from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tournaments", "0007_tournament_entry_fee_wallettransaction_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="tournament",
            name="prize_money",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
    ]
