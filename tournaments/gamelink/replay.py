"""Session-authorized replay bridge; financial settlement never waits for a replay."""
import json
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .models import GameLink
from .signing import sign_command_body

REPLAY_MAX_BYTES = 48 * 1024


@require_GET
def fixture_replay(request, fixture_id):
    if not request.user.is_authenticated:
        return JsonResponse({'detail': 'Authentication required.'}, status=401)
    if not settings.GAMELINK_ENABLED:
        return JsonResponse({'detail': 'Replay not found.'}, status=404)
    link = GameLink.objects.select_related('fixture__mode__tournament').filter(fixture_id=fixture_id).first()
    # Match the existing progress GET visibility: authenticated readers, started tournaments.
    if link is None or link.fixture.mode.tournament.state not in ('active', 'finished'):
        return JsonResponse({'detail': 'Replay not found.'}, status=404)
    result = link.raw_result
    if not isinstance(result, dict) or not isinstance(result.get('replay'), dict):
        return JsonResponse({'detail': 'Replay not found.'}, status=404)
    try:
        match_id = str(uuid.UUID(result['match_id']))
        room_id = str(uuid.UUID(link.external_room_id))
        if result['replay'].get('match_id') != match_id or result.get('room_id') != room_id:
            raise ValueError()
        game_index = int(request.GET.get('game_index', '0'))
        turn_offset = int(request.GET.get('turn_offset', '0'))
        if game_index < 0 or turn_offset < 0:
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        return JsonResponse({'detail': 'Invalid replay position.'}, status=400)
    base = getattr(settings, 'GAMELINK_BACKGAMMON_URL', '').rstrip('/')
    if not base or not getattr(settings, 'GAMELINK_COMMAND_SECRET', ''):
        return JsonResponse({'detail': 'Replay unavailable.'}, status=503)
    body = {'v': 1, 'action': 'read_replay', 'issuer': settings.GAMELINK_ISSUER, 'fixture_id': fixture_id,
            'room_id': room_id, 'match_id': match_id, 'game_index': game_index,
            'turn_offset': turn_offset, 'limit': 50}
    raw = json.dumps(body, separators=(',', ':'), sort_keys=True).encode()
    timestamp = str(int(time.time()))
    try:
        headers = {'Content-Type': 'application/json', 'X-Gamelink-Timestamp': timestamp,
                   'X-Gamelink-Signature': sign_command_body(raw, timestamp),
                   'X-Gamelink-Issuer': settings.GAMELINK_ISSUER}
        with urlopen(Request(base + '/api/link/replay/', data=raw, headers=headers, method='POST'),
                     timeout=3) as upstream:
            content = upstream.read(REPLAY_MAX_BYTES + 1)
        if len(content) > REPLAY_MAX_BYTES:
            raise ValueError()
        payload = json.loads(content)
        if (not isinstance(payload, dict) or payload.get('match_id') != match_id
                or payload.get('game_index') != game_index or payload.get('turn_offset') != turn_offset
                or any(type(payload.get(key)) is not int for key in ('game_count', 'game_index', 'turn_offset', 'turn_count'))
                or payload['game_count'] != result['replay'].get('game_count')
                or payload['game_count'] < 0 or payload['turn_count'] < turn_offset):
            raise ValueError()
        game = payload.get('game')
        if payload['game_count'] == 0:
            if game is not None or game_index or turn_offset or payload['turn_count']:
                raise ValueError()
        elif (not isinstance(game, dict) or not isinstance(game.get('transcript'), list)
              or len(game['transcript']) > 50 or not 0 <= game_index < payload['game_count']
              or turn_offset + len(game['transcript']) > payload['turn_count']):
            raise ValueError()
        turns = game['transcript'] if game else []
        end = turn_offset + len(turns)
        expected_next = end if end < payload['turn_count'] else None
        if payload.get('next_offset') != expected_next or (expected_next is not None and not turns):
            raise ValueError()
    except HTTPError as error:
        return JsonResponse({'detail': 'Replay unavailable.'}, status=404 if error.code == 404 else 503)
    except (URLError, OSError, TimeoutError, ValueError):
        return JsonResponse({'detail': 'Replay unavailable.'}, status=503)
    response = JsonResponse(payload, json_dumps_params={'separators': (',', ':')})
    response['Cache-Control'] = 'private, no-store'
    return response
