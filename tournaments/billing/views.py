"""Read-only access to membership and historical payment records."""
from functools import wraps

from django.db import OperationalError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET

from . import services
from .models import Receipt, Subscription


def endpoint(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'detail': 'Authentication required.'}, status=401)
        try:
            response = view(request, *args, **kwargs)
            response['Cache-Control'] = 'private, no-store'
            return response
        except Receipt.DoesNotExist:
            return JsonResponse({'detail': 'Not found.'}, status=404)
        except OperationalError:
            return JsonResponse({'detail': 'Billing is temporarily unavailable.'}, status=503)
    return wrapped


def serialize(sub):
    return {
        'id': str(sub.pk), 'status': sub.status, 'amount': str(sub.amount), 'currency': sub.currency,
        'tier': sub.tier, 'cancel_requested': sub.cancel_requested,
        # Older clients must never resume a retired checkout from a saved link.
        'approval_url': '',
    }


@require_GET
@ensure_csrf_cookie
@endpoint
def status(request):
    entitlement = services.entitlement_for(request.user)
    sub = Subscription.objects.filter(user=request.user).order_by('-created_at').first()
    return JsonResponse({
        # This flag described the retired recurring-subscription API.
        'enabled': False, 'environment': 'sandbox',
        'subscription': serialize(sub) if sub else None,
        'entitlements': {
            **entitlement,
            'valid_until': entitlement['valid_until'].isoformat() if entitlement['valid_until'] else None,
        },
        'receipts': [dict(id=str(r.pk), **r.data) for r in Receipt.objects.filter(user=request.user).order_by('-created_at')[:100]],
    })


@require_GET
@endpoint
def receipt(request, identifier):
    item = Receipt.objects.get(pk=identifier, user=request.user)
    response = JsonResponse(dict(id=str(item.pk), **item.data))
    response['Content-Disposition'] = f'attachment; filename="payment-record-{item.pk}.json"'
    return response


@csrf_exempt
def retired(request, **kwargs):
    """Always inert, including stale clients and delayed provider callbacks."""
    return JsonResponse({'detail': 'This payment endpoint has been retired.'}, status=410)
