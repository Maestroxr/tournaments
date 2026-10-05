import base64
import hashlib
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from tournaments.models import Fixture, Knockout, Participant, Participation, Tournament, TournamentRegistration

from .models import PushSubscription, TournamentReminderDelivery
from .tournament_reminders import deliver_tournament_reminders, discover_tournament_reminders


@override_settings(
    WEB_PUSH_PUBLIC_KEY='test-public', WEB_PUSH_PRIVATE_KEY='test-private',
    WEB_PUSH_SUBJECT='mailto:test@example.com',
)
class TournamentReminderTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        clock = patch('frontend.tournament_reminders.timezone.now', return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)
        sender = patch('frontend.tournament_reminders.send_notification')
        self.send = sender.start()
        self.addCleanup(sender.stop)
        self.user = User.objects.create_user(username='reminder-player')
        self.participant = Participant.create_for_user(self.user)
        self.tournament = Tournament.objects.create(
            name='Reminder cup', published=True, podium_spec=[], min_players=2, max_players=8,
            starts_at=self.now + timedelta(minutes=5),
        )
        self.mode = Knockout.objects.create(tournament=self.tournament)
        self.participation = Participation.objects.create(
            tournament=self.tournament, participant=self.participant, slot_id=0,
        )
        self.device = self.subscribe(self.user, 'he')

    def subscribe(self, user, language):
        endpoint = f'https://fcm.googleapis.com/fcm/send/{user.pk}-{language}'
        return PushSubscription.objects.create(
            user=user, language=language, endpoint_hash=hashlib.sha256(endpoint.encode()).hexdigest(),
            endpoint=endpoint,
            p256dh=base64.urlsafe_b64encode(b'\x04' + b'k' * 64).decode().rstrip('='),
            auth=base64.urlsafe_b64encode(b'a' * 16).decode().rstrip('='),
        )

    def move_start(self, minutes):
        self.tournament.starts_at = self.now + timedelta(minutes=minutes)
        self.tournament.save(update_fields=['starts_at'])

    def test_reminder_window_excludes_early_and_started_tournaments(self):
        for minutes in (6, 0, -1):
            self.move_start(minutes)
            self.assertEqual(discover_tournament_reminders(), 0)
        self.move_start(5)
        self.assertEqual(discover_tournament_reminders(), 1)

    def test_one_reminder_per_device_with_localized_text_and_tournament_link(self):
        self.subscribe(self.user, 'en')
        self.assertEqual(discover_tournament_reminders(), 2)
        self.assertEqual(discover_tournament_reminders(), 0)
        self.assertEqual(deliver_tournament_reminders(), 2)
        self.assertEqual(deliver_tournament_reminders(), 0)
        calls = {call.args[0].language: call for call in self.send.call_args_list}
        self.assertIn('בעוד 5 דקות', calls['he'].args[1]['body'])
        self.assertIn('in 5 minutes', calls['en'].args[1]['body'])
        for call in calls.values():
            self.assertIn(self.tournament.name, call.args[1]['body'])
            self.assertEqual(call.args[1]['url'], f'/tournaments/tournaments/{self.tournament.pk}')
            self.assertEqual(call.kwargs['ttl'], 300)

    def test_waitlisted_and_disqualified_players_are_excluded(self):
        other = User.objects.create_user(username='waitlisted-player')
        participant = Participant.create_for_user(other)
        self.subscribe(other, 'he')
        TournamentRegistration.objects.create(
            tournament=self.tournament, participant=participant, status=TournamentRegistration.STATUS_WAITLISTED,
        )
        self.participation.disqualified_at = self.now
        self.participation.save(update_fields=['disqualified_at'])
        self.assertEqual(discover_tournament_reminders(), 0)

    def test_withdrawal_before_delivery_discards_reminder(self):
        discover_tournament_reminders()
        self.participation.delete()
        self.assertEqual(deliver_tournament_reminders(), 0)
        self.send.assert_not_called()
        self.assertIsNotNone(TournamentReminderDelivery.objects.get().discarded_at)

    def test_rescheduled_tournament_discards_old_reminder_and_queues_new_one(self):
        discover_tournament_reminders()
        old = TournamentReminderDelivery.objects.get()
        self.move_start(4)
        self.assertEqual(deliver_tournament_reminders(), 0)
        old.refresh_from_db()
        self.assertIsNotNone(old.discarded_at)
        self.assertEqual(discover_tournament_reminders(), 1)
        self.assertEqual(deliver_tournament_reminders(), 1)
        self.assertIn('בעוד 4 דקות', self.send.call_args.args[1]['body'])
        self.assertEqual(self.send.call_args.kwargs['ttl'], 240)

    def test_cancelled_tournament_discards_reminder(self):
        discover_tournament_reminders()
        self.tournament.published = False
        self.tournament.save(update_fields=['published'])
        self.assertEqual(deliver_tournament_reminders(), 0)
        self.send.assert_not_called()

    def test_started_tournament_discards_reminder(self):
        discover_tournament_reminders()
        Fixture.objects.create(mode=self.mode, level=0)
        self.assertEqual(deliver_tournament_reminders(), 0)
        self.send.assert_not_called()

    def test_reminder_is_not_sent_after_start_time(self):
        discover_tournament_reminders()
        with patch('frontend.tournament_reminders.timezone.now', return_value=self.tournament.starts_at):
            self.assertEqual(deliver_tournament_reminders(), 0)
        self.send.assert_not_called()

    def test_transient_failure_retries_without_duplicate_successful_delivery(self):
        discover_tournament_reminders()
        self.send.side_effect = RuntimeError('temporary failure')
        self.assertEqual(deliver_tournament_reminders(), 0)
        delivery = TournamentReminderDelivery.objects.get()
        self.assertEqual(delivery.attempts, 1)
        self.assertIsNotNone(delivery.last_failure_at)
        self.send.side_effect = None
        self.assertEqual(deliver_tournament_reminders(), 0)
        with patch('frontend.tournament_reminders.timezone.now', return_value=self.now + timedelta(minutes=1)):
            self.assertEqual(deliver_tournament_reminders(), 1)
            self.assertEqual(deliver_tournament_reminders(), 0)

    def test_claimed_delivery_is_not_sent_by_another_worker(self):
        discover_tournament_reminders()
        TournamentReminderDelivery.objects.update(next_attempt_at=self.now + timedelta(minutes=1))
        self.assertEqual(deliver_tournament_reminders(), 0)
        self.send.assert_not_called()

    def test_expired_subscription_is_removed(self):
        discover_tournament_reminders()
        error = RuntimeError('subscription expired')
        error.response = SimpleNamespace(status_code=410)
        self.send.side_effect = error
        self.assertEqual(deliver_tournament_reminders(), 0)
        self.assertFalse(PushSubscription.objects.filter(pk=self.device.pk).exists())
        self.assertFalse(TournamentReminderDelivery.objects.exists())

    def test_switching_account_clears_queued_reminders(self):
        discover_tournament_reminders()
        other = User.objects.create_user(username='new-device-owner')
        self.client.force_login(other)
        response = self.client.post('/api/push/subscription', {
            'endpoint': self.device.endpoint,
            'keys': {'p256dh': self.device.p256dh, 'auth': self.device.auth},
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(TournamentReminderDelivery.objects.exists())
        self.assertEqual(discover_tournament_reminders(), 0)

    def test_existing_push_worker_discovers_and_delivers_reminders(self):
        with (
            patch('frontend.management.commands.run_push_notifications.find_spec', return_value=object()),
            patch('frontend.management.commands.run_push_notifications.discover_ready_matches', return_value=0),
        ):
            call_command('run_push_notifications', once=True)
        self.send.assert_called_once()
        self.assertIsNotNone(TournamentReminderDelivery.objects.get().delivered_at)

    @override_settings(WEB_PUSH_PUBLIC_KEY='')
    def test_unconfigured_push_does_not_queue_or_send(self):
        self.assertEqual(discover_tournament_reminders(), 0)
        self.assertEqual(deliver_tournament_reminders(), 0)
        self.send.assert_not_called()
