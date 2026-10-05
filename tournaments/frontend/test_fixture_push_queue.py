from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from frontend.fixture_push import deliver_fixture_pushes
from frontend.models import FixturePushDelivery, PushDelivery, PushSubscription
from frontend.push import (
    deliver_pending, discover_ready_matches,
    notify_tournament_match_ready, notify_tournament_opponent_waiting,
)
from tournaments.models import Fixture, Knockout, Participant, Participation, Tournament


@override_settings(WEB_PUSH_PUBLIC_KEY='test', WEB_PUSH_PRIVATE_KEY='test', WEB_PUSH_SUBJECT='mailto:test@example.invalid',
                   GAMELINK_ENABLED=True, GAMELINK_BACKGAMMON_URL='https://game.example.invalid')
class FixturePushQueueTests(TestCase):
    def setUp(self):
        self.tournament = Tournament.objects.create(
            name='Queued fixture', published=True, starts_at=timezone.now(), podium_spec=['main.placements[0]'],
        )
        self.stage = Knockout.objects.create(tournament=self.tournament, identifier='main')
        self.users = [User.objects.create(username=f'queue-{index}') for index in range(2)]
        players = [Participant.get_or_create_for_user(user) for user in self.users]
        for index, player in enumerate(players):
            Participation.objects.create(tournament=self.tournament, participant=player, slot_id=index)
        self.fixture = Fixture.objects.create(mode=self.stage, level=0, player1=players[0], player2=players[1],
                                              playable_at=timezone.now())
        self.device = PushSubscription.objects.create(
            user=self.users[1], endpoint_hash='queue-device', endpoint='https://fcm.googleapis.com/test',
            p256dh='test', auth='test',
        )

    def test_request_notifications_queue_once_without_provider_io(self):
        with patch('frontend.push.send_notification') as send:
            self.assertEqual(notify_tournament_opponent_waiting(self.fixture, recipient_id=self.users[1].pk), 1)
            self.assertEqual(notify_tournament_opponent_waiting(self.fixture, recipient_id=self.users[1].pk), 0)
            self.assertEqual(notify_tournament_match_ready(self.fixture, recipient_id=self.users[1].pk), 1)
            self.assertEqual(notify_tournament_match_ready(self.fixture, recipient_id=self.users[1].pk), 0)
        send.assert_not_called()
        self.assertEqual(FixturePushDelivery.objects.count(), 1)
        self.assertEqual(PushDelivery.objects.count(), 1)

    def test_provider_failure_retains_retry_without_raising_to_game_flow(self):
        notify_tournament_opponent_waiting(self.fixture, recipient_id=self.users[1].pk)
        with patch('frontend.push.send_notification', side_effect=TimeoutError):
            self.assertEqual(deliver_fixture_pushes(), 0)
        delivery = FixturePushDelivery.objects.get()
        self.assertEqual(delivery.attempts, 1)
        self.assertIsNotNone(delivery.last_failure_at)
        self.assertIsNone(delivery.delivered_at)
        self.assertIsNone(delivery.lease_token)

    def test_lost_worker_ownership_stops_before_provider_io(self):
        notify_tournament_opponent_waiting(self.fixture, recipient_id=self.users[1].pk)
        with patch('frontend.push.send_notification') as send:
            self.assertEqual(deliver_fixture_pushes(heartbeat=lambda: False), 0)
        send.assert_not_called()
        self.assertEqual(FixturePushDelivery.objects.get().attempts, 0)

    def test_reassigned_device_discards_old_recipient_notification(self):
        notify_tournament_opponent_waiting(self.fixture, recipient_id=self.users[1].pk)
        self.device.user = User.objects.create(username='outside-queue')
        self.device.save(update_fields=['user'])
        with patch('frontend.push.send_notification') as send:
            self.assertEqual(deliver_fixture_pushes(), 0)
        send.assert_not_called()
        self.assertIsNotNone(FixturePushDelivery.objects.get().discarded_at)

    def test_expired_delivery_lease_can_be_reclaimed(self):
        notify_tournament_opponent_waiting(self.fixture, recipient_id=self.users[1].pk)
        FixturePushDelivery.objects.update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        with patch('frontend.push.send_notification') as send:
            self.assertEqual(deliver_fixture_pushes(), 1)
        send.assert_called_once()
        self.assertIsNotNone(FixturePushDelivery.objects.get().delivered_at)

    def test_next_personal_match_defers_without_spending_provider_attempts(self):
        later = Fixture.objects.create(
            mode=self.stage, level=1, player1=self.fixture.player1, player2=self.fixture.player2,
            playable_at=timezone.now(),
        )
        notify_tournament_match_ready(later, recipient_id=self.users[1].pk)
        with patch('frontend.push.send_notification') as send:
            for _ in range(6):
                PushDelivery.objects.update(next_attempt_at=timezone.now() - timedelta(seconds=1))
                self.assertEqual(deliver_pending(), 0)
        send.assert_not_called()
        delivery = PushDelivery.objects.get()
        self.assertEqual(delivery.attempts, 0)
        self.assertIsNone(delivery.discarded_at)
        Fixture.objects.filter(pk=self.fixture.pk).update(score1=5, score2=0, auto_confirmed=True)
        PushDelivery.objects.update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        with patch('frontend.push.send_notification') as send:
            self.assertEqual(deliver_pending(), 1)
            self.assertEqual(deliver_pending(), 0)
        send.assert_called_once()
        delivery.refresh_from_db()
        self.assertEqual(delivery.attempts, 1)
        self.assertIsNotNone(delivery.delivered_at)

    def test_discovery_includes_advanced_pair_while_unrelated_round_is_unfinished(self):
        self.fixture.level = 1
        self.fixture.save(update_fields=['level'])
        outsiders = [Participant.objects.create(name=f'other-branch-{index}') for index in range(2)]
        Fixture.objects.create(mode=self.stage, level=0, player1=outsiders[0], player2=outsiders[1])
        self.assertEqual(self.stage.current_level, 0)
        self.assertEqual(discover_ready_matches(), 1)
        self.assertEqual(PushDelivery.objects.get().fixture_id, self.fixture.pk)

    def test_legacy_match_ready_queue_stops_when_worker_lease_is_lost(self):
        notify_tournament_match_ready(self.fixture, recipient_id=self.users[1].pk)
        with patch('frontend.push.send_notification') as send:
            self.assertEqual(deliver_pending(heartbeat=lambda: False), 0)
        send.assert_not_called()
        self.assertEqual(PushDelivery.objects.get().attempts, 0)

    def test_repeated_discovery_read_budget_does_not_grow_per_fixture(self):
        Tournament.objects.filter(pk=self.tournament.pk).update(published=False)
        counts = []
        for size in (32, 128):
            tournament = Tournament.objects.create(
                name=f'Discovery {size}', published=True, starts_at=timezone.now(),
                podium_spec=['main.placements[0]'],
            )
            stage = Knockout.objects.create(tournament=tournament, identifier='main')
            for index in range(size):
                user = User.objects.create(username=f'discover-{size}-{index}')
                participant = Participant.get_or_create_for_user(user)
                Participation.objects.create(tournament=tournament, participant=participant, slot_id=index)
                PushSubscription.objects.create(
                    user=user, endpoint_hash=f'discover-{size}-{index}',
                    endpoint=f'https://fcm.googleapis.com/discover-{size}-{index}',
                    p256dh='test', auth='test',
                )
            with patch('tournaments.models._notify_match_ready'):
                tournament.update_state()
            self.assertEqual(discover_ready_matches(), size)
            with CaptureQueriesContext(connection) as captured:
                self.assertEqual(discover_ready_matches(), 0)
            self.assertLessEqual(len(captured), 14)
            counts.append(len(captured))
            self.assertEqual(PushDelivery.objects.filter(fixture__mode=stage).count(), size)
            Tournament.objects.filter(pk=tournament.pk).update(published=False)
        self.assertLessEqual(counts[1], counts[0] + 2)
