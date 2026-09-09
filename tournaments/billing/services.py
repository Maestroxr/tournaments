import calendar
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import OPEN_STATUSES, Payment, Receipt, Refund, Subscription, TIER_CHOICES, WebhookEvent
from .paypal import PayPal, ProviderError, provider_id


class Conflict(Exception):
    pass


# Product labels are working names. This catalog describes eligibility only; it
# does not claim that an engine, course, lesson, or VIP benefit is implemented.
TIER_PARENTS = {
    'FREE': None,
    'GOLD': 'FREE',
    'PREMIUM': 'GOLD',
    'VIP': 'PREMIUM',
}
TIER_FEATURES = {
    'FREE': {
        'online_play': True,
        'tournaments': True,
        'weekly_cup': True,
        'monthly_cup': True,
        'grand_championship': True,
        'rating': 'basic',
        'pr': 'none',
        'analysis': 'none',
        'courses': 'none',
        'live_lessons': False,
        'ai': 'limited',
        'vip_benefits': False,
    },
    'GOLD': {
        'rating': 'full',
        'pr': 'basic',
        'analysis': 'basic',
        'courses': 'partial',
        'ai': 'more',
    },
    'PREMIUM': {
        'pr': 'advanced',
        'analysis': 'full',
        'courses': 'full',
        'live_lessons': True,
        'ai': 'unlimited',
    },
    'VIP': {
        'pr': 'full',
        'vip_benefits': True,
    },
}
KNOWN_TIERS = frozenset(choice for choice, _ in TIER_CHOICES)
PAID_TIERS = frozenset(('GOLD', 'PREMIUM', 'VIP'))


def capabilities_for(tier):
    """Return the cumulative product catalog for a known tier."""
    if tier not in KNOWN_TIERS:
        tier = 'FREE'
    lineage = []
    while tier:
        lineage.append(tier)
        tier = TIER_PARENTS[tier]
    capabilities = {}
    for item in reversed(lineage):
        capabilities.update(TIER_FEATURES[item])
    return capabilities


def timestamp(value):
    result = parse_datetime(value) if isinstance(value, str) else None
    if not result or timezone.is_naive(result):
        raise ValueError('A timezone-aware provider timestamp is required.')
    return result


def money(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result <= 0 or result >= Decimal('100000000') or result != result.quantize(Decimal('.01')):
            raise ValueError('Invalid payment amount.')
        return result
    except InvalidOperation as error:
        raise ValueError('Invalid payment amount.') from error


def month_after(value):
    year, month = (value.year + 1, 1) if value.month == 12 else (value.year, value.month + 1)
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1]))


def period_end(paid_at, anchor):
    # Preserve the original billing day (Jan 31 -> Feb 28 -> Mar 31).
    # A delayed retry pays for the current billing period, not an extra month
    # beyond the next scheduled renewal.
    if paid_at < anchor - timedelta(minutes=5):
        raise ValueError('Payment predates the subscription.')
    year, month = paid_at.year, paid_at.month
    boundary = anchor.replace(year=year, month=month, day=min(anchor.day, calendar.monthrange(year, month)[1]))
    if boundary <= paid_at + timedelta(minutes=5):
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        boundary = anchor.replace(year=year, month=month, day=min(anchor.day, calendar.monthrange(year, month)[1]))
    return boundary


def paid_access(user):
    """Single server-side entitlement predicate, including expiry and refunds."""
    return Payment.objects.filter(
        subscription__user=user, paid_at__lte=timezone.now(), period_end__gt=timezone.now(),
        refunded_amount__lt=F('amount'), reversed=False,
    )


def has_membership(user):
    return user.is_authenticated and paid_access(user).exists()


def entitlement_for(user):
    """Resolve access from one payment and that payment's subscription only.

    The longest remaining paid period wins. Equal periods are resolved by most
    recent payment time, then primary key, so the result is deterministic.
    Legacy subscriptions without a tier retain their paid membership status but
    receive only the effective FREE catalog.
    """
    access = paid_access(user).select_related('subscription').order_by('-period_end', '-paid_at', '-pk').first()
    tier = access.subscription.tier if access and access.subscription.tier in KNOWN_TIERS else 'FREE'
    return {
        'membership': bool(access),
        'tier': tier,
        'valid_until': access.period_end if access else None,
        'capabilities': capabilities_for(tier),
    }


def configured_plans():
    mappings = {
        tier: provider_id(value)
        for tier in sorted(PAID_TIERS)
        if (value := getattr(settings, f'PAYPAL_{tier}_PLAN_ID', ''))
    }
    if not mappings or len(set(mappings.values())) != len(mappings):
        raise Conflict('Membership plan mapping is invalid.')
    return mappings


def selected_plan(tier):
    mappings = configured_plans()
    if tier is None:
        default = settings.PAYPAL_PLAN_ID
        matches = [item for item, plan_id in mappings.items() if plan_id == default]
        if len(matches) != 1:
            raise Conflict('Select an available membership plan.')
        tier = matches[0]
    if not isinstance(tier, str) or tier not in mappings:
        raise ValueError('Invalid membership tier.')
    return tier, mappings[tier]


