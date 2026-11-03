"""Event readiness keeps one-click intent without HTTP polling or stale socket cleanup."""
import datetime
import os
import uuid
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import ANY, AsyncMock, patch

from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from tournaments.models import Fixture, Knockout, Participant, Participation, Tournament

from gamelink import entry_presence, entry_verification
from gamelink.consumers import ClubUpdatesConsumer
from gamelink.entry_waiting import release, state
from gamelink.models import GameLink
from gamelink.views import _fresh_seat

MEMORY_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


class ClubInvalidationTests(SimpleTestCase):
    async def test_repeated_revision_is_skipped_but_new_generation_is_sent(self):
        consumer = ClubUpdatesConsumer()
        consumer.scope = {'user': SimpleNamespace(pk=1)}
        consumer.sent_revisions = {'tournaments': {'generation': 'old', 'sequence': 5}}
        consumer.send_json = AsyncMock()
        revisions = [
            {'generation': 'old', 'sequence': 5},
            {'generation': 'old', 'sequence': 6},
            {'generation': 'old', 'sequence': 6},
            {'generation': 'new', 'sequence': 1},
        ]
        with patch('frontend.lobby_revisions.current', side_effect=revisions):
            for _ in revisions:
                await consumer.club_invalidate({'resource': 'tournaments'})
        self.assertEqual(consumer.send_json.await_count, 2)
        self.assertEqual(consumer.sent_revisions['tournaments'], revisions[-1])

    async def test_failed_send_does_not_acknowledge_the_revision(self):
        consumer = ClubUpdatesConsumer()
        consumer.scope = {'user': SimpleNamespace(pk=1)}
        previous = {'generation': 'old', 'sequence': 5}
        consumer.sent_revisions = {'tournaments': previous}
        consumer.send_json = AsyncMock(side_effect=RuntimeError('send failed'))
        with patch('frontend.lobby_revisions.current', return_value={'generation': 'old', 'sequence': 6}):
            with self.assertRaisesRegex(RuntimeError, 'send failed'):
                await consumer.club_invalidate({'resource': 'tournaments'})
        self.assertEqual(consumer.sent_revisions['tournaments'], previous)


@override_settings(CHANNEL_LAYERS=MEMORY_LAYERS)
class EntryPresenceTests(SimpleTestCase):
    def setUp(self):
        entry_presence._memory.clear()
        self.now = timezone.now()
        self.token = uuid.uuid4().hex

    def tearDown(self):
        entry_presence._memory.clear()

    def test_connected_lease_survives_the_old_fifteen_second_readiness_window(self):
        entry_presence.change(72, 'p1', self.token, 'socket-a', 'join', self.now)
        self.assertTrue(entry_presence.seat_present(72, 'p1', self.now + datetime.timedelta(seconds=25)))
        entry_presence.change(72, 'p1', self.token, 'socket-a', 'touch',
                              self.now + datetime.timedelta(seconds=25))
        self.assertTrue(entry_presence.seat_present(72, 'p1', self.now + datetime.timedelta(seconds=55)))

    def test_old_disconnect_cannot_cancel_the_reconnected_socket(self):
        entry_presence.change(72, 'p1', self.token, 'socket-a', 'join', self.now)
        entry_presence.change(72, 'p1', self.token, 'socket-b', 'join', self.now)
        self.assertFalse(entry_presence.change(72, 'p1', self.token, 'socket-a', 'leave', self.now))
        self.assertTrue(entry_presence.seat_present(72, 'p1', self.now))

    def test_one_tab_leaving_does_not_clear_another_tabs_readiness(self):
        other = uuid.uuid4().hex
        entry_presence.change(72, 'p1', self.token, 'socket-a', 'join', self.now)
        entry_presence.change(72, 'p1', other, 'socket-b', 'join', self.now)
        entry_presence.change(72, 'p1', self.token, 'socket-a', 'leave', self.now)
        self.assertTrue(entry_presence.seat_present(72, 'p1', self.now))
        entry_presence.change(72, 'p1', other, 'socket-b', 'leave', self.now)
        self.assertFalse(entry_presence.seat_present(72, 'p1', self.now))

    def test_disconnect_grace_expires_and_worker_emits_only_a_state_change(self):
        entry_presence.change(72, 'p1', self.token, 'socket-a', 'join', self.now)
        entry_presence.change(72, 'p1', self.token, 'socket-a', 'disconnect', self.now)
        self.assertTrue(entry_presence.seat_present(72, 'p1', self.now + datetime.timedelta(seconds=14)))
        later = self.now + datetime.timedelta(seconds=15)
        self.assertFalse(entry_presence.seat_present(72, 'p1', later))
        with patch('gamelink.entry_presence.notify_fixture') as notify:
            self.assertEqual(entry_presence.expire_presence(later), 1)
            notify.assert_called_once_with(72)
            self.assertEqual(entry_presence.expire_presence(later), 0)

    def test_expired_connections_cannot_renew_readiness_with_late_pongs(self):
        entry_presence.change(72, 'p1', self.token, 'socket-a', 'join', self.now)
        self.assertFalse(entry_presence.change(72, 'p1', self.token, 'socket-a', 'touch',
                                               self.now + datetime.timedelta(seconds=46)))


