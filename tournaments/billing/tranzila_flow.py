"""One-time hosted checkout. Incoming notifications are hints, never proof."""
import calendar
import hashlib
import json
from datetime import timedelta
from decimal import Decimal
from functools import wraps

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, OperationalError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from tournaments.models import WalletTransaction
from .models import CheckoutRequest, CheckoutEvent
from .tranzila import Tranzila, ProviderError
from .tranzila_setup import readiness


class ReconciliationRequired(ProviderError):
    pass


def response_errors(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except CheckoutRequest.DoesNotExist:
            return JsonResponse({'detail': 'Checkout not found.'}, status=404)
        except (ValueError, TypeError, KeyError):
            return JsonResponse({'detail': 'Payment data does not match the saved checkout.'}, status=400)
        except ReconciliationRequired:
            return JsonResponse({'detail': 'This payment session expired or its terminal changed. An administrator must reconcile the existing transaction before starting another payment.'}, status=409)
        except (ProviderError, OperationalError):
            return JsonResponse({'detail': 'Payment could not be confirmed. Retry the same request.'}, status=503)
        except IntegrityError:
            return JsonResponse({'detail': 'Payment reference already assigned. Reconciliation required.'}, status=409)
    return wrapped


def check_configuration():
    if not readiness()['ready']:
        raise ProviderError('Tranzila configuration is incomplete.')


@transaction.atomic
def prepare(identifier, user):
    check_configuration()
    row = CheckoutRequest.objects.select_for_update().get(pk=identifier)
    if row.user_id != user.pk and not (user.is_staff or user.is_superuser):
        raise CheckoutRequest.DoesNotExist()
    if not row.catalog_product_id or row.status not in ('draft', 'pending'):
        raise ValueError('Not a purchasable catalog checkout')
    provider = Tranzila()
    environment = 'live' if settings.TRANZILA_ENVIRONMENT == 'live' else 'sandbox'
    if row.checkout_session:
        if (row.provider_terminal != provider.terminal or row.environment != environment
                or not row.session_expires_at or row.session_expires_at <= timezone.now()):
            raise ReconciliationRequired('Existing payment session requires reconciliation; do not create another charge.')
        return row.checkout_session
    # A handshake does not charge a card. On failure the transaction rolls back;
    # the stable checkout ID and provider duplicate key are retained on retry.
    session = provider.handshake(str(row.pk), row.amount, row.currency)
    session.pop('thtk', None)  # token is needed only in the provider form fields
    session['environment'] = settings.TRANZILA_ENVIRONMENT
    row.checkout_session = session
    row.session_expires_at = timezone.now() + timedelta(minutes=19)
    row.provider_terminal = provider.terminal
    row.environment = environment
    row.status = 'pending'
    row.save()
    CheckoutEvent.objects.create(checkout=row, kind='checkout_prepared', actor=user)
    return session


@require_POST
@response_errors
def checkout_session(request, identifier):
    if not request.user.is_authenticated:
        return JsonResponse({'detail': 'Authentication required.'}, status=401)
    if not settings.TRANZILA_PURCHASES_ENABLED and not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'detail': 'Purchases are currently unavailable.'}, status=503)
    response = JsonResponse(prepare(identifier, request.user))
    response['Cache-Control'] = 'private, no-store'
    return response


def add_months(value, months):
    total = value.year * 12 + value.month - 1 + months
    year, month = divmod(total, 12)
    month += 1
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1]))