def plan_details(provider, plan_id):
    plan = provider.plan(plan_id)
    cycles = plan.get('billing_cycles', [])
    # One fixed monthly price, no trials, setup fees, shipping, taxes or arrears.
    # This keeps each paid sale equivalent to exactly one service month.
    preferences = plan.get('payment_preferences', {})
    if (plan.get('status') != 'ACTIVE' or plan.get('id') != plan_id
            or len(cycles) != 1 or cycles[0].get('tenure_type') != 'REGULAR'
            or cycles[0].get('frequency') != {'interval_unit': 'MONTH', 'interval_count': 1}
            or cycles[0].get('total_cycles') != 0
            or plan.get('quantity_supported') or plan.get('taxes')
            or preferences.get('auto_bill_outstanding', True)
            or Decimal(str(preferences.get('setup_fee', {}).get('value', '0'))) != 0):
        raise ProviderError('Configure an active fixed monthly plan without trials, setup fees, taxes or arrears.')
    price = cycles[0]['pricing_scheme']['fixed_price']
    currency = price['currency_code']
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
        raise ProviderError('Invalid plan currency.')
    return money(price['value']), currency.upper()


def checkout(user, tier):
    tier, plan_id = selected_plan(tier)
    provider = PayPal()
    amount, currency = plan_details(provider, plan_id)
    # Persist the idempotency key before making the network request. A timeout
    # can then be retried with the same key, even following a process crash.
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        sub = Subscription.objects.filter(user=user, status__in=OPEN_STATUSES).first()
        if not sub:
            if has_membership(user):
                raise Conflict('The paid membership period has not ended yet.')
            sub = Subscription.objects.create(user=user, plan_id=plan_id, tier=tier, amount=amount, currency=currency)
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().get(pk=sub.pk)
        if (sub.status not in ('creating', 'approval_pending') or sub.cancel_requested
                or sub.tier != tier or sub.plan_id != plan_id or sub.amount != amount or sub.currency != currency):
            raise Conflict('A subscription already exists. Manage it before purchasing again.')
        if sub.provider_id:
            return sub
        if sub.created_at < timezone.now() - timedelta(hours=70):
            # PayPal only retains create-subscription request IDs for 72 hours.
            raise Conflict('Checkout requires provider reconciliation before another attempt.')
        sub.provider_id, sub.approval_url = provider.create(sub)
        sub.status = 'approval_pending'
        sub.save()
        return sub


def sync_status(sub, remote):
    if (remote.get('id') != sub.provider_id or remote.get('plan_id') != sub.plan_id
            or remote.get('custom_id') != str(sub.pk)):
        raise ValueError('Provider subscription does not match this purchase.')
    state = remote.get('status', '').lower()
    if state not in ('approval_pending', 'approved', 'active', 'suspended', 'cancelled', 'expired'):
        raise ValueError('Unknown provider subscription status.')
    if state == 'active' and remote.get('billing_info', {}).get('failed_payments_count', 0):
        state = 'past_due'
    # A stale activation callback must not undo confirmed cancellation.
    if sub.status not in ('cancelled', 'expired'):
        sub.status = state
    sub.save(update_fields=['status', 'updated_at'])


def cancel(user, identifier):
    # Keep the intent durable if PayPal accepts cancellation but the response is lost.
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().get(pk=identifier, user=user)
        sub.cancel_requested = True
        sub.save(update_fields=['cancel_requested', 'updated_at'])
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().get(pk=sub.pk)
        if sub.status in ('cancelled', 'expired'):
            return sub
        if not sub.provider_id:
            raise Conflict('Reconcile the pending checkout before cancellation.')
        provider = PayPal()
        remote = provider.subscription(sub.provider_id)
        sync_status(sub, remote)
        if sub.status not in ('cancelled', 'expired'):
            provider.cancel(sub)
            sub.status = 'cancelled'
            sub.save(update_fields=['status', 'updated_at'])
        return sub


def receipt_for(payment, refund=None):
    amount = refund.amount if refund else payment.amount
    relation = {'refund': refund} if refund else {'payment': payment}
    Receipt.objects.get_or_create(**relation, defaults={
        'user': payment.subscription.user,
        'data': {
            'environment': 'sandbox', 'kind': 'credit' if refund else 'payment',
            'description': 'Monthly Backgammon membership',
            'provider': 'PayPal', 'transaction_id': refund.provider_id if refund else payment.provider_id,
            'original_transaction_id': payment.provider_id,
            'amount': str(amount), 'currency': payment.currency,
            'issued_at': (refund.created_at if refund else payment.paid_at).isoformat(),
            'notice': 'Sandbox payment acknowledgement. Not a tax invoice or fiscal receipt.',
        },
    })


