from django.urls import re_path

from .consumers import AdminTournamentProgressConsumer


websocket_urlpatterns = [
    re_path(
        r'^ws/admin/tournaments/(?P<tournament_id>\d+)/progress/$',
        AdminTournamentProgressConsumer.as_asgi(),
    ),
]
