from urllib.parse import urlsplit

from django.conf import settings
from django.core.checks import Error, register


@register()
def tranzila_configuration(app_configs=None, **kwargs):
    if not settings.TRANZILA_ENABLED:
        return []
    from .tranzila_setup import readiness
    state = readiness()
    errors = [Error(f'Tranzila configuration missing or invalid: {item["key"]}', id='billing.E010')
              for item in state['checks'] if not item['configured']]
    if state['environment'] not in ('test', 'live'):
        errors.append(Error('TRANZILA_ENVIRONMENT must be test or live.', id='billing.E011'))
    return errors


@register()
def billing_configuration(app_configs=None, **kwargs):
    if not settings.BILLING_ENABLED:
        return []
    errors = []
    # This delivery is intentionally sandbox-only. Live deployment needs merchant
    # underwriting and an accounting integration for the business jurisdiction.
    if settings.PAYPAL_ENVIRONMENT != 'sandbox':
        errors.append(Error('Billing supports sandbox only.', id='billing.E001'))
    for name in ('PAYPAL_CLIENT_ID', 'PAYPAL_CLIENT_SECRET', 'PAYPAL_WEBHOOK_ID'):
        if not getattr(settings, name, ''):
            errors.append(Error(f'{name} is required for billing.', id='billing.E002'))
    from .services import Conflict, configured_plans
    try:
        mappings = configured_plans()
        if settings.PAYPAL_PLAN_ID and settings.PAYPAL_PLAN_ID not in mappings.values():
            raise ValueError('Unmapped default plan.')
    except (Conflict, ValueError):
        errors.append(Error(
            'Configure distinct valid paid plan IDs; PAYPAL_PLAN_ID, if set, must match one of them.',
            id='billing.E004',
        ))
    target = urlsplit(settings.BILLING_RETURN_URL)
    if (target.scheme != 'https' and not (
        settings.DEBUG and target.scheme == 'http' and target.hostname in ('localhost', '127.0.0.1')
    )) or not target.hostname or target.query or target.fragment or target.username:
        errors.append(Error('BILLING_RETURN_URL must be a trusted absolute URL without query/fragment.', id='billing.E003'))
    return errors
