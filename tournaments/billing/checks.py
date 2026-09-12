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