@transaction.atomic
def verify_payment(identifier, index):
    check_configuration()
    row = CheckoutRequest.objects.select_for_update().get(pk=identifier)
    provider = Tranzila()
    environment = 'live' if settings.TRANZILA_ENVIRONMENT == 'live' else 'sandbox'
    if row.provider_terminal != provider.terminal or row.environment != environment:
        raise ValueError('Wrong terminal or environment')
    reference = hashlib.sha256(f'{environment}:{provider.terminal}:{index}'.encode()).hexdigest()
    if row.status == 'paid':
        if row.provider_reference != reference:
            raise ValueError('Another transaction already paid this checkout')
        return row
    if row.status != 'pending' or not row.checkout_session:
        raise ValueError('Checkout is not awaiting a payment')
    record = provider.lookup(index)
    # These exact report values and custom field mappings must be confirmed on
    # the merchant terminal. Unknown/force/authorization/refund modes fail closed.
    if (record['transaction_index'] != index or record['terminal'] != row.provider_terminal
            or record['checkout_id'] != str(row.pk) or record['duplicate_key'] != str(row.pk)
            or Decimal(record['amount']) != row.amount or record['currency'] != row.currency
            or record['processor_response_code'] != '000' or record['tranmode'] != 'A'
            or record['txn_type'].upper() != 'DEBIT'
            or record['transtatus'] != settings.TRANZILA_APPROVED_TRANSTATUS):
        raise ValueError('Provider record does not prove this purchase')
    get_user_model().objects.select_for_update().get(pk=row.user_id)
    row.provider_reference = reference
    row.provider_transaction_index = str(index)
    row.paid_at = timezone.now()
    row.status = 'paid'
    # Test payments must never credit the live wallet or membership.
    if row.environment == 'live':
        if row.product == 'coins':
            row.wallet_transaction = WalletTransaction.create_entry(
                user=row.user, amount=row.coin_quantity, kind=WalletTransaction.KIND_DEPOSIT,
                note=f'Tranzila coin purchase {row.pk}')
        else:
            months = row.product_snapshot.get('period_months')
            if type(months) is not int or months not in (1, 3, 6, 12):
                raise ValueError('Missing saved subscription period')
            previous = CheckoutRequest.objects.filter(user=row.user, product='subscription', tier=row.tier,
                environment='live', status='paid', valid_until__gt=row.paid_at).order_by('-valid_until').first()
            from .services import paid_access
            legacy = paid_access(row.user).filter(subscription__tier=row.tier).order_by('-period_end').first()
            anchor = max(row.paid_at, previous.valid_until if previous else row.paid_at,
                         legacy.period_end if legacy else row.paid_at)
            row.valid_until = add_months(anchor, months)
    row.checkout_session = {}
    row.save()
    CheckoutEvent.objects.create(checkout=row, kind='payment_verified' if row.environment == 'live' else 'test_payment_verified', actor=None)
    return row


@csrf_exempt
@require_POST
@response_errors
def notify(request):
    if not readiness()['ready']:
        return JsonResponse({'detail': 'Tranzila is disabled or incomplete.'}, status=503)
    if len(request.body) > 16 * 1024:
        return JsonResponse({'detail': 'Notification too large.'}, status=413)
    data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
    if not hasattr(data, 'get'):
        raise ValueError('Invalid notification')
    # Ignore every claimed result/amount/token in the public notification.
    # Only the identifier is used to fetch an authenticated provider report.
    import uuid
    identifier = uuid.UUID(str(data['checkout_id']))
    raw_index = str(data['index'])
    if not raw_index.isascii() or not raw_index.isdecimal() or not 0 < len(raw_index) <= 12:
        raise ValueError('Invalid transaction index')
    existing = CheckoutRequest.objects.filter(pk=identifier).first()
    if existing:
        CheckoutEvent.objects.create(checkout=existing, kind='notification_received')
    try:
        row = verify_payment(identifier, int(raw_index))
    except (ValueError, ProviderError, IntegrityError, OperationalError):
        if existing:
            CheckoutEvent.objects.create(checkout=existing, kind='notification_failed')
        raise
    return JsonResponse({'status': row.status})


@require_POST
@response_errors
def reconcile(request, identifier):
    from .operations import require_finance
    error = require_finance(request)
    if error:
        return error
    data = json.loads(request.body)
    index = data['transaction_index']
    if type(index) is not int or index <= 0 or index > 999999999999:
        raise ValueError('Invalid transaction index')
    from .operations import reconcile_one
    return JsonResponse({'status': reconcile_one(identifier, index, actor=request.user).status})


@require_GET
@response_errors
def order_status(request, identifier):
    if not request.user.is_authenticated:
        return JsonResponse({'detail': 'Authentication required.'}, status=401)
    row = CheckoutRequest.objects.get(pk=identifier, user=request.user)
    from .player_checkout import serialize_order
    response = JsonResponse(serialize_order(row))
    response['Cache-Control'] = 'private, no-store'
    return response
