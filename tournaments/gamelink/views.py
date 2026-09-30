"""
Views for the game link.

Two endpoints, facing in opposite directions and authenticated in completely different ways.

``StartGameView`` faces the player: it authorizes a logged-in request, mints a single-use ticket
and hands the player over to the game server. Session authority, CSRF protection, the lot.

``ResultCallbackView`` faces the game server: it accepts the match result that comes back, and its
*only* authentication is an HMAC over the raw request body. It has no session authority at all and
must never acquire any — see the note on the class itself.
"""

import datetime
import json
import logging
import math
import re
import time
from decimal import Decimal
from urllib.parse import quote

from asgiref.sync import async_to_sync
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.core.exceptions import RequestDataTooBig, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View
from channels.layers import get_channel_layer
from tournaments.models import Fixture, FixtureAudit, HeadToHeadTable, RatingResult, Tournament, WalletTransaction

from .models import GameLink, IssuedTicket, SeenNonce
from .signing import SEATS, issue_direct_play_ticket, issue_ticket, redact, verify_result_signature

logger = logging.getLogger(__name__)


class StartDirectPlayView(LoginRequiredMixin, View):
    """Issue a short-lived game ticket for either player at a funded direct-play table."""

    http_method_names = ['post']

    def post(self, request, code):
        from frontend.entry_lifecycle import expire_unstarted_tables
        expire_unstarted_tables(user_id=request.user.pk)
        with transaction.atomic():
            return self._start(request, code)

    def _start(self, request, code):
        if not settings.GAMELINK_ENABLED:
            return HttpResponse(status=412)
        base_url = getattr(settings, 'GAMELINK_BACKGAMMON_URL', '').rstrip('/')
        if not base_url:
            return HttpResponse(status=412)
        try:
            table = HeadToHeadTable.objects.select_for_update().get(code=code.upper())
        except HeadToHeadTable.DoesNotExist:
            return HttpResponse(status=404)
        if table.status not in (HeadToHeadTable.STATUS_READY, HeadToHeadTable.STATUS_PLAYING):
            return HttpResponse(status=412)
        if request.user.id == table.host_id:
            seat = 'p1'
        elif request.user.id == table.guest_id:
            seat = 'p2'
        else:
            return HttpResponse(status=403)

        try:
            token, _ = issue_direct_play_ticket(request.user, table, seat)
        except ValueError:
            return HttpResponse(status=412)

        if request.user.id == table.host_id:
            from frontend.push import queue_host_entered_push
            queue_host_entered_push(table)
        else:
            from frontend.push import queue_guest_entered_push
            queue_guest_entered_push(table)
        response = HttpResponseRedirect(
            f'{base_url}/api/link/enter/?ticket={quote(token)}')
        response['Referrer-Policy'] = 'no-referrer'
        response['Cache-Control'] = 'no-store'
        return response


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
    if current_stage is None or fixture.mode_id != current_stage.id:
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


def _playable_refusal_reason(user, fixture):
    """Return a development-only label for the first failed playability guard."""
    if not settings.GAMELINK_ENABLED:
        return 'disabled'
    if user is None or not user.is_authenticated:
        return 'not_authenticated'

    tournament = fixture.mode.tournament
    if tournament.state != 'active':
        return 'tournament_not_active'
    current_stage = tournament.current_stage
    if current_stage is None or fixture.mode_id != current_stage.id:
        return 'fixture_not_in_current_stage'
    if fixture.is_confirmed:
        return 'fixture_already_confirmed'
    if fixture.player1 is None or fixture.player2 is None:
        return 'fixture_missing_player'
    if fixture.player1.user_id is None or fixture.player2.user_id is None:
        return 'fixture_player_has_no_user'
    return 'user_not_in_fixture'


def _start_refusal(status, reason):
    """Keep production refusals opaque while making local integration debugging practical."""
    response = HttpResponse(status=status)
    if settings.DEBUG:
        response['X-GameLink-Debug'] = reason
    return response


class StartGameView(LoginRequiredMixin, View):
    """
    Mint a ticket for the requesting player and redirect them to the game server.

    POST only, and CSRF-protected. This endpoint mints a bearer credential, so it must not be
    reachable cross-site, from a link in someone else's page, or by a browser prefetch (plan §2,
    threat 14) — which is why it is a form post rather than one of the GET action links used
    elsewhere in this project.
    """

    http_method_names = ['post']

    @transaction.atomic
    def post(self, request, pk):
        if not settings.GAMELINK_ENABLED:
            logger.warning(
                'gamelink start refused: disabled [fixture=%s user=%s]', pk, request.user.pk)
            return _start_refusal(412, 'disabled')

        try:
            fixture = Fixture.objects.get(pk=pk)
            Tournament.objects.select_for_update().get(pk=fixture.mode.tournament_id)
            fixture = Fixture.objects.select_for_update().get(pk=pk)
        except Fixture.DoesNotExist:
            logger.warning(
                'gamelink start refused: fixture does not exist [fixture=%s user=%s]', pk, request.user.pk)
            return _start_refusal(412, 'fixture_does_not_exist')

        seat, refusal = playable_seat(request.user, fixture)
        if seat is None:
            tournament = fixture.mode.tournament
            reason = _playable_refusal_reason(request.user, fixture)
            logger.warning(
                'gamelink start refused: %s '
                '[fixture=%s user=%s tournament_state=%s fixture_stage=%s current_stage=%s '
                'fixture_level=%s current_level=%s confirmed=%s p1_user=%s p2_user=%s]',
                reason, fixture.pk, request.user.pk, tournament.state, fixture.mode_id,
                getattr(tournament.current_stage, 'id', None), fixture.level,
                getattr(tournament.current_stage, 'current_level',
                        None), fixture.is_confirmed,
                fixture.player1.user_id if fixture.player1 else None,
                fixture.player2.user_id if fixture.player2 else None,
            )
            return _start_refusal(refusal, reason)

        return _issue_game_ticket(request, fixture, seat)


class StartTournamentGameView(LoginRequiredMixin, View):
    """Start the signed-in player's one current fixture in ``pk``.

    The Vue client deliberately posts a tournament id rather than a fixture id.  A player can
    have playable fixtures in more than one active tournament, and choosing a fixture in global
    client state previously allowed two opponents to enter different rooms.  Resolving the
    fixture here, under the tournament lock, makes the tournament and the signed-in identity the
    authority for both the fixture and the seat.
    """

    http_method_names = ['post']

    @transaction.atomic
    def post(self, request, pk):
        if not settings.GAMELINK_ENABLED:
            logger.warning(
                'gamelink tournament start refused: disabled [tournament=%s user=%s]',
                pk, request.user.pk)
            return _start_refusal(412, 'disabled')

        tournament, fixture, seat, refusal = _resolve_current_fixture(request, pk)
        if refusal is not None:
            status, reason, detail = refusal
            if reason == 'tournament_does_not_exist':
                logger.warning(
                    'gamelink tournament start refused: tournament does not exist '
                    '[tournament=%s user=%s]', pk, request.user.pk)
            elif reason == 'tournament_not_active':
                logger.warning(
                    'gamelink tournament start refused: tournament not active '
                    '[tournament=%s user=%s]', pk, request.user.pk)
            else:
                logger.error(
                    'gamelink tournament start refused: %s '
                    '[tournament=%s user=%s fixtures=%s]',
                    reason, pk, request.user.pk, detail)
            return _start_refusal(status, reason)

        return _issue_game_ticket(request, fixture, seat)


def _resolve_current_fixture(request, pk):
    """
    Resolve the signed-in user's exactly-one current playable fixture in tournament ``pk``.

    Returns ``(tournament, fixture, seat, refusal)``. On success ``refusal`` is `None` and
    ``fixture``/``seat`` are authoritative — never trust a fixture id supplied by the client.
    Otherwise ``refusal`` is a ``(status, reason, detail)`` triple the caller turns into a
    refusal response. Must run inside a transaction: the tournament and fixture rows are locked.
    """
    try:
        tournament = Tournament.objects.select_for_update().get(pk=pk)
    except Tournament.DoesNotExist:
        return None, None, None, (412, 'tournament_does_not_exist', None)

    current_stage = tournament.current_stage
    if tournament.state != 'active' or current_stage is None:
        return tournament, None, None, (412, 'tournament_not_active', None)

    fixtures = list(
        Fixture.objects.select_for_update().select_related(
            'mode__tournament', 'player1__user', 'player2__user')
        .filter(
            mode_id=current_stage.pk,
        )
        .filter(Q(player1__user=request.user) | Q(player2__user=request.user))
        .order_by('pk')
    )
    playable = []
    for fixture in fixtures:
        seat, _ = playable_seat(request.user, fixture)
        if seat is not None:
            playable.append((fixture, seat))

    if len(playable) != 1:
        reason = 'current_fixture_not_found' if not playable else 'ambiguous_current_fixtures'
        return tournament, None, None, (412, reason, [fixture.pk for fixture, _ in playable])

    fixture, seat = playable[0]
    return tournament, fixture, seat, None


