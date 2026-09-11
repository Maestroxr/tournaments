import json
import uuid
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch, Q, Sum
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .models import CheckoutEvent, CheckoutRequest, Payment, StoreProduct


@transaction.atomic
def catalog_checkout(data, key, user, actor):
    from .catalog import serialize
    product_id = data['catalog_product_id']
    if type(product_id) is not int or product_id <= 0:
        raise ValueError('Invalid product ID')
    # Retry returns the original snapshot even if price or availability changed.
    previous = CheckoutRequest.objects.filter(idempotency_key=key).first()
    if previous:
        if previous.user_id != user.pk or previous.actor_id != actor.pk or previous.catalog_product_id != product_id:
            return JsonResponse({'detail': 'Idempotency key already used for another request'}, status=409)
        return JsonResponse({'id': str(previous.pk), 'status': previous.status})
    product = StoreProduct.objects.select_for_update().get(pk=product_id, active=True, price__gt=0)
    values = dict(user=user, actor=actor, catalog_product=product, product_snapshot=serialize(product),
                  product=product.kind, tier=product.tier, coin_quantity=product.coin_quantity,
                  amount=product.price, currency=product.currency)
    CheckoutRequest(idempotency_key=key, **values).full_clean(exclude=['idempotency_key'])
    checkout, created = CheckoutRequest.objects.get_or_create(idempotency_key=key, defaults=values)
    if checkout.user_id != user.pk or checkout.actor_id != actor.pk or checkout.catalog_product_id != product_id:
        return JsonResponse({'detail': 'Idempotency key already used for another request'}, status=409)
    if created:
        CheckoutEvent.objects.create(checkout=checkout, kind='draft_created', actor=actor)
    return JsonResponse({'id': str(checkout.pk), 'status': checkout.status}, status=201 if created else 200)


@require_http_methods(['GET', 'POST'])
def admin_checkouts(request):
    from frontend.api import _require_staff
    error = _require_staff(request)
    if error:
        return error
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            if not isinstance(data, dict):
                raise ValueError('Expected an object')
            key = uuid.UUID(str(data.get('idempotency_key', '')))
            user_id = str(data.get('user_id', ''))
            if not user_id.isdecimal():
                raise ValueError('User ID must be an integer')
            user = get_user_model().objects.get(pk=int(user_id))
            if 'catalog_product_id' in data:
                return catalog_checkout(data, key, user, request.user)
            amount = Decimal(str(data.get('amount', '')))
            if not amount.is_finite() or amount <= 0 or amount >= 100000000 or amount != amount.quantize(Decimal('.01')):
                raise ValueError('Invalid amount')
            quantity = str(data.get('coin_quantity', 0))
            if not quantity.isdecimal():
                raise ValueError('Coin quantity must be a whole number')
            values = dict(user=user, actor=request.user, amount=amount,
                          currency=data.get('currency', 'ILS'), product=data.get('product'),
                          tier=data.get('tier', ''), coin_quantity=int(quantity))
            candidate = CheckoutRequest(idempotency_key=key, **values)
            candidate.full_clean(exclude=['idempotency_key'])
            with transaction.atomic():
                checkout, created = CheckoutRequest.objects.get_or_create(idempotency_key=key, defaults=values)
                if any(getattr(checkout, field) != value for field, value in values.items()):
                    return JsonResponse({'detail': 'Idempotency key already used for another request'}, status=409)
                if created:
                    CheckoutEvent.objects.create(checkout=checkout, kind='draft_created', actor=request.user)
            return JsonResponse({'id': str(checkout.pk), 'status': checkout.status}, status=201 if created else 200)
        except (ValueError, TypeError, InvalidOperation, ValidationError, get_user_model().DoesNotExist, StoreProduct.DoesNotExist):
            return JsonResponse({'detail': 'Invalid checkout: choose a user, positive money amount, supported currency and coins or a paid subscription tier.'}, status=400)

    try:
        offset = int(request.GET.get('offset', 0))
        if offset < 0:
            raise ValueError()
    except ValueError:
        return JsonResponse({'detail': 'Invalid offset'}, status=400)
    query = request.GET.get('q', '').strip()[:100]
    rows = CheckoutRequest.objects.select_related('user', 'actor').prefetch_related(
        Prefetch('events', queryset=CheckoutEvent.objects.select_related('actor').order_by('created_at', 'id')))
    if query:
        rows = rows.filter(Q(user__username__icontains=query) | Q(provider_reference__icontains=query))
    for field, choices in [('status', dict(CheckoutRequest.STATUS_CHOICES)), ('product', {'coins', 'subscription'})]:
        value = request.GET.get(field, '')
        if value:
            if value not in choices:
                return JsonResponse({'detail': 'Invalid filter'}, status=400)
            rows = rows.filter(**{field: value})
    totals = list(rows.filter(status='paid').values('currency', 'environment').annotate(amount=Sum('amount'), coins=Sum('coin_quantity')))
    for total in totals:
        total['amount'] = str(total['amount'])
    items = []
    for row in rows.order_by('-created_at', '-id')[offset:offset + 50]:
        items.append(dict(id=str(row.pk), username=row.user.username, user_id=row.user_id,
                          actor=row.actor.username, product=row.product, tier=row.tier,
                          amount=str(row.amount), currency=row.currency, coin_quantity=row.coin_quantity,
                          status=row.status, environment=row.environment, provider=row.provider,
                          provider_reference=(f'{row.provider_terminal}/{row.provider_transaction_index}' if row.provider_transaction_index else row.provider_reference), created_at=row.created_at.isoformat(),
                          events=[dict(kind=e.kind, actor=e.actor.username if e.actor else None,
                                       created_at=e.created_at.isoformat()) for e in row.events.all()]))
    # Existing PayPal sandbox transactions stay visible, separately from Tranzila intents.
    legacy = Payment.objects.select_related('subscription__user').order_by('-paid_at', '-id')
    if query:
        legacy = legacy.filter(subscription__user__username__icontains=query)
    legacy_items = [dict(id=p.id, username=p.subscription.user.username, amount=str(p.amount),
                         currency=p.currency, provider_reference=p.provider_id,
                         refunded_amount=str(p.refunded_amount), reversed=p.reversed,
                         created_at=p.paid_at.isoformat()) for p in legacy[offset:offset + 50]]
    from .tranzila_setup import readiness
    configured = readiness()['ready']
    return JsonResponse(dict(provider={'name': 'tranzila', 'status': 'configured' if configured else 'not_connected', 'checkout_enabled': configured},
                             count=rows.count(), items=items, totals=totals,
                             legacy_payments=legacy_items, legacy_count=legacy.count(), wallet_unit='COINS'))
