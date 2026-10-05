from decimal import Decimal
import json
from types import SimpleNamespace
from unittest.mock import patch

from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser, User
from django.db import transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from gamelink.consumers import ClubUpdatesConsumer
from tournaments.models import HeadToHeadTable, Tournament

from .entry_lifecycle import touch_open_searches
from .lobby_events import TABLE_GROUP, TOURNAMENT_GROUP, user_group
from .lobby_revisions import advance, current, versioned_read, REVISION_HEADER

REVISIONS = {resource: {'generation': '0', 'sequence': 0} for resource in ('tournaments', 'tables')}


class LobbyEventTests(TestCase):
    def setUp(self):
        self.host = User.objects.create(username='host')
        self.guest = User.objects.create(username='guest')
        self.table = HeadToHeadTable.objects.create(
            code='EVT001', game_format='match', mode='match', host=self.host,
            amount=Decimal('100'), fee_percent=Decimal('0'), fee_per_player=Decimal('0'),
        )

    def test_pairing_publishes_after_commit_and_removes_the_public_search(self):
        with patch('frontend.lobby_events._send') as send:
            with self.captureOnCommitCallbacks(execute=True):
                with transaction.atomic():
                    self.table.guest = self.guest
                    self.table.status = 'ready'
                    self.table.save(update_fields=['guest', 'status'])
                    send.assert_not_called()
            send.assert_called_once_with({TABLE_GROUP}, 'tables')

    def test_private_game_changes_only_invalidate_its_players(self):
        self.table.mode = 'friend'
        self.table.guest = self.guest
        self.table.status = 'ready'
        self.table.save()
        with patch('frontend.lobby_events._send') as send:
            with self.captureOnCommitCallbacks(execute=True):
                self.table.status = 'playing'
                self.table.save(update_fields=['status'])
            send.assert_called_once_with({user_group(self.host.pk), user_group(self.guest.pk)}, 'tables')

    def test_presence_heartbeat_and_board_snapshots_do_not_invalidate_lists(self):
        with patch('frontend.lobby_events._send') as send:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(touch_open_searches(self.host.pk), 1)
                self.table.live_snapshot = {'sequence': 1}
                self.table.save(update_fields=['live_snapshot'])
                self.table.refresh_from_db()
                self.table.save()  # A no-op full save also leaves the lists alone.
            send.assert_not_called()

    def test_rollback_does_not_publish_a_change_that_never_committed(self):
        with patch('frontend.lobby_events._send') as send:
            with self.captureOnCommitCallbacks(execute=True):
                with self.assertRaisesMessage(RuntimeError, 'rollback'):
                    with transaction.atomic():
                        self.table.status = 'cancelled'
                        self.table.save(update_fields=['status'])
                        raise RuntimeError('rollback')
            send.assert_not_called()
        self.table.refresh_from_db()
        self.assertEqual(self.table.status, 'open')

    def test_tournament_publication_invalidates_only_the_tournament_cache(self):
        tournament = Tournament.objects.create(name='Upcoming', starts_at=timezone.now(), podium_spec=[])
        with patch('frontend.lobby_events._send') as send:
            with self.captureOnCommitCallbacks(execute=True):
                tournament.published = True
                tournament.save(update_fields=['published'])
            send.assert_called_once_with({TOURNAMENT_GROUP}, 'tournaments')

    def test_versions_roll_back_with_the_changes(self):
        before = current('tables', self.host.pk)
        with self.assertRaisesMessage(RuntimeError, 'rollback'):
            with transaction.atomic():
                self.table.status = 'cancelled'
                self.table.save(update_fields=['status'])
                self.assertNotEqual(current('tables', self.host.pk), before)
                raise RuntimeError('rollback')
        self.assertEqual(current('tables', self.host.pk), before)

    def test_private_revision_does_not_change_other_viewers_versions(self):
        outsider = User.objects.create(username='outsider')
        before = current('tables', outsider.pk)
        host_before = current('tables', self.host.pk)
        advance({user_group(self.host.pk), user_group(self.guest.pk)}, 'tables')
        self.assertEqual(current('tables', outsider.pk), before)
        self.assertNotEqual(current('tables', self.host.pk), host_before)

    def test_read_header_captures_before_serialization_not_after_a_concurrent_change(self):
        from django.http import JsonResponse
        before = current('tournaments', self.host.pk)

        @versioned_read('tournaments')
        def read(request):
            advance({TOURNAMENT_GROUP}, 'tournaments')
            return JsonResponse([], safe=False)

        response = read(SimpleNamespace(method='GET', user=self.host))
        self.assertEqual(json.loads(response[REVISION_HEADER]), before)
        self.assertNotEqual(current('tournaments', self.host.pk), before)


@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class ClubUpdatesConsumerTests(SimpleTestCase):
    def setUp(self):
        versions = patch('frontend.lobby_revisions.current_revisions', return_value=REVISIONS)
        versions.start()
        self.addCleanup(versions.stop)
        revision = patch('frontend.lobby_revisions.current', return_value=REVISIONS['tables'])
        revision.start()
        self.addCleanup(revision.stop)

    def connection(self, user):
        connection = WebsocketCommunicator(ClubUpdatesConsumer.as_asgi(), '/ws/club/updates/')
        connection.scope['user'] = user
        return connection

    async def test_anonymous_connections_are_rejected(self):
        connection = self.connection(AnonymousUser())
        self.assertEqual(await connection.connect(), (False, 4401))
        await connection.disconnect()

    async def test_registered_connection_receives_only_invalidation_metadata(self):
        connection = self.connection(SimpleNamespace(pk=7, is_authenticated=True))
        self.assertTrue((await connection.connect())[0])
        self.assertEqual(await connection.receive_json_from(), {'type': 'connected', 'revisions': REVISIONS})
        for group, resource in ((TOURNAMENT_GROUP, 'tournaments'), (TABLE_GROUP, 'tables'),
                                (user_group(7), 'tables')):
            await get_channel_layer().group_send(group, {'type': 'club.invalidate', 'resource': resource})
            self.assertEqual(await connection.receive_json_from(), {
                'type': 'invalidate', 'resource': resource, 'revision': REVISIONS['tables']})
        await get_channel_layer().group_send(user_group(8), {'type': 'club.invalidate', 'resource': 'tables'})
        self.assertTrue(await connection.receive_nothing())
        await connection.disconnect()