# How long one readiness heartbeat counts as fresh. Both seats must have heartbeated inside
# this window before tickets are issued; each browser re-posts while it waits.
READY_FRESHNESS_SECONDS = 15

# Absolute entry window for a tournament fixture, measured from the fixture's
# own playable moment — never from heartbeats, link creation, or request time.
TOURNAMENT_ENTRY_WINDOW = datetime.timedelta(minutes=10)


def _entry_deadline_fields(fixture, now):
    """
    Return ``(entry_deadline, remaining_seconds)`` for `fixture`.

    The deadline is derived only from ``fixture.playable_at``. When it is
    unexpectedly missing, both values stay `None` so the gap remains visible
    instead of being silently replaced by the wrong clock. The remaining time
    never goes negative; an expired deadline reports ``0`` without resolving
    anything — no-show resolution happens elsewhere.
    """
    if fixture.playable_at is None:
        return None, None
    entry_deadline = fixture.playable_at + TOURNAMENT_ENTRY_WINDOW
    remaining_seconds = max(
        0,
        math.ceil((entry_deadline - now).total_seconds()),
    )
    return entry_deadline, remaining_seconds


def _fresh_seat(game_link, seat, now):
    """Whether `seat` declared readiness inside the freshness window."""
    ready_at = game_link.p1_ready_at if seat == 'p1' else game_link.p2_ready_at
    if ready_at is None:
        return False
    return ready_at >= now - datetime.timedelta(seconds=READY_FRESHNESS_SECONDS)


def _no_show_winner_seat(fixture):
    """
    Winner seat of an opponent-no-show resolution, or `None` when `fixture`
    was not resolved as a no-show walkover.
    """
    if not fixture.admin_result or fixture.admin_winner_id is None:
        return None
    if not FixtureAudit.objects.filter(fixture=fixture, action='opponent_no_show').exists():
        return None
    if fixture.admin_winner_id == fixture.player1_id:
        return 'p1'
    if fixture.admin_winner_id == fixture.player2_id:
        return 'p2'
    return None


def _is_double_no_show(fixture):
    """Whether `fixture` was resolved as a double no-show (no winner)."""
    if getattr(fixture, 'admin_result', None) != 'double_no_show':
        return False
    return FixtureAudit.objects.filter(fixture=fixture, action='double_no_show').exists()


def _resolve_double_no_show_locked(fixture, locked_link, now):
    """Resolve an expired fixture where neither player entered. Caller holds locks.

    `locked_link` is the re-locked GameLink or None when no link row exists.
    Idempotent: returns True when already double-resolved, False when the
    double case does not apply. Never invents a score or winner.
    """
    if fixture.is_confirmed or fixture.admin_result:
        return _is_double_no_show(fixture)
    if fixture.playable_at is None:
        return False
    if fixture.player1_id is None or fixture.player2_id is None:
        return False
    entry_deadline, _ = _entry_deadline_fields(fixture, now)
    if entry_deadline is None or now < entry_deadline:
        return False
    if locked_link is not None:
        if locked_link.status != 'pending':
            return False
        if _fresh_seat(locked_link, 'p1', now) or _fresh_seat(locked_link, 'p2', now):
            return False
    fixture.admin_result = 'double_no_show'
    fixture.admin_winner = None
    fixture.admin_resolved_at = now
    fixture.save(update_fields=['admin_result', 'admin_winner', 'admin_resolved_at'])
    FixtureAudit.objects.create(
        fixture=fixture,
        action='double_no_show',
        reason='Neither player entered before the entry deadline.',
        before={'score': [fixture.score1, fixture.score2], 'admin_result': ''},
        after={'admin_result': 'double_no_show'},
    )
    if locked_link is not None:
        locked_link.status = 'cancelled'
        locked_link.save(update_fields=['status'])
    fixture.mode.tournament.update_state()
    return True


def _try_resolve_no_show(fixture, game_link, now):
    """
    Resolve an expired pending fixture as an opponent-no-show walkover.

    Call only from inside the ready transaction: the tournament and fixture
    rows are already locked, and the link row is re-locked here so concurrent
    heartbeat/timeout requests serialize. Readiness is recomputed from the
    locked link, so a lately committed opponent heartbeat still wins the
    normal ``both_ready`` flow. Returns the winner seat, or `None` when no
    walkover applies (deadline not reached, both or neither present, link not
    pending, or fixture already resolved).
    """
    if fixture.playable_at is None:
        return None
    entry_deadline, _ = _entry_deadline_fields(fixture, now)
    if entry_deadline is None or now < entry_deadline:
        return None
    if fixture.is_confirmed or fixture.admin_result:
        if _is_double_no_show(fixture):
            return 'double_no_show'
        return _no_show_winner_seat(fixture)
    if game_link.status != 'pending':
        return None
    locked_link = GameLink.objects.select_for_update().get(pk=game_link.pk)
    p1_here = _fresh_seat(locked_link, 'p1', now)
    p2_here = _fresh_seat(locked_link, 'p2', now)
    if p1_here == p2_here:
        if not p1_here and not p2_here:
            # Neither entered before the deadline: eliminate both.
            if _resolve_double_no_show_locked(fixture, locked_link, now):
                return 'double_no_show'
            return None
        # Both entered — the normal both_ready flow owns that race.
        # Never award or invent a winner here.
        return None
    winner_seat = 'p1' if p1_here else 'p2'
    winner = fixture.player1 if winner_seat == 'p1' else fixture.player2
    fixture.admin_result = 'advance'
    fixture.admin_winner = winner
    fixture.admin_resolved_at = now
    fixture.save(update_fields=['admin_result', 'admin_winner', 'admin_resolved_at'])
    FixtureAudit.objects.create(
        fixture=fixture,
        action='opponent_no_show',
        reason=f'{winner_seat} entered; the opponent never entered before the entry deadline.',
        before={'score': [fixture.score1, fixture.score2], 'admin_result': ''},
        after={'admin_result': 'advance', 'winner_seat': winner_seat,
               'winner_participant_id': winner.pk},
    )
    # Terminal for first entries: no ticket can be issued off this link again.
    locked_link.status = 'cancelled'
    locked_link.save(update_fields=['status'])
    # Existing tournament flow: mark resolved, confirm via admin_result, and
    # propagate the winner through the bracket.
    fixture.mode.tournament.update_state()
    return winner_seat


def _no_show_terminal_response(fixture, seat, winner_seat, now):
    """Terminal no-show state for a player whose fixture already ended."""
    entry_deadline, _ = _entry_deadline_fields(fixture, now)
    game_link = GameLink.objects.filter(fixture_id=fixture.pk).first()
    if game_link is not None:
        opponent = _opponent_info(fixture, seat, game_link, now)
    elif fixture.player1 is not None and fixture.player2 is not None:
        opponent_user = fixture.player2.user if seat == 'p1' else fixture.player1.user
        opponent = {'username': opponent_user.username, 'is_waiting': False}
    else:
        opponent = {'username': '', 'is_waiting': False}
    return JsonResponse({
        'fixture_id': fixture.pk,
        'seat': seat,
        'both_ready': False,
        'entry_status': 'won_by_no_show' if winner_seat == seat else 'lost_by_no_show',
        'reason': 'opponent_no_show',
        'winner_seat': winner_seat,
        'entry_deadline': entry_deadline,
        'remaining_seconds': 0,
        'opponent': opponent,
    })


