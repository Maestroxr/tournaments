import sys
from urllib.parse import urlsplit
from django.conf import settings
from django.core.checks import Error, register


@register()
def account_configuration(app_configs, **kwargs):
    # Django deliberately sets DEBUG=False while executing `manage.py test`,
    # even when the development settings module was selected.
    if settings.DEBUG or 'test' in sys.argv:
        return []
    errors = []
    url = urlsplit(settings.ACCOUNT_FRONTEND_URL)
    if url.scheme != 'https' or not url.hostname or url.username or url.query or url.fragment:
        errors.append(Error('ACCOUNT_FRONTEND_URL must be the canonical HTTPS website URL.', id='accounts.E001'))
    if settings.DEFAULT_FROM_EMAIL.endswith('@localhost') or not settings.EMAIL_HOST:
        errors.append(Error('Configure DEFAULT_FROM_EMAIL and an email transport.', id='accounts.E002'))
    return errors
