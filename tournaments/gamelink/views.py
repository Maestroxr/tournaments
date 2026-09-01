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
import re
import time
from urllib.parse import quote

from asgiref.sync import async_to_sync
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import RequestDataTooBig, ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View
from channels.layers import get_channel_layer
from tournaments.models import Fixture

from .models import GameLink, IssuedTicket, SeenNonce
from .signing import SEATS, issue_ticket, redact, verify_result_signature

logger = logging.getLogger(__name__)


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
    if fixture.level != current_stage.current_level:
        return 'fixture_not_in_current_level'
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

    def post(self, request, pk):
        if not settings.GAMELINK_ENABLED:
            logger.warning('gamelink start refused: disabled [fixture=%s user=%s]', pk, request.user.pk)
            return _start_refusal(412, 'disabled')

        try:
            fixture = Fixture.objects.get(pk = pk)
        except Fixture.DoesNotExist:
            logger.warning('gamelink start refused: fixture does not exist [fixture=%s user=%s]', pk, request.user.pk)
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
                getattr(tournament.current_stage, 'current_level', None), fixture.is_confirmed,
                fixture.player1.user_id if fixture.player1 else None,
                fixture.player2.user_id if fixture.player2 else None,
            )
            return _start_refusal(refusal, reason)

        # The destination comes from settings and from nowhere else — no host, path or scheme is
        # ever read from the request or from a ticket claim (plan §2, threat 8).
        base_url = settings.GAMELINK_BACKGAMMON_URL.rstrip('/')
        if not base_url:
            logger.warning('gamelink start refused: GAMELINK_BACKGAMMON_URL is empty [fixture=%s user=%s]',
                           fixture.pk, request.user.pk)
            return _start_refusal(412, 'backgammon_url_is_empty')

        now = timezone.now()
        link_ttl = datetime.timedelta(seconds = settings.GAMELINK_LINK_TTL)

        with transaction.atomic():
            game_link, _ = GameLink.objects.get_or_create(
                fixture = fixture,
                defaults = dict(
                    target_points = fixture.mode.tournament.target_points,
                    doubling_enabled = fixture.mode.tournament.doubling_enabled,
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

# Deliberately uninformative (plan §3.2). A caller learns only that it was refused; *why* goes to
# the log and nowhere else, so a prober cannot use the response to map the guards.
_ERRORS = {
    400: 'bad_request',
    401: 'unauthorized',
    404: 'not_found',
    409: 'conflict',
    413: 'payload_too_large',
}


@method_decorator(csrf_exempt, name = 'dispatch')
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
        nonce     = request.headers.get('X-Gamelink-Nonce', '')
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
                SeenNonce.objects.create(nonce = nonce)
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

        with transaction.atomic():
            try:
                game_link = GameLink.objects.select_for_update().get(fixture_id = fixture_id)
            except GameLink.DoesNotExist:
                return _reject(request, 404, 'no game link for this fixture', fixture_id = fixture_id)

            # Terminal idempotency (plan §2, threat 2). A delivery whose response was lost is
            # re-sent under a *fresh* nonce, so it gets this far and must be answered with the
            # same 200 the first one earned — anything else and the sender retries until it gives
            # up on a result that was in fact recorded.
            if game_link.status == STATUS_COMPLETED:
                return _accepted('already_recorded')

            if game_link.status == STATUS_CANCELLED:
                if body['status'] == STATUS_CANCELLED:
                    return _accepted('already_recorded')
                return _reject(request, 409, 'a cancelled link cannot then be completed', fixture_id = fixture_id)

            if game_link.status not in OPEN_LINK_STATUSES:
                return _reject(request, 409, f'link is {game_link.status} and takes no result',
                               fixture_id = fixture_id)

            fixture = game_link.fixture

            # The fixture is found by id, so the tournament is checked rather than trusted: a
            # sender naming the wrong tournament for a fixture is confused or hostile, and either
            # way is not to be acted on.
            if body['tournament_id'] != fixture.mode.tournament_id:
                return _reject(request, 409, 'tournament_id does not belong to this fixture',
                               fixture_id = fixture_id)

            # The room is pinned on first contact and checked ever after, so a second game cannot
            # report a result over the first one's fixture (plan §2, threat 3).
            if game_link.external_room_id and game_link.external_room_id != body['room_id']:
                return _reject(request, 409, 'room_id does not match the room this fixture is linked to',
                               fixture_id = fixture_id)

            if body['status'] == STATUS_CANCELLED:
                return self._record_cancellation(game_link, body)

            return self._record_completion(request, game_link, fixture, body)

    def _record_cancellation(self, game_link, body):
        """
        Release a fixture whose game did not produce a result.

        The fixture itself is deliberately left alone — unscored, unconfirmed and still editable —
        so the players or an organiser can settle it by hand exactly as they would have without
        any of this (plan §2, threat 18).
        """
        game_link.status           = STATUS_CANCELLED
        game_link.external_room_id = body['room_id']
        game_link.raw_result       = body
        game_link.save(update_fields = ['status', 'external_room_id', 'raw_result'])

        logger.info('gamelink result recorded: fixture %s cancelled, released for manual scoring',
                    game_link.fixture_id)
        return _accepted('recorded')

    def _record_completion(self, request, game_link, fixture, body):
        """
        Write a reported score onto its fixture and let the tournament move on.
        """
        # Seats, not colours: the sender has already mapped the score onto `p1`/`p2`, which are
        # this side's `player1` and `player2` because that is how the ticket assigned them.
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
                           fixture_id = fixture.pk)

        fixture.save()

        # Any human confirmations were votes on a different score, or on no score at all. They do
        # not carry over — the same thing the manual path does when a score is edited.
        fixture.confirmations.clear()

        game_link.status           = STATUS_COMPLETED
        game_link.completed_at     = timezone.now()
        game_link.external_room_id = body['room_id']
        game_link.raw_result       = body
        game_link.save(update_fields = ['status', 'completed_at', 'external_room_id', 'raw_result'])

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
        try:
            raw = request.body
        except RequestDataTooBig:
            return _reject(request, 413, 'body exceeds DATA_UPLOAD_MAX_MEMORY_SIZE')
        timestamp = request.headers.get('X-Gamelink-Timestamp', '')
        nonce = request.headers.get('X-Gamelink-Nonce', '')
        signature = request.headers.get('X-Gamelink-Signature', '')
        if (len(raw) > settings.GAMELINK_MAX_BODY or not _TIMESTAMP_PATTERN.match(timestamp)
                or not _NONCE_PATTERN.match(nonce) or not signature
                or abs(int(time.time()) - int(timestamp)) > settings.GAMELINK_CLOCK_SKEW
                or not verify_result_signature(raw, timestamp, nonce, signature)):
            return _reject(request, 401, 'live snapshot authentication failed')
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
                link = GameLink.objects.select_for_update().select_related('fixture__mode').get(fixture_id=fixture_id)
                if link.fixture.mode.tournament_id != tournament_id or link.external_room_id not in ('', room_id):
                    return _reject(request, 409, 'live snapshot does not match fixture', fixture_id=fixture_id)
                previous = (link.live_snapshot or {}).get('sequence', -1)
                if sequence >= previous:
                    link.live_snapshot = body
                    link.live_updated_at = timezone.now()
                    link.external_room_id = room_id
                    link.status = 'playing' if link.status == 'pending' else link.status
                    link.save(update_fields=['live_snapshot', 'live_updated_at', 'external_room_id', 'status'])
                    transaction.on_commit(lambda: _broadcast_live_snapshot(tournament_id, fixture_id, body))
        except IntegrityError:
            return _reject(request, 401, 'nonce has been seen before')
        except GameLink.DoesNotExist:
            return _reject(request, 404, 'no game link for this fixture', fixture_id=fixture_id)
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


def _reject(request, status, reason, fixture_id = None):
    """
    Log why a result was refused, and answer with a response that does not say (plan §6).
    """
    logger.warning(
        'gamelink result refused with %s: %s [fixture=%s remote=%s signature=%s]',
        status,
        reason,
        fixture_id,
        request.META.get('REMOTE_ADDR', ''),
        redact(request.headers.get('X-Gamelink-Signature', '')))
    return JsonResponse({'error': _ERRORS[status]}, status = status)
