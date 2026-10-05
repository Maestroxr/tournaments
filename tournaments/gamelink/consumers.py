from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db.models import Q

from tournaments.models import Fixture, Tournament


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
        # This acknowledgement follows group registration. A refresh begun
        # here closes the initial-load/reconnect gap without polling.
        await self.send_json({'type': 'connected'})

    async def disconnect(self, close_code):
        for group in getattr(self, 'groups_to_join', ()):
            await self.channel_layer.group_discard(group, self.channel_name)

    async def club_invalidate(self, event):
        await self.send_json({'type': 'invalidate', 'resource': event['resource']})


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
