"""Durable opt-in reminders during the five minutes before tournament start."""
import math
from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from tournaments.models import Tournament

from .models import PushSubscription, TournamentReminderDelivery
from .push import DELIVERY_RETRY_DELAY, configured, send_notification


REMINDER_WINDOW = timedelta(minutes=5)
REMINDER_TEXT = {
    'he': {
        'title': 'הטורניר שלך מתחיל בקרוב',
        'body': 'הטורניר „{name}” מתחיל בעוד {minutes} דקות. היכנסו והתכוננו למשחק!',
    },
    'en': {
        'title': 'Your tournament starts soon',
        'body': 'The tournament “{name}” starts in {minutes} minutes. Open the club and get ready to play!',
    },
}


def discover_tournament_reminders():
    if not configured():
        return 0
    now = timezone.now()
    created = 0
    tournaments = Tournament.objects.filter(
        published=True, starts_at__gt=now, starts_at__lte=now + REMINDER_WINDOW,
        stages__fixtures__isnull=True,
    ).distinct()
    for tournament in tournaments:
        if tournament.state != 'open':
            continue
        user_ids = tournament.participations.filter(
            disqualified_at__isnull=True, participant__user__isnull=False,
        ).values_list('participant__user_id', flat=True)
        for device in PushSubscription.objects.filter(user_id__in=user_ids):
            _, new = TournamentReminderDelivery.objects.get_or_create(
                subscription=device, tournament=tournament, scheduled_start=tournament.starts_at,
                defaults={'next_attempt_at': now},
            )
            created += int(new)
    return created


def deliver_tournament_reminders(limit=100, heartbeat=None):
    if not configured():
        return 0
    sent = 0
    due = TournamentReminderDelivery.objects.filter(
        delivered_at=None, discarded_at=None, attempts__lt=5, next_attempt_at__lte=timezone.now(),
    ).order_by('pk')
    for delivery_id in list(due.values_list('pk', flat=True)[:limit]):
        if heartbeat:
            heartbeat()
        now = timezone.now()
        claimed = TournamentReminderDelivery.objects.filter(
            pk=delivery_id, delivered_at=None, discarded_at=None,
            attempts__lt=5, next_attempt_at__lte=now,
        ).update(attempts=F('attempts') + 1, next_attempt_at=now + DELIVERY_RETRY_DELAY)
        if not claimed:
            continue
        delivery = TournamentReminderDelivery.objects.select_related(
            'subscription', 'tournament',
        ).filter(pk=delivery_id).first()
        if not delivery:
            continue
        tournament = delivery.tournament
        remaining = delivery.scheduled_start - now
        if (
            tournament.starts_at != delivery.scheduled_start
            or not timedelta(0) < remaining <= REMINDER_WINDOW
            or tournament.state != 'open'
            or not tournament.participations.filter(
                participant__user_id=delivery.subscription.user_id, disqualified_at__isnull=True,
            ).exists()
        ):
            TournamentReminderDelivery.objects.filter(pk=delivery_id).update(discarded_at=now)
            continue
        text = REMINDER_TEXT.get(delivery.subscription.language, REMINDER_TEXT['he'])
        payload = {
            'title': text['title'],
            'body': text['body'].format(name=tournament.name, minutes=math.ceil(remaining.total_seconds() / 60)),
            'url': f'/tournaments/tournaments/{tournament.pk}',
            'tag': f'tournament-reminder:{tournament.pk}:{delivery.scheduled_start.isoformat()}',
        }
        try:
            send_notification(delivery.subscription, payload, ttl=max(1, int(remaining.total_seconds())))
        except Exception as error:
            response = getattr(error, 'response', None)
            if getattr(response, 'status_code', None) in (404, 410):
                PushSubscription.objects.filter(pk=delivery.subscription_id).delete()
            else:
                TournamentReminderDelivery.objects.filter(pk=delivery_id).update(last_failure_at=timezone.now())
            continue
        TournamentReminderDelivery.objects.filter(pk=delivery_id).update(delivered_at=timezone.now())
        sent += 1
    return sent
