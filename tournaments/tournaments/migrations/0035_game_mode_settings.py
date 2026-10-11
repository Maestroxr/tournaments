from copy import deepcopy

from django.db import migrations, models
import tournaments.models


def preserve_current_rules(apps, schema_editor):
    Settings = apps.get_model('tournaments', 'DirectPlaySettings')
    rows = Settings.objects.using(schema_editor.connection.alias)
    for row in rows.all():
        profile = row.format_profiles['match']
        row.friend_rules = {
            'enabled': profile['enabled'] and profile['private'],
            **{key: deepcopy(profile[key]) for key in (
                'target_points', 'time_controls', 'doubling_options', 'max_cube')},
        }
        clocks = row.format_profiles['money']['time_controls']
        row.money_time_control = 'normal' if 'normal' in clocks else clocks[0]
        row.save(update_fields=['friend_rules', 'money_time_control'])


class Migration(migrations.Migration):
    dependencies = [('tournaments', '0034_wallet_prize_uniqueness')]
    operations = [
        migrations.AddField(
            model_name='directplaysettings', name='friend_rules',
            field=models.JSONField(null=True, blank=True, default=tournaments.models.default_friend_rules,
                                   validators=[tournaments.models.validate_friend_rules])),
        migrations.AddField(
            model_name='directplaysettings', name='practice_rules',
            field=models.JSONField(default=tournaments.models.default_practice_rules,
                                   validators=[tournaments.models.validate_practice_rules])),
        migrations.AddField(
            model_name='directplaysettings', name='money_time_control',
            field=models.CharField(max_length=20, blank=True, default='normal',
                                   choices=[('none', 'None'), ('fast', 'Fast'),
                                            ('normal', 'Normal'), ('slow', 'Slow')])),
        migrations.RunPython(preserve_current_rules, migrations.RunPython.noop),
    ]
