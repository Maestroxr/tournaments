import json
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .models import StoreProduct, StoreProductAudit

CAPABILITY_SCHEMA = {
    **{key: [False, True] for key in ('online_play', 'tournaments', 'weekly_cup', 'monthly_cup',
                                      'grand_championship', 'live_lessons', 'vip_benefits')},
    'rating': ['basic', 'full'], 'pr': ['none', 'basic', 'advanced', 'full'],
    'analysis': ['none', 'basic', 'full'], 'courses': ['none', 'partial', 'full'],
    'ai': ['limited', 'more', 'unlimited'],
}


def serialize(product):
    return dict(id=product.pk, name=product.name, kind=product.kind, tier=product.tier,
                price=str(product.price), currency=product.currency, coin_quantity=product.coin_quantity,
                period_months=product.period_months, active=product.active,
                capabilities=product.capabilities, version=product.version)


def validate(product):
    if not isinstance(product.name, str) or not product.name.strip():
        raise ValueError('A product name is required')
    product.name = product.name.strip()
    if type(product.active) is not bool:
        raise ValueError('Active must be a boolean')
    for key in ('coin_quantity', 'period_months'):
        if type(getattr(product, key)) is not int:
            raise ValueError('Quantities and periods must be whole numbers')
    product.price = Decimal(str(product.price))
    if not product.price.is_finite() or product.price != product.price.quantize(Decimal('.01')):
        raise ValueError('Invalid price')
    if not isinstance(product.capabilities, dict):
        raise ValueError('Invalid permissions')
    if product.kind == 'coins':
        if product.capabilities:
            raise ValueError('Coin packages cannot grant membership permissions')
    else:
        if set(product.capabilities) != set(CAPABILITY_SCHEMA):
            raise ValueError('Provide all supported permissions')
        for key, choices in CAPABILITY_SCHEMA.items():
            value = product.capabilities[key]
            if not any(type(value) is type(choice) and value == choice for choice in choices):
                raise ValueError('Invalid permission value')
        if product.tier == 'FREE' and product.price != 0:
            raise ValueError('The free tier must remain free')
    product.full_clean()


@require_http_methods(['GET', 'POST', 'PATCH'])
def admin_catalog(request, pk=None):
    from frontend.api import _require_staff
    error = _require_staff(request)
    if error:
        return error
    if request.method == 'GET' and pk is None:
        return JsonResponse({'items': [serialize(p) for p in StoreProduct.objects.order_by('kind', 'id')],
                             'capability_schema': CAPABILITY_SCHEMA})
    if (request.method == 'POST' and pk is not None) or (request.method != 'POST' and request.method != 'PATCH') or (request.method == 'PATCH' and pk is None):
        return JsonResponse({'detail': 'Unsupported operation'}, status=405)
    try:
        data = json.loads(request.body)
        editable = {'name', 'kind', 'tier', 'price', 'currency', 'coin_quantity', 'period_months', 'active', 'capabilities'}
        if not isinstance(data, dict) or set(data) - editable - {'version', 'id'}:
            raise ValueError('Invalid product fields')
        with transaction.atomic():
            if pk is not None:
                product = StoreProduct.objects.select_for_update().get(pk=pk)
                if type(data.get('version')) is not int or data['version'] != product.version:
                    return JsonResponse({'detail': 'Product changed. Reload before saving.'}, status=409)
                if any(key in data and data[key] != getattr(product, key) for key in ('kind', 'tier')):
                    raise ValueError('Product type and tier cannot be changed')
                before = serialize(product)
                product.version += 1
            else:
                product = StoreProduct()
                before = {}
            for key in editable & data.keys():
                setattr(product, key, data[key])
            validate(product)
            product.save()
            after = serialize(product)
            StoreProductAudit.objects.create(product=product, actor=request.user, before=before, after=after)
        return JsonResponse(after, status=201 if pk is None else 200)
    except StoreProduct.DoesNotExist:
        return JsonResponse({'detail': 'Product not found'}, status=404)
    except (ValueError, TypeError, InvalidOperation, ValidationError, IntegrityError) as exc:
        detail = '; '.join(exc.messages) if isinstance(exc, ValidationError) else 'Invalid product configuration' if isinstance(exc, IntegrityError) else str(exc)
        return JsonResponse({'detail': detail}, status=400)
