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
