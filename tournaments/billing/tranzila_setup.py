import re
from urllib.parse import urlsplit

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET


def trusted_url(value):
    try:
        url = urlsplit(value)
        return bool(url.scheme == 'https' and url.hostname and not url.username and not url.password
                    and not url.query and not url.fragment and not any(c.isspace() for c in value))
    except (ValueError, TypeError):
        return False


def readiness():
    checks = {
        'enabled': bool(settings.TRANZILA_ENABLED),
        'terminal': bool(re.fullmatch(r'[A-Za-z0-9_-]{1,100}', settings.TRANZILA_TERMINAL)),
        'api_key': bool(settings.TRANZILA_APP_KEY.strip()),
        'api_secret': bool(settings.TRANZILA_APP_SECRET.strip()),
        'return_url': trusted_url(settings.TRANZILA_RETURN_URL),
        'notify_url': trusted_url(settings.TRANZILA_NOTIFY_URL),
        'report_mapping': bool(settings.TRANZILA_REPORT_MAPPING_CONFIRMED),
        'transaction_status': bool(settings.TRANZILA_APPROVED_TRANSTATUS.strip()),
    }
    valid_environment = settings.TRANZILA_ENVIRONMENT in ('test', 'live')
    return {'ready': all(checks.values()) and valid_environment,
            'purchases_enabled': bool(settings.TRANZILA_PURCHASES_ENABLED and all(checks.values()) and valid_environment),
            'enabled': checks['enabled'], 'environment': settings.TRANZILA_ENVIRONMENT,
            'checks': [{'key': key, 'configured': value} for key, value in checks.items()],
            'automatic_fulfillment': all(checks.values()) and valid_environment, 'recurring_enabled': False}


@require_GET
def admin_readiness(request):
    from frontend.api import _require_staff
    error = _require_staff(request)
    if error:
        return error
    state = readiness()
    from .models import CheckoutRequest
    environment = 'live' if settings.TRANZILA_ENVIRONMENT == 'live' else 'sandbox'
    last = CheckoutRequest.objects.filter(provider_terminal=settings.TRANZILA_TERMINAL,
        environment=environment, paid_at__isnull=False).order_by('-paid_at').first()
    state['last_verified_at'] = last.paid_at.isoformat() if last else None
    response = JsonResponse(state)
    response['Cache-Control'] = 'private, no-store'
    return response