def _double_no_show_terminal_response(fixture, seat, now):
    """Terminal double-no-show state: fixture ended with no winner."""
    entry_deadline, _ = _entry_deadline_fields(fixture, now)
    game_link = GameLink.objects.filter(fixture_id=fixture.pk).first()
    if game_link is not None:
        try:
            opponent = _opponent_info(fixture, seat, game_link, now)
        except Exception:
            opponent = {'username': '', 'is_waiting': False}
    else:
        opponent = {'username': '', 'is_waiting': False}
    return JsonResponse({
        'fixture_id': fixture.pk,
        'seat': seat,
        'both_ready': False,
        'entry_status': 'double_no_show',
        'reason': 'double_no_show',
        'winner_seat': None,
        'entry_deadline': entry_deadline,
        'remaining_seconds': 0,
        'opponent': opponent,
    })


def _double_no_show_after_resolution(request, tournament_pk):
    """Terminal double-no-show state for a player with no playable fixture."""
    try:
        Tournament.objects.select_for_update().get(pk=tournament_pk)
    except Tournament.DoesNotExist:
        return None
    candidates = (Fixture.objects.select_related('mode__tournament', 'player1__user', 'player2__user')
        .filter(mode__tournament_id=tournament_pk, admin_result='double_no_show')
        .filter(Q(player1__user=request.user) | Q(player2__user=request.user))
        .order_by('-pk'))
    now = timezone.now()
    for fixture in candidates:
        if not _is_double_no_show(fixture):
            continue
        if fixture.player1 is not None and fixture.player1.user_id == request.user.id:
            seat = 'p1'
        elif fixture.player2 is not None and fixture.player2.user_id == request.user.id:
            seat = 'p2'
        else:
            continue
        return _double_no_show_terminal_response(fixture, seat, now)
    return None


def _no_show_after_resolution(request, tournament_pk):
    """
    Terminal no-show state for a player whose fixture already ended and who
    therefore no longer resolves to a playable fixture.

    Returns a JsonResponse, or `None` when no no-show resolution applies (the
    caller then returns the original refusal, reopening nothing).
    """
    try:
        Tournament.objects.select_for_update().get(pk=tournament_pk)
    except Tournament.DoesNotExist:
        return None
    candidates = (Fixture.objects.select_related('mode__tournament', 'player1__user', 'player2__user')
        .filter(mode__tournament_id=tournament_pk, admin_result='advance')
        .filter(Q(player1__user=request.user) | Q(player2__user=request.user))
        .order_by('-pk'))
    now = timezone.now()
    for fixture in candidates:
        winner_seat = _no_show_winner_seat(fixture)
        if winner_seat is None:
            continue
        if fixture.player1 is not None and fixture.player1.user_id == request.user.id:
            seat = 'p1'
        elif fixture.player2 is not None and fixture.player2.user_id == request.user.id:
            seat = 'p2'
        else:
            continue
        return _no_show_terminal_response(fixture, seat, winner_seat, now)
    return _double_no_show_after_resolution(request, tournament_pk)


def _readiness_fresh(game_link, now):
    """True only when both seats heartbeated no earlier than the freshness window."""
    if game_link.p1_ready_at is None or game_link.p2_ready_at is None:
        return False
    cutoff = now - datetime.timedelta(seconds=READY_FRESHNESS_SECONDS)
    return game_link.p1_ready_at >= cutoff and game_link.p2_ready_at >= cutoff


def _has_prior_entry(game_link, user):
    """
    True when this backend already issued `user` a ticket for `game_link`.

    An issued ticket is the tournaments side's authoritative evidence that this player
    entered the linked room before, which is what distinguishes re-entry into a `playing`
    link from a first entry that must still go through readiness.
    """
    return IssuedTicket.objects.filter(game_link=game_link, user=user).exists()


def _opponent_info(fixture, seat, game_link, now):
    """
    Freshness card for the caller's authoritative opponent in this fixture.

    Only ever called after `_resolve_current_fixture` authorized the caller, so the
    opponent is always the other seat's user — never an id taken from the request.
    """
    if seat == 'p1':
        opponent_user = fixture.player2.user
        opponent_ready_at = game_link.p2_ready_at
    else:
        opponent_user = fixture.player1.user
        opponent_ready_at = game_link.p1_ready_at
    cutoff = now - datetime.timedelta(seconds=READY_FRESHNESS_SECONDS)
    return {
        'username': opponent_user.username,
        'is_waiting': opponent_ready_at is not None and opponent_ready_at >= cutoff,
    }


def resolve_expired_double_no_shows_for_tournament(tournament_id, now, exclude_fixture_id=None):
    """Opportunistically resolve silent expired fixtures with zero readiness.

    Runs inside the caller's transaction via savepoints; one fixture failure
    never breaks the heartbeat. Returns the number resolved.
    """
    from django.db import transaction as db_transaction

    cutoff = now - TOURNAMENT_ENTRY_WINDOW
    candidate_ids = list(
        Fixture.objects.filter(
            mode__tournament_id=tournament_id,
            playable_at__lte=cutoff,
            player1__isnull=False,
            player2__isnull=False,
            admin_result='',
            score1__isnull=True,
            score2__isnull=True,
        ).values_list('pk', flat=True)
    )
    resolved = 0
    for fixture_id in candidate_ids:
        if exclude_fixture_id is not None and fixture_id == exclude_fixture_id:
            continue
        try:
            with db_transaction.atomic():
                fixture = Fixture.objects.select_for_update().get(pk=fixture_id)
                if fixture.is_confirmed or fixture.admin_result:
                    continue
                if fixture.playable_at is None:
                    continue
                entry_deadline, _ = _entry_deadline_fields(fixture, now)
                if entry_deadline is None or now < entry_deadline:
                    continue
                link = GameLink.objects.select_for_update().filter(fixture_id=fixture.pk).first()
                if link is not None and link.status != 'pending':
                    continue
                if _resolve_double_no_show_locked(fixture, link, now):
                    resolved += 1
        except Exception:
            continue
    return resolved


class TournamentGameReadyView(LoginRequiredMixin, View):
    """
    Record one player's readiness heartbeat for their current tournament fixture.

    POST only, session-authenticated and CSRF-protected like the play endpoint. Each browser
    posts roughly every two seconds while the loading overlay waits; `both_ready` turns true
    once both seats have a fresh heartbeat, and only then does the client submit the game
    entry form. There is no countdown, no cancellation and no entry-timeout behavior here —
    waiting simply continues until both players are ready.
    """

    http_method_names = ['post']

    @transaction.atomic
    def post(self, request, pk):
        if not settings.GAMELINK_ENABLED:
            return _start_refusal(412, 'disabled')

        _, fixture, seat, refusal = _resolve_current_fixture(request, pk)
        if refusal is not None:
            terminal = _no_show_after_resolution(request, pk)
            if terminal is not None:
                return terminal
            status, reason, _ = refusal
            return _start_refusal(status, reason)

        now = timezone.now()
        game_link, _ = GameLink.objects.get_or_create(
            fixture=fixture,
            defaults=dict(
                target_points=fixture.mode.tournament.target_points,
                doubling_enabled=fixture.mode.tournament.doubling_enabled,
                expires_at=now + datetime.timedelta(seconds=settings.GAMELINK_LINK_TTL),
            ),
        )

        if game_link.status in ('completed', 'cancelled', 'failed'):
            return _start_refusal(412, 'link_terminal')

        if game_link.status == 'playing' and _has_prior_entry(game_link, request.user):
            # Already underway and this player entered before: straight back in. Anyone
            # else falls through to the readiness check below instead of bypassing it.
            entry_deadline, remaining_seconds = _entry_deadline_fields(fixture, now)
            return JsonResponse({
                'fixture_id': fixture.pk,
                'seat': seat,
                'both_ready': True,
                'entry_status': 'ready',
                'entry_deadline': entry_deadline,
                'remaining_seconds': remaining_seconds,
                'opponent': _opponent_info(fixture, seat, game_link, now),
            })

        field = 'p1_ready_at' if seat == 'p1' else 'p2_ready_at'
        previous_ready_at = getattr(game_link, field)
        cutoff = now - datetime.timedelta(seconds=READY_FRESHNESS_SECONDS)
        new_waiting_attempt = previous_ready_at is None or previous_ready_at < cutoff
        if seat == 'p1':
            opponent_user_id = fixture.player2.user_id
        else:
            opponent_user_id = fixture.player1.user_id
        setattr(game_link, field, now)
        game_link.save(update_fields=[field])
        # Re-read so a heartbeat the opponent committed while this request was in flight counts.
        game_link.refresh_from_db()
        if (new_waiting_attempt and opponent_user_id is not None
                and not _readiness_fresh(game_link, now)):
            from frontend.push import notify_tournament_opponent_waiting
            transaction.on_commit(
                lambda fixture=fixture, opponent_user_id=opponent_user_id:
                    notify_tournament_opponent_waiting(
                        fixture,
                        recipient_id=opponent_user_id,
                    )
            )
        both_ready = _readiness_fresh(game_link, now)
        if both_ready:
            entry_deadline, remaining_seconds = _entry_deadline_fields(fixture, now)
            return JsonResponse({
                'fixture_id': fixture.pk,
                'seat': seat,
                'both_ready': both_ready,
                'entry_status': 'ready',
                'entry_deadline': entry_deadline,
                'remaining_seconds': remaining_seconds,
                'opponent': _opponent_info(fixture, seat, game_link, now),
            })
        winner_seat = _try_resolve_no_show(fixture, game_link, now)
        if winner_seat == 'double_no_show':
            return _double_no_show_terminal_response(fixture, seat, now)
        if winner_seat is not None:
            return _no_show_terminal_response(fixture, seat, winner_seat, now)
        try:
            resolve_expired_double_no_shows_for_tournament(
                fixture.mode.tournament_id, now, exclude_fixture_id=fixture.pk,
            )
        except Exception:
            pass
        entry_deadline, remaining_seconds = _entry_deadline_fields(fixture, now)
        return JsonResponse({
            'fixture_id': fixture.pk,
            'seat': seat,
            'both_ready': both_ready,
            'entry_status': 'waiting',
            'entry_deadline': entry_deadline,
            'remaining_seconds': remaining_seconds,
            'opponent': _opponent_info(fixture, seat, game_link, now),
        })