@override_settings(CHANNEL_LAYERS=MEMORY_LAYERS, GAMELINK_ENABLED=True,
                   GAMELINK_TICKET_SECRET='event-entry-test-only-secret-0123456789',
                   GAMELINK_BACKGAMMON_URL='https://game.example.invalid')
class EventAdmissionTests(TestCase):
    def setUp(self):
        entry_presence._memory.clear()
        entry_verification._memory.clear()
        self.now = timezone.now()
        self.users = [User.objects.create_user(username=f'event-player-{n}') for n in (1, 2)]
        self.tournament = Tournament.objects.create(name='Event entry', starts_at=self.now,
                                                    published=True, podium_spec=[], target_points=5)
        stage = Knockout.objects.create(tournament=self.tournament)
        participants = [Participant.create_for_user(user) for user in self.users]
        for slot, participant in enumerate(participants):
            Participation.objects.create(tournament=self.tournament, participant=participant, slot_id=slot)
        self.fixture = Fixture.objects.create(mode=stage, level=0, player1=participants[0],
                                              player2=participants[1], extras={}, playable_at=self.now)
        self.tokens = [uuid.uuid4().hex for _ in self.users]

    def tearDown(self):
        entry_presence._memory.clear()
        entry_verification._memory.clear()

    def join(self, index):
        with patch('gamelink.entry_waiting.entry_presence.notify_fixture'):
            return state(self.users[index], self.tournament.pk, self.tokens[index], f'socket-{index}', join=True)

    def verify(self, index, challenge):
        with patch('gamelink.entry_waiting.entry_presence.notify_fixture'):
            return state(self.users[index], self.tournament.pk, self.tokens[index], f'socket-{index}',
                         fixture_id=self.fixture.pk, verification_id=challenge)

    def verified_pair(self):
        self.assertFalse(self.join(0)['state']['both_ready'])
        waiting = self.join(1)['state']
        self.assertFalse(waiting['both_ready'])
        challenge = waiting['verification_id']
        self.assertFalse(self.verify(0, challenge)['state']['both_ready'])
        self.assertTrue(self.verify(1, challenge)['state']['both_ready'])
        return challenge

    def test_both_current_screens_must_confirm_and_exit_cancels_unissued_admission(self):
        self.verified_pair()
        link = GameLink.objects.get(fixture=self.fixture)
        self.assertIsNone(link.entry_authorized_at)
        release((self.tournament.pk, self.fixture.pk, 'p1', self.tokens[0]), 'socket-0')
        other = state(self.users[1], self.tournament.pk, self.tokens[1], 'socket-1', fixture_id=self.fixture.pk)
        self.assertFalse(other['state']['both_ready'])
        link.refresh_from_db()
        self.assertFalse(link.entry_authorized_for(self.fixture))

    def test_issued_ticket_preserves_the_other_players_handoff(self):
        challenge = self.verified_pair()
        self.client.force_login(self.users[0])
        url = reverse('gamelink-tournament-start-api', args=[self.tournament.pk])
        response = self.client.post(url, {'attempt_id': self.tokens[0], 'verification_id': challenge},
                                    content_type='application/json', HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 200)
        release((self.tournament.pk, self.fixture.pk, 'p1', self.tokens[0]), 'socket-0')
        self.assertTrue(self.verify(1, challenge)['state']['both_ready'])
        self.client.force_login(self.users[1])
        response = self.client.post(url, {'attempt_id': self.tokens[1], 'verification_id': challenge},
                                    content_type='application/json', HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 200)

    def test_closed_screen_cannot_confirm_from_a_stale_lease(self):
        self.join(0)
        challenge = self.join(1)['state']['verification_id']
        release((self.tournament.pk, self.fixture.pk, 'p1', self.tokens[0]), 'socket-0', disconnected=True)
        self.assertFalse(self.verify(0, challenge)['state']['both_ready'])
        self.assertFalse(self.verify(1, challenge)['state']['both_ready'])
        self.assertFalse(entry_presence.seat_present(self.fixture.pk, 'p1', timezone.now()))

    def test_waiting_indicator_requires_a_current_response_from_the_opponent(self):
        self.join(0)
        waiting = self.join(1)['state']
        self.assertTrue(entry_presence.seat_present(self.fixture.pk, 'p1', timezone.now()))
        self.assertFalse(waiting['opponent']['is_waiting'])
        challenge = waiting['verification_id']
        self.verify(0, challenge)
        result = state(self.users[1], self.tournament.pk, self.tokens[1], 'socket-1',
                       fixture_id=self.fixture.pk)['state']
        self.assertTrue(result['opponent']['is_waiting'])
        self.assertFalse(result['both_ready'])

    def test_expired_confirmation_requires_a_new_round_from_both_screens(self):
        self.join(0)
        challenge = self.join(1)['state']['verification_id']
        self.verify(0, challenge)
        with patch('gamelink.views.timezone.now', return_value=self.now + datetime.timedelta(seconds=6)):
            result = self.verify(1, challenge)['state']
        self.assertFalse(result['both_ready'])
        self.assertNotEqual(result['verification_id'], challenge)
        self.assertIsNone(GameLink.objects.get(fixture=self.fixture).entry_authorized_at)

    def test_old_socket_confirmation_cannot_confirm_the_replacement_owner(self):
        self.join(0)
        challenge = self.join(1)['state']['verification_id']
        with patch('gamelink.entry_waiting.entry_presence.notify_fixture'):
            state(self.users[0], self.tournament.pk, self.tokens[0], 'replacement', join=True,
                  fixture_id=self.fixture.pk)
        self.assertFalse(self.verify(0, challenge)['state']['both_ready'])
        self.assertFalse(self.verify(1, challenge)['state']['both_ready'])
        release((self.tournament.pk, self.fixture.pk, 'p1', self.tokens[0]), 'socket-0', disconnected=True)
        with patch('gamelink.entry_waiting.entry_presence.notify_fixture'):
            result = state(self.users[0], self.tournament.pk, self.tokens[0], 'replacement',
                           fixture_id=self.fixture.pk, verification_id=challenge)
        self.assertTrue(result['state']['both_ready'])

    def test_unconfirmed_tab_leaving_does_not_clear_the_current_round(self):
        challenge = self.verified_pair()
        other = uuid.uuid4().hex
        entry_presence.change(self.fixture.pk, 'p1', other, 'other-tab', 'join')
        release((self.tournament.pk, self.fixture.pk, 'p1', other), 'other-tab')
        self.assertTrue(self.verify(1, challenge)['state']['both_ready'])

    def test_wrong_round_and_wrong_attempt_cannot_mint_the_first_ticket(self):
        challenge = self.verified_pair()
        self.client.force_login(self.users[0])
        url = reverse('gamelink-tournament-start-api', args=[self.tournament.pk])
        for attempt, round_id in ((uuid.uuid4().hex, challenge), (self.tokens[0], uuid.uuid4().hex)):
            response = self.client.post(url, {'attempt_id': attempt, 'verification_id': round_id},
                                        content_type='application/json', HTTP_ACCEPT='application/json')
            self.assertEqual(response.status_code, 412)
        self.assertIsNone(GameLink.objects.get(fixture=self.fixture).entry_authorized_at)

    def test_legacy_http_heartbeats_cannot_authorize_navigation(self):
        url = reverse('gamelink-tournament-ready', args=[self.tournament.pk])
        for user in self.users:
            self.client.force_login(user)
            self.assertFalse(self.client.post(url).json()['both_ready'])
        self.assertIsNone(GameLink.objects.get(fixture=self.fixture).entry_authorized_at)
        self.assertEqual(self.client.post(reverse('gamelink-tournament-start-api',
                                                 args=[self.tournament.pk])).status_code, 412)

    def test_explicit_cancel_before_opponent_join_removes_readiness(self):
        self.join(0)
        release((self.tournament.pk, self.fixture.pk, 'p1', self.tokens[0]), 'socket-0')
        self.assertFalse(self.join(1)['state']['both_ready'])
        link = GameLink.objects.get(fixture=self.fixture)
        self.assertFalse(_fresh_seat(link, 'p1', timezone.now()))
        self.assertIsNone(link.entry_authorized_at)

    def test_old_fixture_and_non_player_cannot_register_presence(self):
        rejected = state(self.users[0], self.tournament.pk, self.tokens[0], 'socket-0',
                         join=True, fixture_id=self.fixture.pk + 1)
        self.assertEqual(rejected['type'], 'entry_rejected')
        outsider = User.objects.create_user(username='event-outsider')
        rejected = state(outsider, self.tournament.pk, uuid.uuid4().hex, 'outsider', join=True)
        self.assertEqual(rejected['type'], 'entry_rejected')
        self.assertFalse(entry_presence.seat_present(self.fixture.pk, 'p1', timezone.now()))


