import json
import logging
from functools import wraps

from django.conf import settings
from django.db import OperationalError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from . import services
from .models import Payment, Receipt, Subscription
from .paypal import PayPal, ProviderError

logger = logging.getLogger(__name__)


def endpoint(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'detail': 'Authentication required.'}, status=401)
        try:
            return view(request, *args, **kwargs)
        except (Subscription.DoesNotExist, Payment.DoesNotExist, Receipt.DoesNotExist):
            return JsonResponse({'detail': 'Not found.'}, status=404)
        except services.Conflict as error:
            return JsonResponse({'detail': str(error)}, status=409)
        except (ValueError, KeyError, TypeError):
            return JsonResponse({'detail': 'Invalid billing data.'}, status=400)
        except (ProviderError, OperationalError):
            return JsonResponse({'detail': 'Billing is temporarily unavailable. Retry the same action.'}, status=503)
    return wrapped


def serialize(sub):
    return {
        'id': str(sub.pk), 'status': sub.status, 'amount': str(sub.amount), 'currency': sub.currency,
        'tier': sub.tier,
        'cancel_requested': sub.cancel_requested,
        'approval_url': sub.approval_url if sub.status == 'approval_pending' and not sub.cancel_requested else '',
    }


@require_GET
@ensure_csrf_cookie
@endpoint
def status(request):
    entitlement = services.entitlement_for(request.user)
    sub = Subscription.objects.filter(user=request.user).order_by('-created_at').first()
    return JsonResponse({
        'enabled': settings.BILLING_ENABLED, 'environment': 'sandbox',
        'subscription': serialize(sub) if sub else None,
        'entitlements': {
            **entitlement,
            'valid_until': entitlement['valid_until'].isoformat() if entitlement['valid_until'] else None,
        },
        'receipts': [dict(id=str(r.pk), **r.data) for r in Receipt.objects.filter(user=request.user).order_by('-created_at')[:100]],
    })


@require_GET
@endpoint
def plan(request):
    tier, plan_id = services.selected_plan(request.GET.get('tier'))
    amount, currency = services.plan_details(PayPal(), plan_id)
    return JsonResponse({'tier': tier, 'amount': str(amount), 'currency': currency, 'interval': 'month'})


@require_POST
@endpoint
def checkout(request):
    data = json.loads(request.body or '{}')
    if not isinstance(data, dict) or ('tier' in data and (
        not isinstance(data['tier'], str) or data['tier'] not in services.PAID_TIERS
    )):
        raise ValueError('Invalid membership tier.')
    sub = services.checkout(request.user, data.get('tier'))
    return JsonResponse(serialize(sub), status=201)


@require_POST
@endpoint
def cancel(request, identifier):
    return JsonResponse(serialize(services.cancel(request.user, identifier)))


@require_POST
@endpoint
def refund(request, payment_id):
    if not request.user.is_staff:
        return JsonResponse({'detail': 'Staff access required.'}, status=403)
    payment = services.request_refund(payment_id)
    return JsonResponse({'payment_id': payment.pk, 'refund_id': payment.refund_id, 'refunded_amount': str(payment.refunded_amount)})


@require_GET
@endpoint
def receipt(request, identifier):
    item = Receipt.objects.get(pk=identifier, user=request.user)
    response = JsonResponse(dict(id=str(item.pk), **item.data))
    response['Content-Disposition'] = f'attachment; filename="sandbox-receipt-{item.pk}.json"'
    response['Cache-Control'] = 'private, no-store'
    return response


@csrf_exempt
@require_POST
def webhook(request):
    if not settings.BILLING_ENABLED:
        return JsonResponse({'detail': 'Billing is disabled.'}, status=404)
    if len(request.body) > 256 * 1024:
        return JsonResponse({'detail': 'Event too large.'}, status=413)
    try:
        event = json.loads(request.body)
        if not isinstance(event, dict):
            raise ValueError()
        provider = PayPal()
        if not provider.verify(request.headers, event):
            return JsonResponse({'detail': 'Invalid webhook signature.'}, status=400)
        return JsonResponse({'result': services.process_event(event, provider)})
    except (ValueError, KeyError, TypeError):
        logger.warning('Billing webhook rejected: invalid or conflicting provider data.')
        return JsonResponse({'detail': 'Invalid billing event.'}, status=400)
    except (ProviderError, OperationalError):
        logger.warning('Billing webhook requires retry.')
        return JsonResponse({'detail': 'Retry this event.'}, status=503)
