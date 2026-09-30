import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class AccountEmail(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='account_email')
    email = models.EmailField(unique=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)


class GoogleIdentity(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='google_identity')
    subject = models.CharField(max_length=255, unique=True)


class PushWorkerStatus(models.Model):
    last_seen_at = models.DateTimeField()
    expected_by = models.DateTimeField()


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
    last_failure_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    discarded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['subscription', 'fixture'], name='unique_match_push_per_device')]


class TablePushDelivery(models.Model):
    KIND_GUEST_JOINED = 'guest_joined'
    KIND_HOST_ENTERED = 'host_entered'
    KIND_GUEST_ENTERED = 'guest_entered'
    KIND_CHOICES = [(KIND_GUEST_JOINED, 'Guest joined'), (KIND_HOST_ENTERED, 'Host entered'),
                    (KIND_GUEST_ENTERED, 'Guest entered')]

    subscription = models.ForeignKey(PushSubscription, on_delete=models.CASCADE)
    table = models.ForeignKey('tournaments.HeadToHeadTable', on_delete=models.CASCADE)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField()
    last_failure_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    discarded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['subscription', 'table', 'kind'], name='unique_table_push_per_device_event',
        )]


class Task(models.Model):
    NAME_DELIVER_ADMIN_COMMAND = 'deliver_admin_command'
    NAME_EXPIRE_UNSTARTED_GAMES = 'expire_unstarted_games'
    NAME_START_SCHEDULED_TOURNAMENTS = 'start_scheduled_tournaments'
    NAME_CHOICES = [
        (NAME_DELIVER_ADMIN_COMMAND, 'Deliver admin command'),
        (NAME_EXPIRE_UNSTARTED_GAMES, 'Expire unstarted games'),
        (NAME_START_SCHEDULED_TOURNAMENTS, 'Start scheduled tournaments'),
    ]
    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_DONE = 'done'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_DONE, 'Done'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=40, choices=NAME_CHOICES)
    kwargs = models.JSONField(default=dict)
    status = models.CharField(max_length=8, choices=STATUS_CHOICES, default=STATUS_PENDING)
    run_at = models.DateTimeField(default=timezone.now)
    attempts = models.PositiveIntegerField(default=0)
    lease_token = models.UUIDField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    last_finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('run_at', 'created_at', 'id')
        indexes = [
            models.Index(fields=['status', 'run_at'], name='task_status_run_at_idx'),
            models.Index(fields=['status', 'locked_until'], name='task_status_lease_idx'),
        ]
