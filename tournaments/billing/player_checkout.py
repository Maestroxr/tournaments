"""Player catalog and durable, owner-bound checkout requests."""
import json
import uuid
from functools import wraps

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .catalog import serialize as serialize_product
from .models import CheckoutEvent, CheckoutRequest, StoreProduct
from .tranzila_setup import readiness


def purchases_available():
    return bool(settings.TRANZILA_PURCHASES_ENABLED and readiness()['ready'])


def player_endpoint(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'detail': 'Authentication required.'}, status=401)
        try:
            response = view(request, *args, **kwargs)
        except (CheckoutRequest.DoesNotExist, StoreProduct.DoesNotExist):
            response = JsonResponse({'detail': 'Purchase not found or unavailable.'}, status=404)
        except (ValueError, TypeError, KeyError, ValidationError):
            response = JsonResponse({'detail': 'Invalid purchase data.'}, status=400)
        except IntegrityError:
            response = JsonResponse({'detail': 'Purchase conflict. Refresh your existing orders.'}, status=409)
        except OperationalError:
            response = JsonResponse({'detail': 'Purchase unavailable. Retry the same request.'}, status=503)
        response['Cache-Control'] = 'private, no-store'
        return response
    return wrapped


def serialize_order(row):
    environment = 'live' if settings.TRANZILA_ENVIRONMENT == 'live' else 'sandbox'
    has_session = bool(row.checkout_session)
    recovery_required = row.status == 'pending' and (
        not has_session or not row.session_expires_at or row.session_expires_at <= timezone.now()
        or row.provider_terminal != settings.TRANZILA_TERMINAL or row.environment != environment
    )
    return dict(id=str(row.pk), product_id=row.catalog_product_id,
                name=row.product_snapshot.get('name', ''), product=row.product, tier=row.tier,
                period_months=row.product_snapshot.get('period_months', 0),
                coin_quantity=row.coin_quantity, amount=str(row.amount), currency=row.currency,
                status=row.status, environment=row.environment,
                valid_until=row.valid_until.isoformat() if row.valid_until else None,
                created_at=row.created_at.isoformat(), recovery_required=recovery_required,
                can_cancel=row.status == 'draft' and not has_session,
                session_expires_at=row.session_expires_at.isoformat() if row.session_expires_at else None,
                can_pay=row.status in ('draft', 'pending') and not recovery_required and purchases_available())


@require_GET
@ensure_csrf_cookie
@player_endpoint
def catalog(request):
    state = readiness()
    products = StoreProduct.objects.filter(active=True, price__gt=0).exclude(tier='FREE').order_by('kind', 'id')
    return JsonResponse({'enabled': purchases_available(), 'environment': state['environment'],
                         'items': [serialize_product(product) for product in products]})


@require_http_methods(['GET', 'POST'])
@player_endpoint
def orders(request):
    if request.method == 'GET':
        # Unresolved payments remain discoverable after browser storage loss.
        rows = CheckoutRequest.objects.filter(user=request.user, catalog_product__isnull=False)
        unresolved = list(rows.filter(status__in=['draft', 'pending']).order_by('-created_at'))
        recent = list(rows.exclude(status__in=['draft', 'pending']).order_by('-created_at')[:20])
        return JsonResponse({'items': [serialize_order(row) for row in unresolved + recent]})
    data = json.loads(request.body)
    if not isinstance(data, dict) or set(data) != {'product_id', 'idempotency_key'}:
        raise ValueError('Only a product ID and retry key are accepted')
    product_id = data['product_id']
    if type(product_id) is not int or product_id <= 0 or not isinstance(data['idempotency_key'], str):
        raise ValueError('Invalid product or retry key')
    key = uuid.UUID(data['idempotency_key'])
    with transaction.atomic():
        # Serialize creation across tabs/devices for the same player.
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        previous = CheckoutRequest.objects.filter(idempotency_key=key).first()
        if previous:
            if (previous.user_id != request.user.pk or previous.actor_id != request.user.pk
                    or previous.catalog_product_id != product_id):
                return JsonResponse({'detail': 'Retry key already used for another purchase.'}, status=409)
            return JsonResponse(serialize_order(previous))
        outstanding = CheckoutRequest.objects.filter(user=request.user, catalog_product__isnull=False,
                                                      status__in=['draft', 'pending']).first()
        if outstanding:
            return JsonResponse({'detail': 'Resolve your existing order before starting another purchase.',
                                 'order_id': str(outstanding.pk)}, status=409)
        if not purchases_available():
            return JsonResponse({'detail': 'Purchases are currently unavailable.'}, status=503)
        product = StoreProduct.objects.select_for_update().get(pk=product_id, active=True, price__gt=0)
        if product.tier == 'FREE':
            raise ValueError('Free membership is not purchasable')
        row = CheckoutRequest(user=request.user, actor=request.user, idempotency_key=key,
            catalog_product=product, product_snapshot=serialize_product(product), product=product.kind,
            tier=product.tier, coin_quantity=product.coin_quantity, amount=product.price, currency=product.currency,
            environment='live' if settings.TRANZILA_ENVIRONMENT == 'live' else 'sandbox')
        row.full_clean()
        row.save()
        CheckoutEvent.objects.create(checkout=row, kind='draft_created', actor=request.user)
    return JsonResponse(serialize_order(row), status=201)


@require_POST
@player_endpoint
def cancel_draft(request, identifier):
    with transaction.atomic():
        row = CheckoutRequest.objects.select_for_update().get(pk=identifier, user=request.user)
        if row.status == 'cancelled':
            return JsonResponse(serialize_order(row))
        # Once a handshake exists, cancellation requires provider reconciliation.
        if row.status != 'draft' or row.checkout_session:
            return JsonResponse({'detail': 'A prepared payment must be reconciled before cancellation.'}, status=409)
        row.status = 'cancelled'
        row.save(update_fields=['status', 'updated_at'])
        CheckoutEvent.objects.create(checkout=row, kind='draft_cancelled', actor=request.user)
    return JsonResponse(serialize_order(row))
