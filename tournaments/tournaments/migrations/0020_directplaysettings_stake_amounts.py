from django.db import migrations, models
import tournaments.models


class Migration(migrations.Migration):
    dependencies = [('tournaments', '0019_fixed_friend_game_fee')]

    operations = [
        migrations.AddField(
            model_name='directplaysettings',
            name='stake_amounts',
            field=models.JSONField(blank=True, default=tournaments.models.default_stake_amounts,
                                   validators=[tournaments.models.validate_stake_amounts]),
        ),
    ]
