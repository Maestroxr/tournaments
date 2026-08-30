"""
Read-only admin for the game link.

Everything here is an audit record. Nothing is editable, because editing any of it would either
forge an audit trail or desynchronize this database from the game server's. The one deliberate
omission is a ticket's token: only its `jti` is ever stored (plan §2, threat 13).
"""

from django.contrib import admin

from . import models


class ReadOnlyModelAdmin(admin.ModelAdmin):

    def get_readonly_fields(self, request, obj = None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj = None):
        return False


@admin.register(models.GameLink)
class GameLinkAdmin(ReadOnlyModelAdmin):

    list_display = ('id', 'fixture', 'provider', 'status', 'external_room_id', 'created_at', 'completed_at')
    list_filter  = ('provider', 'status')

    ordering = ('-created_at',)


@admin.register(models.IssuedTicket)
class IssuedTicketAdmin(ReadOnlyModelAdmin):

    list_display = ('jti', 'game_link', 'user', 'seat', 'issued_at', 'expires_at')
    list_filter  = ('seat',)

    ordering = ('-issued_at',)