def _issue_game_ticket(request, fixture, seat):
    """Mint and record a ticket after the caller has locked and authorized ``fixture``."""
    # The destination comes from settings and from nowhere else — no host, path or scheme is
    # ever read from the request or from a ticket claim (plan §2, threat 8).
    base_url = settings.GAMELINK_BACKGAMMON_URL.rstrip('/')
    if not base_url:
        logger.warning('gamelink start refused: GAMELINK_BACKGAMMON_URL is empty [fixture=%s user=%s]',
                       fixture.pk, request.user.pk)
        return _start_refusal(412, 'backgammon_url_is_empty')

    now = timezone.now()
    link_ttl = datetime.timedelta(seconds=settings.GAMELINK_LINK_TTL)

    with transaction.atomic():
        game_link, _ = GameLink.objects.get_or_create(
            fixture=fixture,
            defaults=dict(
                target_points=fixture.mode.tournament.target_points,
                doubling_enabled=fixture.mode.tournament.doubling_enabled,
                expires_at=now + link_ttl,
            ),
        )

        # Readiness gate for real tournament fixtures. `playing` allows a ticket only as a
        # re-entry for a player this backend already issued a ticket to; `pending` starts
        # only once both seats have sent a fresh readiness heartbeat (see
        # TournamentGameReadyView). Anything else — a link that is completed, cancelled or
        # failed, a first entry into a `playing` link, or a pending link nobody is waiting
        # on — refuses, so posting straight at a play endpoint cannot bypass readiness.
        if game_link.status == 'playing' and _has_prior_entry(game_link, request.user):
            pass
        elif game_link.status == 'pending' and _readiness_fresh(game_link, now):
            pass
        else:
            return HttpResponse(status=412)

        update_fields = []
        if game_link.target_points != fixture.mode.tournament.target_points:
            game_link.target_points = fixture.mode.tournament.target_points
            update_fields.append('target_points')
        if game_link.doubling_enabled != fixture.mode.tournament.doubling_enabled:
            game_link.doubling_enabled = fixture.mode.tournament.doubling_enabled
            update_fields.append('doubling_enabled')

        # Both players may take a while to click through, and the second one to arrive must not
        # find the link timed out from under them.
        if game_link.expires_at <= now:
            game_link.expires_at = now + link_ttl
            update_fields.append('expires_at')

        if update_fields:
            game_link.save(update_fields=update_fields)

        token, jti = issue_ticket(request.user, fixture, seat, game_link)
        IssuedTicket.objects.create(
            jti=jti,
            game_link=game_link,
            user=request.user,
            seat=seat,
            expires_at=now +
            datetime.timedelta(seconds=settings.GAMELINK_TICKET_TTL),
        )

    response = HttpResponseRedirect(
        f'{base_url}/api/link/enter/?ticket={quote(token)}')

    # The ticket is in the URL, so keep it out of the next request's `Referer` and out of any
    # shared cache (plan §2, threat 5).
    response['Referrer-Policy'] = 'no-referrer'
    response['Cache-Control'] = 'no-store'
    return response


# The result callback (backgammon -> tournaments)
# -----------------------------------------------

RESULT_VERSION = 1

STATUS_COMPLETED = 'completed'
STATUS_CANCELLED = 'cancelled'
REPORTABLE_STATUSES = (STATUS_COMPLETED, STATUS_CANCELLED)

# The states a link may still receive a result in. Anything else is either terminal — and handled
# by the idempotency branch above it — or a link this server has already given up on (plan §2,
# threat 3).
OPEN_LINK_STATUSES = ('pending', 'playing')

# `Fixture.score1` and `score2` are `PositiveSmallIntegerField`, so this is the whole range they
# can hold. A score outside it is a malformed message rather than a disagreement about a fixture,
# which is why it is caught here as a 400 and not later as a 409.
MAX_SCORE = 32767

_TIMESTAMP_PATTERN = re.compile(r'\A[0-9]{1,20}\Z')
_NONCE_PATTERN = re.compile(r'\A[A-Za-z0-9._:-]{1,64}\Z')

# Authentication failures remain generic. After signature and payload validation, result
# conflicts include a stable code so the trusted sender can explain and stop a blocked delivery.
_ERRORS = {
    400: 'bad_request',
    401: 'unauthorized',
    403: 'forbidden',
    404: 'not_found',
    409: 'conflict',
    413: 'payload_too_large',
}


