from django.db import migrations, models
from decimal import Decimal


def initialize_fixed_friend_fee(apps, schema_editor):
    # The former per-point rate is not the new price for the whole game.
    settings_model = apps.get_model('tournaments', 'DirectPlaySettings')
    settings_model.objects.using(schema_editor.connection.alias).all().update(
        friend_game_fee=Decimal('50.00'),
    )


class Migration(migrations.Migration):
    dependencies = [('tournaments', '0018_headtoheadtable_time_control')]

    operations = [
        migrations.RemoveConstraint(
            model_name='directplaysettings',
            name='direct_play_friend_fee_per_point_positive',
        ),
        migrations.RenameField(
            model_name='directplaysettings',
            old_name='friend_fee_per_point',
            new_name='friend_game_fee',
        ),
        migrations.RunPython(initialize_fixed_friend_fee, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='directplaysettings',
            constraint=models.CheckConstraint(
                check=models.Q(friend_game_fee__gt=0),
                name='direct_play_friend_game_fee_positive',
            ),
        ),
    ]
