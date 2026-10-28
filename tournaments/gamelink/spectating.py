"""Issue narrowly scoped, read-only admission to an already running tournament room."""
import time
import uuid
from urllib.parse import quote, urlsplit, urlunsplit

from django.conf import settings
from django.core import signing
from django.core.exceptions import ImproperlyConfigured
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .models import GameLink, LinkedAccount
from .signing import _ticket_secret

SPECTATOR_SALT = 'gamelink.spectator.v1'
SPECTATOR_TTL = 120


def can_watch_fixture(fixture, game_link, user, *, tournament_state, is_confirmed):
    """Shared visibility check; callers supply fresh state or a response-local snapshot."""
    if (not settings.GAMELINK_ENABLED or not user.is_authenticated
            or tournament_state != 'active' or not fixture.mode.tournament.published
            or is_confirmed or fixture.admin_result or fixture.score1 is not None
            or not fixture.player1_id or not fixture.player2_id or game_link is None):
        return False
    if user.pk in (fixture.player1.user_id, fixture.player2.user_id):
        return False
    live = game_link.live_snapshot if isinstance(game_link.live_snapshot, dict) else {}
    state = live.get('state') if isinstance(live.get('state'), dict) else {}
    presence = state.get('presence') if isinstance(state.get('presence'), dict) else {}
    if (game_link.status not in ('pending', 'playing')
            or (game_link.status != 'playing' and live.get('status') != 'playing')
            or live.get('status') in ('completed', 'cancelled', 'failed')
            or presence.get('needsAdminAdjudication')):
        return False
    try:
        uuid.UUID(game_link.external_room_id)
    except (ValueError, TypeError, AttributeError):
        return False
    return True


def _frontend_url():
    configured = getattr(settings, 'GAMELINK_GAME_FRONTEND_URL', '').strip()
    if not configured:
        backend = urlsplit(getattr(settings, 'GAMELINK_BACKGAMMON_URL', ''))
        configured = urlunsplit((backend.scheme, backend.netloc, '/6b/backgammon', '', ''))
    parsed = urlsplit(configured)
    local_http = parsed.scheme == 'http' and (
        parsed.hostname in ('localhost', '127.0.0.1', '::1')
        or (parsed.hostname or '').endswith('.localhost'))
    if (not parsed.netloc or (parsed.scheme != 'https' and not local_http)
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ImproperlyConfigured('Invalid game frontend URL')
    return configured.rstrip('/')


def _response(payload, *, status=200):
    response = JsonResponse(payload, status=status)
    response['Cache-Control'] = 'private, no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response


@require_POST
def watch_fixture(request, fixture_id):
    if not request.user.is_authenticated:
        return _response({'detail': 'Authentication required.'}, status=401)
    if not settings.GAMELINK_ENABLED:
        return _response({'detail': 'Game not available for watching.'}, status=404)
    link = GameLink.objects.select_related(
        'fixture__mode__tournament', 'fixture__player1', 'fixture__player2',
    ).filter(fixture_id=fixture_id).first()
    if link is None:
        return _response({'detail': 'Game not available for watching.'}, status=404)
    fixture = link.fixture
    tournament = fixture.mode.tournament
    if not can_watch_fixture(fixture, link, request.user,
                             tournament_state=tournament.state,
                             is_confirmed=fixture.is_confirmed):
        return _response({'detail': 'Game not available for watching.'}, status=404)
    try:
        frontend = _frontend_url()
        issued_at = int(time.time())
        room_id = str(uuid.UUID(link.external_room_id))
        payload = {
            'v': 1, 'role': 'spectator', 'iss': settings.GAMELINK_ISSUER,
            'aud': settings.GAMELINK_AUDIENCE,
            'sub': LinkedAccount.external_id_for(request.user),
            'trn': tournament.pk, 'fix': fixture.pk, 'room': room_id,
            'iat': issued_at, 'exp': issued_at + SPECTATOR_TTL,
            'jti': str(uuid.uuid4()),
        }
        token = signing.dumps(payload, key=_ticket_secret(), salt=SPECTATOR_SALT, compress=False)
    except ImproperlyConfigured:
        return _response({'detail': 'Watching is temporarily unavailable.'}, status=503)
    return _response({
        'url': f'{frontend}/watch/{room_id}/?tournament={tournament.pk}#ticket={quote(token)}',
    })
