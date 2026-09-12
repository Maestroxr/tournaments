from django.conf import settings
from django.db import models


class AccountEmail(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='account_email')
    email = models.EmailField(unique=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)


class GoogleIdentity(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='google_identity')
    subject = models.CharField(max_length=255, unique=True)


class PushSubscription(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='push_subscriptions')
    endpoint_hash = models.CharField(max_length=64, unique=True)
    endpoint = models.URLField(max_length=2048)
    p256dh = models.CharField(max_length=128)
    auth = models.CharField(max_length=64)
    language = models.CharField(max_length=2, default='he')
    created_at = models.DateTimeField(auto_now_add=True)


class PushDelivery(models.Model):
    subscription = models.ForeignKey(PushSubscription, on_delete=models.CASCADE)
    fixture = models.ForeignKey('tournaments.Fixture', on_delete=models.CASCADE)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField()
    delivered_at = models.DateTimeField(null=True, blank=True)
    discarded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['subscription', 'fixture'], name='unique_match_push_per_device')]


class TablePushDelivery(models.Model):
    KIND_GUEST_JOINED = 'guest_joined'
    KIND_HOST_ENTERED = 'host_entered'
    KIND_CHOICES = [(KIND_GUEST_JOINED, 'Guest joined'), (KIND_HOST_ENTERED, 'Host entered')]

    subscription = models.ForeignKey(PushSubscription, on_delete=models.CASCADE)
    table = models.ForeignKey('tournaments.HeadToHeadTable', on_delete=models.CASCADE)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField()
    delivered_at = models.DateTimeField(null=True, blank=True)
    discarded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['subscription', 'table', 'kind'], name='unique_table_push_per_device_event',
        )]
