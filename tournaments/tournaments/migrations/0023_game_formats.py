from django.db import migrations, models
import tournaments.models


def initialize_profiles(apps, schema_editor):
    Settings = apps.get_model('tournaments', 'DirectPlaySettings')
    for row in Settings.objects.all():
        profiles = tournaments.models.default_format_profiles()
        for name, profile in profiles.items():
            profile['stake_amounts'] = row.stake_amounts
            profile['fee_percent'] = float(row.head_to_head_fee_percent)
            if name == 'match':
                profile.update({key: row.game_rules['match'][key] for key in ('target_points', 'time_controls', 'doubling_options')})
        row.format_profiles = profiles
        row.save(update_fields=['format_profiles'])


class Migration(migrations.Migration):
    dependencies = [('tournaments', '0022_headtoheadtable_quick_stakes')]
    operations = [
        migrations.AddField(model_name='directplaysettings', name='format_profiles', field=models.JSONField(default=tournaments.models.default_format_profiles, validators=[tournaments.models.validate_format_profiles])),
        migrations.AddField(model_name='headtoheadtable', name='game_format', field=models.CharField(max_length=12, default='legacy', choices=[('legacy', 'Legacy'), ('match', 'Match'), ('money', 'Money')])),
        migrations.AddField(model_name='headtoheadtable', name='rules_snapshot', field=models.JSONField(default=dict, blank=True)),
        migrations.AddField(model_name='headtoheadtable', name='settlement', field=models.JSONField(default=dict, blank=True)),
        migrations.RunPython(initialize_profiles, migrations.RunPython.noop),
    ]
