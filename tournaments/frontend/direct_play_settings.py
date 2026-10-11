"""Apply a single admin section without overwriting other settings."""
from copy import deepcopy

from django.core.exceptions import ValidationError


SECTION_FIELDS = {
    'match': {'profile'},
    'money': {'profile', 'money_time_control'},
    'friend': {'friend_rules', 'friend_game_fee'},
    'practice': {'practice_rules', 'ai_game_fee'},
    'tournaments': {'tournament_fee_percent'},
    'settings': {'enabled', 'coin_grant_enabled', 'coin_grant_amount', 'coin_grant_interval_hours'},
    'legacy': {'game_rules', 'stake_amounts', 'head_to_head_fee_percent'},
}
PROFILE_FIELDS = {
    'match': {'enabled', 'public', 'quick', 'target_points', 'time_controls',
              'doubling_options', 'max_cube', 'stake_amounts', 'fee_percent'},
    'money': {'enabled', 'quick', 'doubling_options', 'stake_amounts', 'fee_percent', 'jacoby'},
}


def section_payload(row, data):
    section = data.get('section')
    if section is None:
        return data
    if not isinstance(section, str) or section not in SECTION_FIELDS or set(data) - {'section'} - SECTION_FIELDS[section]:
        raise ValidationError({'section': 'Invalid settings section or fields.'})
    result = {key: value for key, value in data.items() if key != 'section'}
    if 'profile' in result:
        patch = result.pop('profile')
        if not isinstance(patch, dict) or set(patch) - PROFILE_FIELDS[section]:
            raise ValidationError({'profile': 'Invalid profile fields for this game.'})
        profiles = deepcopy(row.format_profiles)
        profiles[section].update(patch)
        result['format_profiles'] = profiles
    return result


def validated_field(field, validator, value):
    try:
        return validator(value)
    except (ValidationError, ValueError, TypeError) as error:
        raise ValidationError({field: getattr(error, 'messages', [str(error)])}) from error