@override_settings(CHANNEL_LAYERS=MEMORY_LAYERS)
class EntrySocketTests(SimpleTestCase):
    def setUp(self):
        versions = patch('frontend.lobby_revisions.current_revisions', return_value={})
        versions.start()
        self.addCleanup(versions.stop)

    async def test_shared_socket_accepts_entry_intent_and_explicit_cancellation(self):
        token = uuid.uuid4().hex
        connection = WebsocketCommunicator(ClubUpdatesConsumer.as_asgi(), '/ws/club/updates/')
        connection.scope['user'] = SimpleNamespace(pk=7, is_authenticated=True)
        self.assertTrue((await connection.connect())[0])
        self.assertEqual(await connection.receive_json_from(), {'type': 'connected', 'revisions': {}})
        payload = {'type': 'entry_state', 'attempt_id': token,
                   'state': {'fixture_id': 72, 'seat': 'p1', 'both_ready': False}}
        with patch('gamelink.entry_waiting.state', return_value=payload) as snapshot:
            await connection.send_json_to({'type': 'entry_join', 'tournament_id': 32, 'attempt_id': token})
            self.assertEqual(await connection.receive_json_from(), payload)
            self.assertEqual(snapshot.call_count, 2)
        with patch('gamelink.entry_waiting.release') as cancel:
            await connection.send_json_to({'type': 'entry_leave', 'attempt_id': token})
            self.assertTrue(await connection.receive_nothing())
            cancel.assert_called_once_with((32, 72, 'p1', token), ANY)
        await connection.disconnect()

    async def test_matching_verification_is_forwarded_but_old_attempt_is_ignored(self):
        token, challenge = uuid.uuid4().hex, uuid.uuid4().hex
        consumer = ClubUpdatesConsumer()
        consumer.entry = (32, 72, 'p1', token)
        consumer.verification_task = None
        consumer.verification_round = None
        consumer.channel_name = 'current-socket'
        consumer.scope = {'user': SimpleNamespace(pk=7)}
        consumer.send_json = AsyncMock()
        payload = {'type': 'entry_state', 'attempt_id': token,
                   'state': {'fixture_id': 72, 'both_ready': True, 'verification_id': challenge}}
        with patch('gamelink.entry_waiting.state', return_value=payload) as snapshot:
            await consumer.receive_json({'type': 'entry_verified', 'attempt_id': uuid.uuid4().hex,
                                         'fixture_id': 72, 'verification_id': challenge})
            snapshot.assert_not_called()
            await consumer.receive_json({'type': 'entry_verified', 'attempt_id': token,
                                         'fixture_id': 72, 'verification_id': challenge})
            snapshot.assert_called_once_with(consumer.scope['user'], 32, token, 'current-socket',
                                             fixture_id=72, verification_id=challenge)
        consumer.send_json.assert_awaited_once_with(payload)

    async def test_verification_deadline_refreshes_state_and_stops_when_no_pair_remains(self):
        token = uuid.uuid4().hex
        consumer = ClubUpdatesConsumer()
        consumer.entry = (32, 72, 'p1', token)
        consumer.verification_task = None
        consumer.verification_round = 'expired-round'
        consumer.channel_name = 'current-socket'
        consumer.scope = {'user': SimpleNamespace(pk=7)}
        consumer.send_json = AsyncMock()
        payload = {'type': 'entry_state', 'attempt_id': token,
                   'state': {'fixture_id': 72, 'both_ready': False, 'verification_id': None}}
        with patch('gamelink.consumers.asyncio.sleep', new_callable=AsyncMock), \
                patch('gamelink.entry_waiting.state', return_value=payload) as snapshot:
            await consumer._verification_expired(consumer.entry, 5)
        snapshot.assert_called_once()
        consumer.send_json.assert_awaited_once_with(payload)
        self.assertIsNone(consumer.verification_round)


