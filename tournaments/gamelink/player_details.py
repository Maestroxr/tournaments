"""Read the canonical rating and wallet of an existing game's participants."""
import json
import re
import time
import uuid

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from tournaments.models import HeadToHeadTable, PlayerRating, WalletTransaction
from .models import GameLink
from .signing import verify_result_signature


def _response(data, status=200):
    response = JsonResponse(data, status=status)
    response['Cache-Control'] = 'private, no-store'
    return response


def _summary(user):
    if user is None:
        return None
    rating = PlayerRating.objects.filter(user=user).values_list('value', flat=True).first()
    return {
        'rating': rating if rating is not None else PlayerRating._meta.get_field('value').get_default(),
        'balance': str(WalletTransaction.balance_for_user(user)),
    }


@csrf_exempt
@require_POST
def player_details(request):
    if not settings.GAMELINK_ENABLED:
        return _response({'detail': 'Not found.'}, 404)
    try:
        raw = request.body
    except RequestDataTooBig:
        return _response({'detail': 'Request too large.'}, 413)
    if len(raw) > settings.GAMELINK_MAX_BODY:
        return _response({'detail': 'Request too large.'}, 413)
    timestamp = request.headers.get('X-Gamelink-Timestamp', '')
    nonce = request.headers.get('X-Gamelink-Nonce', '')
    issuer = request.headers.get('X-Gamelink-Issuer', '')
    if (issuer != settings.GAMELINK_AUDIENCE
            or not re.fullmatch(r'[0-9]{1,12}', timestamp)
            or not re.fullmatch(r'[0-9a-f]{32}', nonce)
            or abs(int(time.time()) - int(timestamp)) > settings.GAMELINK_CLOCK_SKEW
            or not verify_result_signature(raw, timestamp, nonce, request.headers.get('X-Gamelink-Signature', ''))):
        return _response({'detail': 'Unauthorized.'}, 401)
    try:
        body = json.loads(raw)
        if (not isinstance(body, dict) or body.get('v') != 1
                or body.get('purpose') != 'game_player_details' or body.get('iss') != issuer
                or type(body.get('fixture_id')) is not int or body['fixture_id'] == 0
                or type(body.get('tournament_id')) is not int):
            raise ValueError()
        room_id = str(uuid.UUID(body['room_id']))
    except (ValueError, KeyError, TypeError, AttributeError):
        return _response({'detail': 'Invalid game.'}, 400)

    if body['fixture_id'] < 0 and body['tournament_id'] == 0:
        game = HeadToHeadTable.objects.select_related('host', 'guest').filter(pk=-body['fixture_id']).first()
        if game is None or (game.external_room_id and game.external_room_id != room_id):
            return _response({'detail': 'Game not found.'}, 404)
        users = {'p1': game.host, 'p2': game.guest}
    else:
        game = GameLink.objects.select_related('fixture__player1__user', 'fixture__player2__user').filter(
            fixture_id=body['fixture_id'], fixture__mode__tournament_id=body['tournament_id'],
            provider=issuer,
        ).first()
        if game is None or (game.external_room_id and game.external_room_id != room_id):
            return _response({'detail': 'Game not found.'}, 404)
        fixture = game.fixture
        users = {'p1': fixture.player1.user if fixture.player1 else None,
                 'p2': fixture.player2.user if fixture.player2 else None}
        if ((game.entry_player1_id and (users['p1'] is None or game.entry_player1_id != users['p1'].pk))
                or (game.entry_player2_id and (users['p2'] is None or game.entry_player2_id != users['p2'].pk))):
            return _response({'detail': 'Game participants changed.'}, 404)
    return _response({'players': {seat: _summary(user) for seat, user in users.items()}})
