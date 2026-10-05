import asyncio
import logging
import uuid

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db.models import Q

from tournaments.models import Fixture, Tournament
from .entry_presence import group_name

logger = logging.getLogger(__name__)


class ClubUpdatesConsumer(AsyncJsonWebsocketConsumer):
    """One authenticated stream for both shared caches, without private payloads."""

    async def connect(self):
        from frontend.lobby_events import TABLE_GROUP, TOURNAMENT_GROUP, user_group

        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            await self.close(code=4401)
            return
        self.groups_to_join = (TOURNAMENT_GROUP, TABLE_GROUP, user_group(user.pk))
        for group in self.groups_to_join:
            await self.channel_layer.group_add(group, self.channel_name)
        await self.accept()
        from frontend.lobby_revisions import current_revisions
        # Register first, then read versions to cover changes during connection.
        revisions = await database_sync_to_async(current_revisions)(user.pk)
        await self.send_json({'type': 'connected', 'revisions': revisions})
        self.entry = None
        self.pong = None
        self.probe_task = asyncio.create_task(self._probe_connection())

    async def disconnect(self, close_code):
        task = getattr(self, 'probe_task', None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        binding = getattr(self, 'entry', None)
        if binding:
            from .entry_waiting import release
            try:
                await database_sync_to_async(release)(binding, self.channel_name, disconnected=True)
            except Exception:
                logger.exception('event=entry_disconnect_failed fixture_id=%s', binding[1])
            await self.channel_layer.group_discard(group_name(binding[1]), self.channel_name)
        for group in getattr(self, 'groups_to_join', ()):
            await self.channel_layer.group_discard(group, self.channel_name)

    async def club_invalidate(self, event):
        from frontend.lobby_revisions import current
        resource = event['resource']
        # Read the latest committed version, not the possibly delayed event's
        # version. Several writes in one action therefore announce the same value.
        revision = await database_sync_to_async(current)(resource, self.scope['user'].pk)
        await self.send_json({'type': 'invalidate', 'resource': resource, 'revision': revision})

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict):
            return
        if content.get('type') == 'pong':
            if self.pong and not self.pong.done() and content.get('nonce') == self.probe_nonce:
                self.pong.set_result(None)
            return
        token = content.get('attempt_id')
        try:
            if not isinstance(token, str) or len(token) != 32 or uuid.UUID(token).hex != token:
                return
        except ValueError:
            return
        from .entry_waiting import release, state
        if content.get('type') == 'entry_leave':
            if self.entry and self.entry[3] == token:
                binding, self.entry = self.entry, None
                await database_sync_to_async(release)(binding, self.channel_name)
                await self.channel_layer.group_discard(group_name(binding[1]), self.channel_name)
            return
        if content.get('type') != 'entry_join':
            return
        tournament_id = content.get('tournament_id')
        expected = content.get('fixture_id')
        if type(tournament_id) is not int or tournament_id < 1:
            return
        if expected is not None and (type(expected) is not int or expected < 1):
            return
        if self.entry and (self.entry[3] != token or self.entry[0] != tournament_id
                           or (expected is not None and self.entry[1] != expected)):
            await self.send_json({'type': 'entry_rejected', 'attempt_id': token, 'status': 409})
            return
        try:
            message = await database_sync_to_async(state)(
                self.scope['user'], tournament_id, token, self.channel_name,
                join=True, fixture_id=expected,
            )
            if message['type'] == 'entry_state':
                data = message['state']
                self.entry = (tournament_id, data['fixture_id'], data['seat'], token)
                await self.channel_layer.group_add(group_name(data['fixture_id']), self.channel_name)
                # Catch a second player's join between the transaction and group subscription.
                message = await database_sync_to_async(state)(
                    self.scope['user'], tournament_id, token, self.channel_name,
                    fixture_id=data['fixture_id'],
                )
            await self.send_json(message)
        except Exception:
            logger.exception('event=entry_join_failed tournament_id=%s', tournament_id)
            if self.entry:
                binding, self.entry = self.entry, None
                try:
                    await database_sync_to_async(release)(binding, self.channel_name)
                except Exception:
                    logger.exception('event=entry_join_cleanup_failed fixture_id=%s', binding[1])
                await self.channel_layer.group_discard(group_name(binding[1]), self.channel_name)
            await self.send_json({'type': 'entry_rejected', 'attempt_id': token, 'status': 503})

    async def club_entry_changed(self, event):
        if not self.entry or event['fixture_id'] != self.entry[1]:
            return
        from .entry_waiting import state
        tournament_id, fixture_id, _, token = self.entry
        message = await database_sync_to_async(state)(
            self.scope['user'], tournament_id, token, self.channel_name, fixture_id=fixture_id,
        )
        await self.send_json(message)

    async def _probe_connection(self):
        """Small ping/pong renews a Redis lease, with no DB or list refresh."""
        from .entry_presence import change
        try:
            while True:
                await asyncio.sleep(20)
                if not self.entry:
                    continue
                self.probe_nonce = uuid.uuid4().hex
                self.pong = asyncio.get_running_loop().create_future()
                await self.send_json({'type': 'ping', 'nonce': self.probe_nonce})
                await asyncio.wait_for(self.pong, timeout=10)
                binding = self.entry
                if binding:
                    _, fixture_id, seat, token = binding
                    renewed = await sync_to_async(change)(
                        fixture_id, seat, token, self.channel_name, 'touch',
                    )
                    if not renewed and self.entry == binding:
                        await self.send_json({'type': 'entry_rejected', 'attempt_id': token, 'status': 410})
                        self.entry = None
                        await self.channel_layer.group_discard(group_name(fixture_id), self.channel_name)
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.close(code=1011)


@database_sync_to_async
def _player_fixture_for_tournament(user_id, tournament_id):
    try:
        tournament = Tournament.objects.get(pk=tournament_id)
    except Tournament.DoesNotExist:
        return None

    fixtures = (
        Fixture.objects
        .select_related('player1__user', 'player2__user', 'mode__tournament')
        .filter(mode__tournament_id=tournament_id)
        .filter(
            Q(player1__user_id=user_id) |
            Q(player2__user_id=user_id)
        )
        .order_by('-pk')
    )

    fixture = fixtures.first()
    if fixture is None:
        return None

    if fixture.player1 is not None and fixture.player1.user_id == user_id:
        seat = 'p1'
    elif fixture.player2 is not None and fixture.player2.user_id == user_id:
        seat = 'p2'
    else:
        return None

    return fixture.pk, seat


class AdminTournamentProgressConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.tournament_id = self.scope['url_route']['kwargs']['tournament_id']
        self.group_name = f'tournament_live_{self.tournament_id}'

        if not await self._can_view_progress():
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json({'type': 'connected'})

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def tournament_live(self, event):
        await self.send_json(event['payload'])

    @database_sync_to_async
    def _can_view_progress(self):
        user = self.scope.get('user')
        return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


class TournamentEntryConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.tournament_id = int(
            self.scope['url_route']['kwargs']['tournament_id']
        )

        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            await self.close(code=4401)
            return

        resolved = await _player_fixture_for_tournament(
            user.id,
            self.tournament_id,
        )

        if resolved is None:
            await self.close(code=4403)
            return

        self.fixture_id, self.seat = resolved
        self.user_id = user.id

        self.group_name = f'tournament_entry_user_{self.user_id}'

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name,
            )

    async def tournament_entry(self, event):
        await self.send_json(event['payload'])