@skipUnless(os.environ.get('ENTRY_REDIS_TESTS') == '1', 'Opt in to isolated Redis integration coverage')
@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels_redis.core.RedisChannelLayer'}})
class RedisEntryPresenceTests(SimpleTestCase):
    def setUp(self):
        from django.conf import settings
        prefix = f'entry-test:{uuid.uuid4().hex}:'
        self.prefix_patch = patch('gamelink.entry_presence.PREFIX', prefix)
        self.prefix_patch.start()
        self.addCleanup(self.prefix_patch.stop)
        self.client = entry_presence._client(settings.REDIS_URL)
        self.addCleanup(self.client.delete, *entry_presence._keys(72, 'p1'), entry_presence._due_key())
        self.now = timezone.now()
        self.token = uuid.uuid4().hex

    def test_lua_fences_old_socket_and_expiry_cannot_remove_a_renewed_attempt(self):
        entry_presence.change(72, 'p1', self.token, 'old', 'join', self.now)
        entry_presence.change(72, 'p1', self.token, 'old', 'disconnect', self.now)
        later = self.now + datetime.timedelta(seconds=10)
        entry_presence.change(72, 'p1', self.token, 'new', 'join', later)
        self.assertFalse(entry_presence.change(72, 'p1', self.token, 'old', 'leave', later))
        self.assertEqual(entry_presence.expire_presence(self.now + datetime.timedelta(seconds=16)), 0)
        self.assertTrue(entry_presence.seat_present(72, 'p1', self.now + datetime.timedelta(seconds=30)))
        entry_presence.change(72, 'p1', self.token, 'new', 'leave', later)
        self.assertFalse(entry_presence.seat_present(72, 'p1', later))
        self.assertEqual(self.client.zcard(entry_presence._due_key()), 0)

    def test_dead_redis_lease_expires_once_without_broadcasting_test_fixtures(self):
        entry_presence.change(72, 'p1', self.token, 'old', 'join', self.now)
        later = self.now + datetime.timedelta(seconds=46)
        with patch('gamelink.entry_presence.notify_fixture') as notify:
            self.assertEqual(entry_presence.expire_presence(later), 1)
            notify.assert_called_once_with(72)
            self.assertEqual(entry_presence.expire_presence(later), 0)