@method_decorator(csrf_exempt, name='dispatch')
class ResultCallbackView(View):
    """
    Record the result of an externally played game.

    **On the CSRF exemption.** It is safe here — and only here — because this view has no session
    or cookie authority whatsoever. Its sole authentication is a detached HMAC over the exact
    request body (plan §2, threat 15), computed by a peer that holds a shared secret no browser
    ever sees. CSRF protects endpoints that act on the strength of an ambient credential; this one
    has none to be confused about. **It must never read `request.user`**, and a test asserts that a
    session cookie riding along on the request changes nothing.

    The checks run cheapest-first so that an unauthenticated flood is turned away before it can
    cost a database query (plan §2, threat 16): size, then headers, then the clock, then the
    signature — and only after all four does anything touch the database.
    """

    http_method_names = ['post']

    def post(self, request):
        # 1. A deployment that does not link games does not admit that this endpoint exists.
        if not settings.GAMELINK_ENABLED:
            return _reject(request, 404, 'the game link is disabled')

        # 2. Size, from the header, before the body is pulled into memory.
        if _declared_length(request) > settings.GAMELINK_MAX_BODY:
            return _reject(request, 413, 'declared body length exceeds GAMELINK_MAX_BODY')

        try:
            raw = request.body
        except RequestDataTooBig:
            return _reject(request, 413, 'body exceeds DATA_UPLOAD_MAX_MEMORY_SIZE')

        # A `Content-Length` that understates the body, or none at all, does not get to skip the
        # cap. Cheap: the body is already in memory by now either way.
        if len(raw) > settings.GAMELINK_MAX_BODY:
            return _reject(request, 413, 'body exceeds GAMELINK_MAX_BODY')

        # 3. The three headers that carry the authentication. `X-Gamelink-Issuer` is read for the
        #    log only: it is outside the signed material, so anyone can write anything in it and
        #    gating on it would be theatre. Cross-environment confusion is kept out by giving each
        #    environment its own secret (plan §2, threat 7), not by this header.
        timestamp = request.headers.get('X-Gamelink-Timestamp', '')
        nonce = request.headers.get('X-Gamelink-Nonce', '')
        signature = request.headers.get('X-Gamelink-Signature', '')

        if not _TIMESTAMP_PATTERN.match(timestamp):
            return _reject(request, 401, 'missing or malformed X-Gamelink-Timestamp')
        if not _NONCE_PATTERN.match(nonce):
            return _reject(request, 401, 'missing or malformed X-Gamelink-Nonce')
        if not signature:
            return _reject(request, 401, 'missing X-Gamelink-Signature')

        # 4. The clock. The window is the only thing bounding how long a captured message stays
        #    replayable against a nonce table that gets purged (plan §8).
        if abs(int(time.time()) - int(timestamp)) > settings.GAMELINK_CLOCK_SKEW:
            return _reject(request, 401, 'timestamp is outside GAMELINK_CLOCK_SKEW')

        # 5. The signature, over the raw bytes and before any database access at all. Note the
        #    timestamp goes in as the string that arrived: it is what the sender signed, and
        #    normalising it here would break every message whose timestamp is not canonical.
        if not verify_result_signature(raw, timestamp, nonce, signature):
            return _reject(request, 401, 'signature does not verify')

        # 6. Burn the nonce. The unique constraint is the whole mechanism, so a replay loses the
        #    race atomically however many arrive at once. The inner `atomic()` is load-bearing: an
        #    `IntegrityError` marks the enclosing transaction unusable, and without a savepoint to
        #    roll back to, every query after this one would fail.
        try:
            with transaction.atomic():
                SeenNonce.objects.create(nonce=nonce)
        except IntegrityError:
            return _reject(request, 401, 'nonce has been seen before')

        # 7. Only now is it worth parsing. Everything above proves the bytes came from the holder
        #    of the secret; this decides whether they mean anything.
        try:
            body = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            return _reject(request, 400, 'body is not valid JSON')

        problem = _validate_result(body)
        if problem is not None:
            return _reject(request, 400, problem)

        return self.record(request, body)

    def record(self, request, body):
        """
        Apply a verified, well-formed result to its fixture.

        Split out from `post` so that the authentication above reads as one sequence and the
        tournament bookkeeping as another. Everything here happens in one transaction, so a
        refusal partway through leaves the tournament exactly as it was.
        """
        fixture_id = body['fixture_id']

        if body.get('tournament_id') == 0 and fixture_id < 0:
            return self._record_direct_play(request, -fixture_id, body)

        with transaction.atomic():
            try:
                tournament_id = Fixture.objects.values_list(
                    'mode__tournament_id', flat=True).get(pk=fixture_id)
                Tournament.objects.select_for_update().get(pk=tournament_id)
                locked_fixture = Fixture.objects.select_for_update().get(pk=fixture_id)
                game_link = GameLink.objects.select_for_update().get(fixture_id=fixture_id)
                game_link.fixture = locked_fixture
            except (GameLink.DoesNotExist, Fixture.DoesNotExist):
                return _reject(request, 404, 'no game link for this fixture', fixture_id=fixture_id,
                               code='fixture_not_found')

            if locked_fixture.admin_result:
                return _reject(request, 409, 'fixture settled by an administrator', fixture_id=fixture_id,
                               code='fixture_admin_resolved')

            # Terminal idempotency (plan §2, threat 2). A delivery whose response was lost is
            # re-sent under a *fresh* nonce, so it gets this far and must be answered with the
            # same 200 the first one earned — anything else and the sender retries until it gives
            # up on a result that was in fact recorded.
            if game_link.status == STATUS_COMPLETED:
                return _accepted('already_recorded')

            if game_link.status == STATUS_CANCELLED:
                if body['status'] == STATUS_CANCELLED:
                    return _accepted('already_recorded')
                return _reject(request, 409, 'a cancelled link cannot then be completed', fixture_id=fixture_id,
                               code='link_cancelled')

            if game_link.status not in OPEN_LINK_STATUSES:
                return _reject(request, 409, f'link is {game_link.status} and takes no result',
                               fixture_id=fixture_id, code='link_not_open')

            fixture = game_link.fixture

            # The fixture is found by id, so the tournament is checked rather than trusted: a
            # sender naming the wrong tournament for a fixture is confused or hostile, and either
            # way is not to be acted on.
            if body['tournament_id'] != fixture.mode.tournament_id:
                return _reject(request, 409, 'tournament_id does not belong to this fixture',
                               fixture_id=fixture_id, code='tournament_mismatch')

            # The room is pinned on first contact and checked ever after, so a second game cannot
            # report a result over the first one's fixture (plan §2, threat 3).
            if game_link.external_room_id and game_link.external_room_id != body['room_id']:
                return _reject(request, 409, 'room_id does not match the room this fixture is linked to',
                               fixture_id=fixture_id, code='room_mismatch')

            if body['status'] == STATUS_CANCELLED:
                return self._record_cancellation(game_link, body)

            return self._record_completion(request, game_link, fixture, body)

    def _record_direct_play(self, request, table_id, body):
        """Settle a versioned contract, retaining fee-only settlement for legacy friend tables."""
        with transaction.atomic():
            try:
                table = HeadToHeadTable.objects.select_for_update(
                ).select_related('host', 'guest').get(pk=table_id)
            except HeadToHeadTable.DoesNotExist:
                return _reject(request, 404, 'no direct-play table for this result', fixture_id=-table_id)
            if table.status == HeadToHeadTable.STATUS_COMPLETED:
                return _direct_play_response(table, 'already_recorded')
            if table.status == HeadToHeadTable.STATUS_CANCELLED:
                return _accepted('already_recorded') if body['status'] == STATUS_CANCELLED else _reject(
                    request, 409, 'cancelled direct-play table cannot be completed', fixture_id=-table_id)
            if table.game_format != 'legacy':
                from frontend.game_formats import settle
                from django.core.exceptions import ValidationError
                try:
                    with transaction.atomic():
                        settle(table, body)
                        from gamelink.ratings import rate_table
                        rate_table(table, body)
                except ValidationError as error:
                    return _reject(request, 409, '; '.join(error.messages), fixture_id=-table_id)
                return _direct_play_response(table, 'recorded')
            # Rating and wallet settlement share these identities. Lock both in
            # the same order before crediting a winner or refunding either seat.
            list(User.objects.select_for_update().filter(
                pk__in=[table.host_id, table.guest_id]).order_by('pk'))
            if table.external_room_id and table.external_room_id != body['room_id']:
                return _reject(request, 409, 'room mismatch for direct-play table', fixture_id=-table_id)
            if body['status'] != STATUS_CANCELLED:
                if table.status not in (HeadToHeadTable.STATUS_READY, HeadToHeadTable.STATUS_PLAYING) or not table.guest_id:
                    return _reject(request, 409, 'direct-play table is not funded', fixture_id=-table_id)
                charge_kind = WalletTransaction.KIND_FRIEND_GAME_FEE if table.is_friend_game else WalletTransaction.KIND_HEAD_TO_HEAD_ENTRY
                charge_amount = table.fee_per_player if table.is_friend_game else table.amount
                for player_id in (table.host_id, table.guest_id):
                    charges = table.wallet_transactions.filter(
                        user_id=player_id, kind=charge_kind, amount=-charge_amount)
                    if charges.count() != 1 or table.wallet_transactions.filter(user_id=player_id, kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND).exists():
                        return _reject(request, 409, 'direct-play table is not funded', fixture_id=-table_id)
            table.external_room_id = body['room_id']
            if body['status'] == STATUS_CANCELLED:
                for charge in table.wallet_transactions.filter(amount__lt=0).select_related('user'):
                    if not table.wallet_transactions.filter(
                        user=charge.user, kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND,
                    ).exists():
                        WalletTransaction.create_entry(
                            user=charge.user, amount=-charge.amount,
                            kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND,
                            head_to_head_table=table, note=f'Cancelled table {table.code}',
                        )
                table.status = HeadToHeadTable.STATUS_CANCELLED
                table.save(update_fields=[
                           'external_room_id', 'status', 'updated_at'])
                return _accepted('recorded')
            winner = table.host if body.get('winner_seat') == 'p1' else table.guest if body.get(
                'winner_seat') == 'p2' else None
            if winner is None:
                return _reject(request, 400, 'direct-play result has no winner', fixture_id=-table_id)
            if not table.is_friend_game:
                pot = table.amount * Decimal('2')
                # ``amount`` is the advertised stake. The rake is a percentage of
                # that stake, not of the combined two-player pot.
                platform_fee = table.fee_per_player
                WalletTransaction.create_entry(
                    user=winner, amount=pot - platform_fee,
                    kind=WalletTransaction.KIND_HEAD_TO_HEAD_PRIZE,
                    head_to_head_table=table,
                    note=f'Match-play prize for table {table.code}; platform fee {platform_fee}',
                )
            table.winner = winner
            table.status = HeadToHeadTable.STATUS_COMPLETED
            table.completed_at = timezone.now()
            table.save(update_fields=[
                       'external_room_id', 'winner', 'status', 'completed_at', 'updated_at'])
            from gamelink.ratings import rate_table
            rate_table(table, body)
            return _accepted('recorded')

    def _record_cancellation(self, game_link, body):
        """
        Release a fixture whose game did not produce a result.

        The fixture itself is deliberately left alone — unscored, unconfirmed and still editable —
        so the players or an organiser can settle it by hand exactly as they would have without
        any of this (plan §2, threat 18).
        """
        game_link.status = STATUS_CANCELLED
        game_link.external_room_id = body['room_id']
        game_link.raw_result = body
        game_link.save(
            update_fields=['status', 'external_room_id', 'raw_result'])

        logger.info('gamelink result recorded: fixture %s cancelled, released for manual scoring',
                    game_link.fixture_id)
        return _accepted('recorded')

    def _record_completion(self, request, game_link, fixture, body):
        """
        Write a reported score onto its fixture and let the tournament move on.
        """
        # Completing a group can award a champion outside this fixture. Acquire
        # every potential payout/rating identity in one order before either step.
        participant_ids = list(fixture.mode.tournament.participations.values_list(
            'participant__user_id', flat=True))
        participant_ids.extend(player.user_id for player in (
            fixture.player1, fixture.player2) if player)
        list(User.objects.select_for_update().filter(
            pk__in=participant_ids).order_by('pk'))
        # Seats, not colours: the sender has already mapped the score onto `p1`/`p2`, which are
        # this side's `player1` and `player2` because that is how the ticket assigned them.
        previous_score = [fixture.score1, fixture.score2]
        fixture.score1 = body['score']['p1']
        fixture.score2 = body['score']['p2']

        # A result from the game server is authoritative and collects no human votes, so without
        # this the fixture would never reach `required_confirmations_count` and the tournament
        # would stall on it forever (plan §4).
        fixture.auto_confirmed = True

        try:
            # `Fixture.clean` runs `Mode.check_fixture`, which is what stops a draw being written
            # into a knockout bracket that cannot propagate one. Refusing here is the whole point:
            # a corrupt bracket is much worse than an unrecorded result.
            fixture.full_clean()
        except ValidationError as error:
            return _reject(request, 409, f'the reported score is not valid for this fixture: {error}',
                           fixture_id=fixture.pk, code='invalid_score')

        fixture.save()

        # Any human confirmations were votes on a different score, or on no score at all. They do
        # not carry over — the same thing the manual path does when a score is edited.
        fixture.confirmations.clear()

        game_link.status = STATUS_COMPLETED
        game_link.completed_at = timezone.now()
        game_link.external_room_id = body['room_id']
        game_link.raw_result = body
        game_link.save(
            update_fields=['status', 'completed_at', 'external_room_id', 'raw_result'])
        from gamelink.ratings import rate_fixture
        rate_fixture(fixture, body)
        FixtureAudit.objects.create(fixture=fixture, action='game_result',
                                    before={'score': previous_score}, after={'score': [fixture.score1, fixture.score2], 'confirmed': True})

        # This is where the tournament actually advances: the level closes, a knockout propagates
        # its winner, and a finished tournament gets its podium.
        fixture.mode.tournament.update_state()

        logger.info('gamelink result recorded: fixture %s completed %s-%s',
                    fixture.pk, fixture.score1, fixture.score2)
        return _accepted('recorded')


