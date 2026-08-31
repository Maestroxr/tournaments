"""
Boot-time guard for the game link (plan §5).

The link is only as safe as its configuration, and a misconfiguration here degrades silently:
an empty secret still signs, and a ``http://`` base URL still redirects. So when the feature is
switched on outside ``DEBUG``, refuse to boot rather than run in a weakened state.
"""

from django.conf import settings
from django.core.checks import Error, Tags, register

MINIMUM_SECRET_LENGTH = 32


@register(Tags.security)
def check_gamelink_settings(app_configs, **kwargs):
    if not getattr(settings, 'GAMELINK_ENABLED', False):
        return list()

    if settings.DEBUG:
        return list()

    errors = list()

    if not _is_strong(getattr(settings, 'GAMELINK_TICKET_SECRET', '')):
        errors.append(
            Error(
                'GAMELINK_TICKET_SECRET is missing or too short.',
                hint = f'Set it from the environment to at least {MINIMUM_SECRET_LENGTH} characters. '
                       'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"',
                id = 'gamelink.E001'))

    result_secrets = [secret for secret in getattr(settings, 'GAMELINK_RESULT_SECRETS', list()) if secret]
    if not result_secrets or not all(_is_strong(secret) for secret in result_secrets):
        errors.append(
            Error(
                'GAMELINK_RESULT_SECRETS is empty or contains a secret that is too short.',
                hint = f'Every entry must be at least {MINIMUM_SECRET_LENGTH} characters. During rotation the '
                       'list holds both the old and the new secret; the signer uses the first.',
                id = 'gamelink.E002'))

    if getattr(settings, 'GAMELINK_TICKET_SECRET', '') in result_secrets:
        errors.append(
            Error(
                'GAMELINK_TICKET_SECRET is also configured as a result secret.',
                hint = 'The two channels must be keyed independently: whoever can mint tickets must not '
                       'thereby also be able to report match results.',
                id = 'gamelink.E003'))

    if getattr(settings, 'GAMELINK_TICKET_SECRET', '') == settings.SECRET_KEY:
        errors.append(
            Error(
                'GAMELINK_TICKET_SECRET must not be the Django SECRET_KEY.',
                id = 'gamelink.E004'))

    backgammon_url = getattr(settings, 'GAMELINK_BACKGAMMON_URL', '')
    if not backgammon_url.startswith('https://'):
        errors.append(
            Error(
                'GAMELINK_BACKGAMMON_URL is not an https:// URL.',
                hint = 'Tickets are bearer credentials and must never traverse plain HTTP.',
                id = 'gamelink.E005'))

    return errors


def _is_strong(secret):
    return bool(secret) and len(secret) >= MINIMUM_SECRET_LENGTH
