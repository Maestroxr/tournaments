from django.db import migrations, models
import tournaments.models


class Migration(migrations.Migration):
    dependencies = [('tournaments', '0020_directplaysettings_stake_amounts')]

    operations = [
        migrations.AddField(
            model_name='directplaysettings',
            name='game_rules',
            field=models.JSONField(default=tournaments.models.default_game_rules,
                                   validators=[tournaments.models.validate_game_rules]),
        ),
    ]