@method_decorator(csrf_exempt, name='dispatch')
class LiveSnapshotCallbackView(View):
    """Accept an authenticated, admin-safe snapshot from the game server."""

    http_method_names = ['post']

    def post(self, request):
        if not settings.GAMELINK_ENABLED:
            return _reject(request, 404, 'the game link is disabled')
        if _declared_length(request) > settings.GAMELINK_MAX_BODY:
            return _reject(request, 413, 'declared body length exceeds GAMELINK_MAX_BODY')
        try:
            raw = request.body
        except RequestDataTooBig:
            return _reject(request, 413, 'body exceeds DATA_UPLOAD_MAX_MEMORY_SIZE')
        if len(raw) > settings.GAMELINK_MAX_BODY:
            return _reject(request, 413, 'body exceeds GAMELINK_MAX_BODY')
        timestamp = request.headers.get('X-Gamelink-Timestamp', '')
        nonce = request.headers.get('X-Gamelink-Nonce', '')
        signature = request.headers.get('X-Gamelink-Signature', '')
        if not _TIMESTAMP_PATTERN.match(timestamp):
            return _reject(request, 401, 'missing or malformed X-Gamelink-Timestamp')
        if not _NONCE_PATTERN.match(nonce):
            return _reject(request, 401, 'missing or malformed X-Gamelink-Nonce')
        if not signature:
            return _reject(request, 401, 'missing X-Gamelink-Signature')
        if abs(int(time.time()) - int(timestamp)) > settings.GAMELINK_CLOCK_SKEW:
            return _reject(request, 401, 'timestamp is outside GAMELINK_CLOCK_SKEW')
        if not verify_result_signature(raw, timestamp, nonce, signature):
            return _reject(request, 401, 'signature does not verify')
        try:
            body = json.loads(raw.decode('utf-8'))
            fixture_id = body['fixture_id']
            tournament_id = body['tournament_id']
            room_id = body['room_id']
            sequence = body['sequence']
            if not all(_is_integer(value) for value in (fixture_id, tournament_id, sequence)):
                raise ValueError
            if not isinstance(room_id, str) or not isinstance(body.get('state'), dict):
                raise ValueError
        except (KeyError, TypeError, ValueError, UnicodeDecodeError):
            return _reject(request, 400, 'invalid live snapshot')
        try:
            with transaction.atomic():
                SeenNonce.objects.create(nonce=nonce)
                # Use the same tournament -> fixture -> link lock order as final results
                # and organizer rulings, so an in-flight snapshot cannot follow a ruling.
                if tournament_id == 0 and fixture_id < 0:
                    return self._record_direct_play(request, -fixture_id, body)
                actual_tournament_id = Fixture.objects.values_list(
                    'mode__tournament_id', flat=True).get(pk=fixture_id)
                Tournament.objects.select_for_update().get(pk=actual_tournament_id)
                Fixture.objects.select_for_update().get(pk=fixture_id)
                link = GameLink.objects.select_for_update().select_related(
                    'fixture__mode').get(fixture_id=fixture_id)
                if link.fixture.mode.tournament_id != tournament_id or link.external_room_id not in ('', room_id):
                    return _reject(request, 409, 'live snapshot does not match fixture', fixture_id=fixture_id)
                if link.fixture.admin_result:
                    return _reject(request, 409, 'fixture settled by an administrator', fixture_id=fixture_id)
                previous = (link.live_snapshot or {}).get('sequence', -1)
                if sequence >= previous:
                    link.live_snapshot = body
                    link.live_updated_at = timezone.now()
                    link.external_room_id = room_id
                    link.status = 'playing' if link.status == 'pending' else link.status
                    link.save(update_fields=[
                              'live_snapshot', 'live_updated_at', 'external_room_id', 'status'])
                    if body.get('status') == 'playing' and not FixtureAudit.objects.filter(fixture_id=fixture_id, action='live_started').exists():
                        FixtureAudit.objects.create(
                            fixture_id=fixture_id, action='live_started')
                    transaction.on_commit(lambda: _broadcast_live_snapshot(
                        tournament_id, fixture_id, body))
        except IntegrityError:
            return _reject(request, 401, 'nonce has been seen before')
        except (GameLink.DoesNotExist, Fixture.DoesNotExist):
            return _reject(request, 404, 'no game link for this fixture', fixture_id=fixture_id)
        return JsonResponse({'status': 'recorded'})

    def _record_direct_play(self, request, table_id, body):
        """Called inside the authenticated snapshot transaction, including nonce storage."""
        try:
            table = HeadToHeadTable.objects.select_for_update().get(pk=table_id)
        except HeadToHeadTable.DoesNotExist:
            return _reject(request, 404, 'no direct-play table for this snapshot', fixture_id=-table_id)
        if not body['room_id'] or len(body['room_id']) > 64 or body['sequence'] < 0:
            return _reject(request, 400, 'invalid direct-play live snapshot', fixture_id=-table_id)
        if table.external_room_id not in ('', body['room_id']):
            return _reject(request, 409, 'room mismatch for direct-play table', fixture_id=-table_id)
        # A delayed snapshot must never reopen a settled table or replace its last live state.
        if table.status in (HeadToHeadTable.STATUS_COMPLETED, HeadToHeadTable.STATUS_CANCELLED):
            return JsonResponse({'status': 'already_recorded'})
        if table.status not in (HeadToHeadTable.STATUS_READY, HeadToHeadTable.STATUS_PLAYING) or not table.guest_id:
            return _reject(request, 409, 'direct-play table is not ready', fixture_id=-table_id)
        previous = (table.live_snapshot or {}).get('sequence', -1)
        if body['sequence'] > previous:
            table.live_snapshot = body
            table.live_updated_at = timezone.now()
            table.external_room_id = body['room_id']
            table.status = HeadToHeadTable.STATUS_PLAYING
            table.save(update_fields=[
                'live_snapshot', 'live_updated_at', 'external_room_id', 'status', 'updated_at',
            ])
        return JsonResponse({'status': 'recorded'})


