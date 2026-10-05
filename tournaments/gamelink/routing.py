from channels.security.websocket import AllowedHostsOriginValidator
from django.urls import re_path

from .consumers import (
    AdminTournamentProgressConsumer,
    ClubUpdatesConsumer,
    TournamentEntryConsumer,
)


websocket_urlpatterns = [
    re_path(r'^ws/club/updates/$', AllowedHostsOriginValidator(ClubUpdatesConsumer.as_asgi())),
    re_path(
        r'^ws/admin/tournaments/(?P<tournament_id>\d+)/progress/$',
        AdminTournamentProgressConsumer.as_asgi(),
    ),
    re_path(
        r'^ws/tournaments/(?P<tournament_id>\d+)/entry/$',
        TournamentEntryConsumer.as_asgi(),
    ),
]
