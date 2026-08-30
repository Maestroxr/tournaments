"""
Views for the game link.

``StartGameView`` is the only endpoint a player touches: it authorizes the request, mints a
single-use ticket and hands the player over to the game server. Session 6 of the plan adds the
result callback the game server posts match results back to.
"""

import datetime
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect
from django.utils import timezone
from django.views.generic import View
from tournaments.models import Fixture

from .models import GameLink, IssuedTicket
from .signing import issue_ticket


def playable_seat(user, fixture):
    """
    Return ``(seat, refusal)`` for `user` playing `fixture`.

    On success `seat` is ``'p1'`` or ``'p2'`` and `refusal` is `None`. Otherwise `seat` is `None`
    and `refusal` is the status code a POST should be answered with — 403 when the requester is
    simply not one of the two players, 412 for every other reason, and never a body that would
    tell a prober which guard it tripped over (plan §2, threat 4).

    This is the *only* predicate behind both the "Go to game" button and :class:`StartGameView`,
    so the button and the endpoint cannot disagree about who may play what. The seat in particular
    is derived here, from the fixture, and is never read from the request.
    """

    # 1. The feature has to be switched on. Checked first, and before anything touches the
    #    database, so that the button costs nothing on a deployment that does not use it.
    if not settings.GAMELINK_ENABLED:
        return None, 412

    if user is None or not user.is_authenticated:
        return None, 403

    # 2. The tournament has to be running.
    tournament = fixture.mode.tournament
    if tournament.state != 'active':
        return None, 412

    # 3. The fixture has to be one that is playable right now.
    current_stage = tournament.current_stage
    if current_stage is None or fixture.mode_id != current_stage.id or fixture.level != current_stage.current_level:
        return None, 412

    # 4. A fixture whose result is settled is not replayable.
    if fixture.is_confirmed:
        return None, 412

    # 5. Both seats have to belong to a user of this site; an offline participant cannot be handed
    #    a ticket, and the game server has nobody to seat opposite.
    if fixture.player1 is None or fixture.player2 is None:
        return None, 412
    if fixture.player1.user_id is None or fixture.player2.user_id is None:
        return None, 412

    # 6. Finally, the requester has to be one of the two players, which is what fixes the seat.
    if fixture.player1.user_id == user.id:
        return 'p1', None
    if fixture.player2.user_id == user.id:
        return 'p2', None

    return None, 403


class StartGameView(LoginRequiredMixin, View):
    """
    Mint a ticket for the requesting player and redirect them to the game server.

    POST only, and CSRF-protected. This endpoint mints a bearer credential, so it must not be
    reachable cross-site, from a link in someone else's page, or by a browser prefetch (plan §2,
    threat 14) — which is why it is a form post rather than one of the GET action links used
    elsewhere in this project.
    """

    http_method_names = ['post']

    def post(self, request, pk):
        if not settings.GAMELINK_ENABLED:
            return HttpResponse(status = 412)

        try:
            fixture = Fixture.objects.get(pk = pk)
        except Fixture.DoesNotExist:
            return HttpResponse(status = 412)

        seat, refusal = playable_seat(request.user, fixture)
        if seat is None:
            return HttpResponse(status = refusal)

        # The destination comes from settings and from nowhere else — no host, path or scheme is
        # ever read from the request or from a ticket claim (plan §2, threat 8).
        base_url = settings.GAMELINK_BACKGAMMON_URL.rstrip('/')
        if not base_url:
            return HttpResponse(status = 412)

        now = timezone.now()
        link_ttl = datetime.timedelta(seconds = settings.GAMELINK_LINK_TTL)

        with transaction.atomic():
            game_link, _ = GameLink.objects.get_or_create(
                fixture = fixture,
                defaults = dict(
                    target_points = settings.GAMELINK_TARGET_POINTS,
                    expires_at = now + link_ttl,
                ),
            )

            # The game has been played and its result reported; a fresh ticket must not be able to
            # start a second one over the top of it.
            if game_link.status == 'completed':
                return HttpResponse(status = 412)

            # Both players may take a while to click through, and the second one to arrive must
            # not find the link timed out from under them.
            if game_link.expires_at <= now:
                game_link.expires_at = now + link_ttl
                game_link.save(update_fields = ['expires_at'])

            token, jti = issue_ticket(request.user, fixture, seat, game_link)
            IssuedTicket.objects.create(
                jti        = jti,
                game_link  = game_link,
                user       = request.user,
                seat       = seat,
                expires_at = now + datetime.timedelta(seconds = settings.GAMELINK_TICKET_TTL),
            )

        response = HttpResponseRedirect(f'{base_url}/api/link/enter/?ticket={quote(token)}')

        # The ticket is in the URL, so keep it out of the next request's `Referer` and out of any
        # shared cache (plan §2, threat 5).
        response['Referrer-Policy'] = 'no-referrer'
        response['Cache-Control']   = 'no-store'
        return response
