from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer


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
