import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


OPEN_STATUSES = ('creating', 'approval_pending', 'approved', 'active', 'past_due', 'suspended')
TIER_CHOICES = (
    ('FREE', 'Free'),
    ('GOLD', 'Gold'),
    ('PREMIUM', 'Premium'),
    ('VIP', 'VIP'),
)


class Subscription(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    provider_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    plan_id = models.CharField(max_length=100)
    # Null means this legacy/provider plan has not been assigned a product tier.
    # It must not be guessed from an amount or a provider plan id.
    tier = models.CharField(max_length=16, choices=TIER_CHOICES, null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=24, default='creating')
    approval_url = models.URLField(max_length=1000, blank=True)
    cancel_requested = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['user'], condition=models.Q(status__in=OPEN_STATUSES),
            name='billing_one_open_subscription',
        )]


class Payment(models.Model):
    # The provider transaction, not the webhook event, is the accounting identity.
    provider_id = models.CharField(max_length=100, unique=True)
    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    paid_at = models.DateTimeField()
    period_end = models.DateTimeField()
    refunded_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    reversed = models.BooleanField(default=False)
    refund_requested_at = models.DateTimeField(null=True, blank=True)
    refund_id = models.CharField(max_length=100, blank=True)


class Refund(models.Model):
    provider_id = models.CharField(max_length=100, unique=True)
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name='refunds')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField()


class Receipt(models.Model):
    """Immutable sandbox payment/credit acknowledgements; never tax invoices."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.OneToOneField(Payment, on_delete=models.PROTECT, null=True, blank=True)
    refund = models.OneToOneField(Refund, on_delete=models.PROTECT, null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    data = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.CheckConstraint(
            check=(models.Q(payment__isnull=False, refund__isnull=True)
                   | models.Q(payment__isnull=True, refund__isnull=False)),
            name='billing_receipt_one_source',
        )]


class WebhookEvent(models.Model):
    provider_id = models.CharField(max_length=100, unique=True)
    event_type = models.CharField(max_length=100)
    # Avoid storing payer PII or card details from the incoming webhook.
    resource_id = models.CharField(max_length=100)
    processed_at = models.DateTimeField(default=timezone.now)


class CheckoutRequest(models.Model):
    """Real-money checkout intent. Never part of the game-coin wallet."""
    STATUS_CHOICES = [(s, s) for s in ('draft', 'pending', 'paid', 'failed', 'cancelled', 'refunded')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_checkouts')
    idempotency_key = models.UUIDField(unique=True)
    catalog_product = models.ForeignKey('StoreProduct', on_delete=models.PROTECT, null=True, blank=True)
    product_snapshot = models.JSONField(default=dict, blank=True)
    provider = models.CharField(max_length=20, default='tranzila', editable=False)
    environment = models.CharField(max_length=10, default='sandbox', choices=[('sandbox', 'Sandbox'), ('live', 'Live')])
    product = models.CharField(max_length=20, choices=[('coins', 'Coins'), ('subscription', 'Subscription')])
    tier = models.CharField(max_length=16, blank=True)
    coin_quantity = models.PositiveIntegerField(default=0)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='ILS', choices=[('ILS', 'ILS'), ('USD', 'USD'), ('EUR', 'EUR')])
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='draft')
    provider_reference = models.CharField(max_length=100, null=True, blank=True, unique=True)
    provider_terminal = models.CharField(max_length=100, blank=True)
    provider_transaction_index = models.CharField(max_length=32, blank=True)
    checkout_session = models.JSONField(default=dict, blank=True)
    session_expires_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    wallet_transaction = models.OneToOneField('tournaments.WalletTransaction', on_delete=models.PROTECT, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(check=models.Q(amount__gt=0), name='checkout_positive_amount'),
            models.CheckConstraint(check=(models.Q(product='coins', coin_quantity__gt=0, tier='') | models.Q(product='subscription', coin_quantity=0, tier__in=['GOLD', 'PREMIUM', 'VIP'])), name='checkout_product_units'),
        ]


class CheckoutEvent(models.Model):
    """Allowlisted audit metadata only; no raw provider payloads or card data."""
    checkout = models.ForeignKey(CheckoutRequest, on_delete=models.PROTECT, related_name='events')
    kind = models.CharField(max_length=32)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True)
    created_at = models.DateTimeField(default=timezone.now)


class StoreProduct(models.Model):
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=16, choices=[('subscription', 'Subscription'), ('coins', 'Coins')])
    tier = models.CharField(max_length=16, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default='ILS', choices=[('ILS', 'ILS'), ('USD', 'USD'), ('EUR', 'EUR')])
    coin_quantity = models.PositiveIntegerField(default=0)
    period_months = models.PositiveSmallIntegerField(default=1)
    active = models.BooleanField(default=False)
    capabilities = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['tier'], condition=models.Q(kind='subscription'), name='store_one_product_per_tier'),
            models.CheckConstraint(check=models.Q(price__gte=0), name='store_nonnegative_price'),
            models.CheckConstraint(check=(models.Q(kind='coins', tier='', coin_quantity__gt=0, period_months=0) | models.Q(kind='subscription', tier__in=['FREE', 'GOLD', 'PREMIUM', 'VIP'], coin_quantity=0, period_months__in=[1, 3, 6, 12])), name='store_valid_product'),
            models.CheckConstraint(check=(models.Q(active=False) | models.Q(tier='FREE', price=0) | models.Q(price__gt=0)), name='store_active_price'),
        ]


class StoreProductAudit(models.Model):
    product = models.ForeignKey(StoreProduct, on_delete=models.PROTECT, related_name='changes')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    before = models.JSONField(default=dict)
    after = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)