def _validate_result(body):
    """
    Return why `body` is not a usable result message, or `None` if it is one.

    Only the fields this server acts on are required. The rest of the message is kept verbatim in
    ``GameLink.raw_result`` as the audit record behind the auto-confirmation, and a sender that
    adds a field to it does not thereby break this receiver.
    """
    if not isinstance(body, dict):
        return 'body is not an object'

    # `_is_integer` first, because `True == 1` in Python and a version of `true` is not version 1.
    if not _is_integer(body.get('v')) or body['v'] != RESULT_VERSION:
        return 'unsupported result version'

    for key in ('tournament_id', 'fixture_id'):
        if not _is_integer(body.get(key)):
            return f'{key} is missing or not an integer'

    room_id = body.get('room_id')
    if not isinstance(room_id, str) or not room_id or len(room_id) > 64:
        return 'room_id is missing or not a usable identifier'

    status = body.get('status')
    if status not in REPORTABLE_STATUSES:
        return f'status is not one of {REPORTABLE_STATUSES}'

    if status == STATUS_COMPLETED:
        score = body.get('score')
        if not isinstance(score, dict):
            return 'score is missing'
        for seat in SEATS:
            if not _is_integer(score.get(seat)) or not 0 <= score[seat] <= MAX_SCORE:
                return f'score.{seat} is missing or not a usable score'

    return None


def _is_integer(value):
    # `bool` is a subclass of `int`, and `True` is emphatically not a score or a fixture id.
    return isinstance(value, int) and not isinstance(value, bool)


def _declared_length(request):
    try:
        return int(request.META.get('CONTENT_LENGTH') or 0)
    except (TypeError, ValueError):
        return 0


def _accepted(status):
    return JsonResponse({'status': status})


def _direct_play_response(table, status):
    """Authoritative direct-play response with persisted rating and ledger deltas."""
    # Rating payload - p1 = host, p2 = guest
    rating = None
    try:
        rr = RatingResult.objects.filter(table=table).first()
    except Exception:
        rr = None
    if rr is not None:
        rating = {
            'p1': {
                'before': rr.player1_before,
                'after': rr.player1_after,
                'change': rr.player1_after - rr.player1_before,
            },
            'p2': {
                'before': rr.player2_before,
                'after': rr.player2_after,
                'change': rr.player2_after - rr.player2_before,
            },
        }
    # Money payload - only for money format
    money = None
    if table.game_format == 'money':
        from django.db.models import Sum
        p1_total = table.wallet_transactions.filter(
            user_id=table.host_id).aggregate(total=Sum('amount'))['total']
        p2_total = table.wallet_transactions.filter(user_id=table.guest_id).aggregate(
            total=Sum('amount'))['total'] if table.guest_id else None
        if p1_total is None:
            p1_total = Decimal('0')
        if p2_total is None:
            p2_total = Decimal('0')

        def _to_number(d):
            # Return JSON number: int when integral, else float
            if d == int(d):
                return int(d)
            return float(d)

        money = {
            'stake': str(table.amount),
            'p1Change': _to_number(p1_total),
            'p2Change': _to_number(p2_total),
        }
    return JsonResponse({'status': status, 'rating': rating, 'money': money})


def _broadcast_live_snapshot(tournament_id, fixture_id, snapshot):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        f'tournament_live_{tournament_id}',
        {
            'type': 'tournament.live',
            'payload': {
                'type': 'live_snapshot',
                'fixture_id': fixture_id,
                'live': snapshot,
            },
        },
    )