def record_refund(payment, resource):
    if resource.get('state') != 'completed':
        return
    if resource.get('sale_id') != payment.provider_id:
        raise ValueError('Refund does not match the original payment.')
    amount = money(resource['amount']['total'])
    if resource['amount']['currency'] != payment.currency:
        raise ValueError('Refund currency mismatch.')
    refund, created = Refund.objects.get_or_create(provider_id=provider_id(resource['id']), defaults={
        'payment': payment, 'amount': amount, 'created_at': timestamp(resource['create_time']),
    })
    if refund.payment_id != payment.pk or refund.amount != amount:
        raise ValueError('Conflicting refund identity.')
    if created:
        if payment.refunded_amount + amount > payment.amount:
            raise ValueError('Refund exceeds payment.')
        payment.refunded_amount += amount
        payment.save(update_fields=['refunded_amount'])
    receipt_for(payment, refund)


def request_refund(payment_id):
    # Staff endpoint only. Only full refunds are initiated here; partial refunds
    # made in the provider dashboard are also reconciled by signed callbacks.
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment_id)
        if not payment.refund_requested_at:
            payment.refund_requested_at = timezone.now()
            payment.save(update_fields=['refund_requested_at'])
    with transaction.atomic():
        payment = Payment.objects.select_for_update().select_related('subscription').get(pk=payment_id)
        if payment.refunded_amount == payment.amount or payment.refund_id:
            return payment
        if payment.refund_requested_at < timezone.now() - timedelta(days=29):
            raise Conflict('Reconcile the refund with PayPal before retrying.')
        resource = PayPal().refund(payment)
        if resource.get('state') not in ('pending', 'completed'):
            raise ProviderError('PayPal has not accepted the refund.')
        payment.refund_id = provider_id(resource['id'])
        payment.save(update_fields=['refund_id'])
        record_refund(payment, resource)
        return payment


SUBSCRIPTION_EVENTS = {
    'BILLING.SUBSCRIPTION.CREATED', 'BILLING.SUBSCRIPTION.ACTIVATED',
    'BILLING.SUBSCRIPTION.UPDATED', 'BILLING.SUBSCRIPTION.CANCELLED',
    'BILLING.SUBSCRIPTION.EXPIRED', 'BILLING.SUBSCRIPTION.SUSPENDED',
    'BILLING.SUBSCRIPTION.PAYMENT.FAILED',
}
SALE_EVENTS = {'PAYMENT.SALE.COMPLETED', 'PAYMENT.SALE.REFUNDED', 'PAYMENT.SALE.REVERSED'}


@transaction.atomic
def process_event(event, provider):
    """Only called after provider signature verification; atomically receipt+grant+dedupe."""
    event_id = provider_id(event['id'])
    kind = event['event_type']
    resource = event['resource']
    resource_id = provider_id(resource['id'])
    _, created = WebhookEvent.objects.get_or_create(provider_id=event_id, defaults={
        'event_type': kind, 'resource_id': resource_id,
    })
    if not created:
        return 'duplicate'
    if kind not in SUBSCRIPTION_EVENTS | SALE_EVENTS:
        return 'ignored'

    if kind in ('PAYMENT.SALE.REFUNDED', 'PAYMENT.SALE.REVERSED'):
        sale_id = resource.get('sale_id') if kind.endswith('REFUNDED') else resource_id
        # Missing payment means delivery was out of order: rollback the event
        # marker and ask the provider to retry after the completed event arrives.
        payment = Payment.objects.select_for_update().select_related('subscription').filter(provider_id=sale_id).first()
        if not payment:
            raise ProviderError('Original payment has not been received; retry this event.')
        if kind.endswith('REFUNDED'):
            record_refund(payment, resource)
        else:
            payment.reversed = True
            payment.save(update_fields=['reversed'])
        return 'processed'

    sub_id = resource.get('billing_agreement_id') if kind in SALE_EVENTS else resource_id
    if not sub_id:
        return 'ignored'  # A non-subscription sale from the same merchant app.
    sub = Subscription.objects.select_for_update().filter(provider_id=sub_id).first()
    if not sub:
        raise ProviderError('Checkout has not been persisted; retry this event.')
    # Fetch current provider state, instead of applying lifecycle events in
    # delivery order. Binding is to the server-generated purchase UUID.
    remote = provider.subscription(sub.provider_id)
    sync_status(sub, remote)
    if kind == 'PAYMENT.SALE.COMPLETED':
        if resource.get('state') != 'completed':
            raise ValueError('Payment is not completed.')
        amount = money(resource['amount']['total'])
        currency = resource['amount']['currency']
        if amount != sub.amount or currency != sub.currency:
            raise ValueError('Payment price does not match the subscription.')
        paid_at = timestamp(resource['create_time'])
        payment, _ = Payment.objects.get_or_create(provider_id=resource_id, defaults={
            'subscription': sub, 'amount': amount, 'currency': currency,
            'paid_at': paid_at, 'period_end': period_end(paid_at, timestamp(remote['start_time'])),
        })
        if (payment.subscription_id != sub.pk or payment.amount != amount
                or payment.currency != currency or payment.paid_at != paid_at):
            raise ValueError('Conflicting payment identity.')
        receipt_for(payment)
    return 'processed'