@method_decorator(csrf_exempt, name='dispatch')
class RematchCallbackView(View):
    http_method_names = ['post']

    def post(self, request):
        if not settings.GAMELINK_ENABLED:
            return _reject(request, 404, 'the game link is disabled')
        if _declared_length(request) > settings.GAMELINK_MAX_BODY:
            return _reject(request, 413, 'declared body length exceeds GAMELINK_MAX_BODY')
        try:
            raw = request.body
        except RequestDataTooBig:
            return _reject(request, 413, 'body exceeds DATA_UPLOAD_MAX_MEMORY_SIZE')
        if len(raw) > settings.GAMELINK_MAX_BODY:
            return _reject(request, 413, 'body exceeds GAMELINK_MAX_BODY')
        timestamp = request.headers.get('X-Gamelink-Timestamp', '')
        nonce = request.headers.get('X-Gamelink-Nonce', '')
        signature = request.headers.get('X-Gamelink-Signature', '')
        if not _TIMESTAMP_PATTERN.match(timestamp):
            return _reject(request, 401, 'missing or malformed X-Gamelink-Timestamp')
        if not _NONCE_PATTERN.match(nonce):
            return _reject(request, 401, 'missing or malformed X-Gamelink-Nonce')
        if not signature:
            return _reject(request, 401, 'missing X-Gamelink-Signature')
        if abs(int(time.time()) - int(timestamp)) > settings.GAMELINK_CLOCK_SKEW:
            return _reject(request, 401, 'timestamp is outside GAMELINK_CLOCK_SKEW')
        if not verify_result_signature(raw, timestamp, nonce, signature):
            return _reject(request, 401, 'signature does not verify')
        try:
            with transaction.atomic():
                SeenNonce.objects.create(nonce=nonce)
        except IntegrityError:
            return _reject(request, 401, 'nonce has been seen before')
        try:
            body = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            return _reject(request, 400, 'body is not valid JSON')
        # validate
        if not isinstance(body, dict) or body.get('v') != 1:
            return _reject(request, 400, 'unsupported version')
        action = body.get('action')
        if action not in ('request', 'accept', 'decline', 'cancel', 'disconnect'):
            return _reject(request, 400, 'invalid action')
        source_table_id = body.get('source_table_id')
        room_id = body.get('room_id')
        actor_seat = body.get('actor_seat')
        if not isinstance(source_table_id, int) or type(source_table_id) is bool or source_table_id <= 0 or not isinstance(room_id, str) or actor_seat not in ('p1', 'p2'):
            return _reject(request, 400, 'invalid rematch payload')
        table_id = source_table_id
        # Process
        try:
            if action == 'request':
                return self._handle_request(request, body, table_id, room_id, actor_seat)
            elif action == 'accept':
                return self._handle_accept(request, body, table_id, room_id, actor_seat)
            elif action == 'decline':
                return self._handle_decline(request, body, table_id, room_id, actor_seat)
            elif action == 'cancel':
                return self._handle_cancel(request, body, table_id, room_id, actor_seat)
            elif action == 'disconnect':
                return self._handle_disconnect(request, body, table_id, room_id, actor_seat)
        except ValidationError as e:
            return _reject(request, 409, '; '.join(e.messages))
        except DirectPlayRematch.DoesNotExist:
            return _reject(request, 404, 'rematch not found')
        except Exception as e:
            logger.exception('rematch error')
            return _reject(request, 400, str(e))
        return _reject(request, 400, 'unhandled')

    def _load_source(self, table_id):
        from django.db.models import Q
        try:
            return HeadToHeadTable.objects.select_for_update().get(pk=table_id)
        except HeadToHeadTable.DoesNotExist:
            raise

    def _handle_request(self, request, body, table_id, room_id, actor_seat):
        from tournaments.models import HeadToHeadTable as H
        from .models import DirectPlayRematch
        from frontend.game_formats import calculate_dynamic_params
        with transaction.atomic():
            source = HeadToHeadTable.objects.select_for_update().get(pk=table_id)
            if source.external_room_id != room_id:
                return JsonResponse({"ok": False, "code": "source_room_mismatch"}, status=409)
            if source.status != HeadToHeadTable.STATUS_COMPLETED:
                return JsonResponse({"ok": False, "code": "source_not_settled"}, status=409)
            if not source.guest_id:
                return JsonResponse({"ok": False, "code": "invalid_source"}, status=409)
            p1 = source.host
            p2 = source.guest
            actor = p1 if actor_seat == 'p1' else p2
            other = p2 if actor == p1 else p1
            # check if already pending
            existing = DirectPlayRematch.objects.select_for_update().filter(
                source_table=source).first()
            if existing:
                if existing.status == 'pending':
                    if existing.requester_id == actor.id:
                        return JsonResponse({'status': 'pending'})
                    else:
                        # other player requests while pending -> treat as accept
                        return self._handle_accept(request, body, table_id, room_id, actor_seat)
                elif existing.status == 'created':
                    if not existing.new_table:
                        return _reject(request, 409, 'rematch created but no table')
                    from .signing import issue_direct_play_ticket
                    t1, _ = issue_direct_play_ticket(
                        existing.new_table.host, existing.new_table, 'p1')
                    t2, _ = issue_direct_play_ticket(
                        existing.new_table.guest, existing.new_table, 'p2')
                    return JsonResponse({'status': 'created', 'table_id': existing.new_table.pk, 'table_code': existing.new_table.code, 'tickets': {'p1': t1, 'p2': t2}})
            # preflight eligibility: check can_join for both
            # requester must afford now, responder preflight
            for user, code in [(actor, 'requester_not_eligible'), (other, 'opponent_not_eligible')]:
                bal = WalletTransaction.balance_for_user(user)
                if source.game_format == 'money':
                    params = calculate_dynamic_params(
                        bal, source.amount, source.rules_snapshot, mars_enabled=True, is_quick=True)
                    if not params['can_join']:
                        return JsonResponse({'code': code}, status=409)
                elif source.is_friend_game:
                    req = source.fee_per_player
                    if bal < req:
                        return JsonResponse({'code': code}, status=409)
                else:
                    req = source.amount
                    if bal < req:
                        return JsonResponse({'code': code}, status=409)
            # create pending
            if existing:
                existing.requester = actor
                existing.responder = other
                existing.status = 'pending'
                existing.save(
                    update_fields=['requester', 'responder', 'status', 'updated_at'])
                rem = existing
            else:
                rem = DirectPlayRematch.objects.create(
                    source_table=source, requester=actor, responder=other, status='pending')
            return JsonResponse({'status': 'pending'})

    def _handle_accept(self, request, body, table_id, room_id, actor_seat):
        from .models import DirectPlayRematch
        from frontend.game_formats import create_rematch_table
        from .signing import issue_direct_play_ticket
        from tournaments.models import HeadToHeadTable as H
        with transaction.atomic():
            source = HeadToHeadTable.objects.select_for_update().get(pk=table_id)
            rem = DirectPlayRematch.objects.select_for_update().get(source_table=source)
            if rem.status != 'pending':
                return _reject(request, 409, 'no pending rematch')
            # actor must be responder
            p1 = source.host
            p2 = source.guest
            actor = p1 if actor_seat == 'p1' else p2
            if rem.responder_id != actor.id:
                return _reject(request, 403, 'only responder may accept')
            # recheck settlement and room mismatch separately
            if source.external_room_id != room_id:
                return JsonResponse({"ok": False, "code": "source_room_mismatch"}, status=409)
            if source.status != HeadToHeadTable.STATUS_COMPLETED:
                return JsonResponse({"ok": False, "code": "source_not_settled"}, status=409)
            # lock users
            from django.contrib.auth.models import User
            uids = sorted([p1.id, p2.id])
            list(User.objects.select_for_update().filter(
                pk__in=uids).order_by('pk'))
            active = [H.STATUS_OPEN, H.STATUS_READY, H.STATUS_PLAYING]
            for uid in uids:
                if H.objects.filter(host_id=uid, status__in=active).exists() or H.objects.filter(guest_id=uid, status__in=active).exists():
                    return _reject(request, 409, 'active game exists')
            # recheck funds — actor-relative codes
            other = p2 if actor.id == p1.id else p1
            from frontend.game_formats import calculate_dynamic_params
            for user, code in ((actor, 'requester_not_eligible'), (other, 'opponent_not_eligible')):
                bal = WalletTransaction.balance_for_user(user)
                if source.game_format == 'money':
                    params = calculate_dynamic_params(
                        bal, source.amount, source.rules_snapshot, mars_enabled=True, is_quick=True)
                    if not params['can_join']:
                        return JsonResponse({'code': code}, status=409)
                elif source.is_friend_game:
                    if bal < source.fee_per_player:
                        return JsonResponse({'code': code}, status=409)
                else:
                    if bal < source.amount:
                        return JsonResponse({'code': code}, status=409)
            new_table = create_rematch_table(source)
            rem.status = 'created'
            rem.new_table = new_table
            rem.save(update_fields=['status', 'new_table', 'updated_at'])
            t1, _ = issue_direct_play_ticket(p1, new_table, 'p1')
            t2, _ = issue_direct_play_ticket(p2, new_table, 'p2')
            return JsonResponse({'status': 'created', 'table_id': new_table.pk, 'table_code': new_table.code, 'tickets': {'p1': t1, 'p2': t2}})

    def _handle_decline(self, request, body, table_id, room_id, actor_seat):
        from .models import DirectPlayRematch
        with transaction.atomic():
            source = HeadToHeadTable.objects.select_for_update().get(pk=table_id)
            rem = DirectPlayRematch.objects.select_for_update().get(source_table=source)
            if rem.status != 'pending':
                return _reject(request, 409, 'no pending')
            p1 = source.host
            p2 = source.guest
            actor = p1 if actor_seat == 'p1' else p2
            if rem.responder_id != actor.id:
                return _reject(request, 403, 'only responder may decline')
            rem.status = 'declined'
            rem.save(update_fields=['status', 'updated_at'])
            return JsonResponse({'status': 'declined'})

    def _handle_cancel(self, request, body, table_id, room_id, actor_seat):
        from .models import DirectPlayRematch
        with transaction.atomic():
            source = HeadToHeadTable.objects.select_for_update().get(pk=table_id)
            rem = DirectPlayRematch.objects.select_for_update().get(source_table=source)
            if rem.status != 'pending':
                return _reject(request, 409, 'no pending')
            p1 = source.host
            p2 = source.guest
            actor = p1 if actor_seat == 'p1' else p2
            if rem.requester_id != actor.id:
                return _reject(request, 403, 'only requester may cancel')
            rem.status = 'cancelled'
            rem.save(update_fields=['status', 'updated_at'])
            return JsonResponse({'status': 'cancelled'})

    def _handle_disconnect(self, request, body, table_id, room_id, actor_seat):
        from .models import DirectPlayRematch
        with transaction.atomic():
            try:
                source = HeadToHeadTable.objects.select_for_update().get(pk=table_id)
            except HeadToHeadTable.DoesNotExist:
                return _reject(request, 404, 'source not found')
            if source.external_room_id != room_id:
                return JsonResponse({"ok": False, "code": "source_room_mismatch"}, status=409)
            if source.status != HeadToHeadTable.STATUS_COMPLETED:
                return JsonResponse({"ok": False, "code": "source_not_settled"}, status=409)
            rem = DirectPlayRematch.objects.select_for_update().filter(
                source_table=source).first()
            if not rem:
                return JsonResponse({'status': 'no_pending'})
            if rem.status != 'pending':
                return JsonResponse({'status': rem.status})
            rem.status = 'cancelled'
            rem.save(update_fields=['status', 'updated_at'])
            return JsonResponse({'status': 'cancelled'})


def _reject(request, status, reason, fixture_id=None, *, code=None):
    """
    Log the full reason. Only validated result handlers opt in to a public, fixed error code.
    """
    logger.warning(
        'gamelink result refused with %s: %s [fixture=%s remote=%s signature=%s]',
        status,
        reason,
        fixture_id,
        request.META.get('REMOTE_ADDR', ''),
        redact(request.headers.get('X-Gamelink-Signature', '')))
    payload = {'error': _ERRORS[status]}
    if code is not None:
        payload['code'] = code
    return JsonResponse(payload, status=status)
