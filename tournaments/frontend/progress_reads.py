"""Serialize fixtures using one response's already loaded tournament state."""
from django.utils.dateparse import parse_datetime
from gamelink.spectating import can_watch_fixture
from tournaments.models import Knockout


def _pair_ready(fixture, snapshot, now):
    if not (fixture.playable_at and fixture.playable_at <= now and fixture.player1 and fixture.player2):
        return False
    for player in (fixture.player1, fixture.player2):
        if player.user_id is not None:
            personal = snapshot.current_user_fixtures(player.user)
            if len(personal) != 1 or personal[0].pk != fixture.pk:
                return False
    return True


def _operational_status(fixture, game_link, *, is_confirmed, pair_ready):
    live = game_link.live_snapshot if game_link else None
    live_status = live.get('status') if isinstance(live, dict) else None
    live_playing = bool(game_link and game_link.status in ('pending', 'playing')
                        and (game_link.status == 'playing' or live_status == 'playing'))
    live_state = (live.get('state') or {}) if isinstance(live, dict) else {}
    presence = live_state.get('presence') or {}
    stalled = bool(not is_confirmed and live_playing and presence.get('needsAdminAdjudication'))
    if is_confirmed:
        status = 'completed'
    elif fixture.score1 is not None or fixture.read_confirmation_count:
        status = 'review'
    elif stalled:
        status = 'stalled'
    elif live_playing:
        status = 'playing'
    elif pair_ready:
        status = 'waiting'
    elif bool(fixture.player1_id) != bool(fixture.player2_id):
        status = 'waiting_opponent'
    else:
        status = 'upcoming'
    return status, stalled


def _player_payload(player):
    account = player.user if player and player.user_id else None
    return {'id': player.pk, 'user_id': account.pk if account else None,
            'name': player.name, 'username': account.username if account else None} if player else None


def serialize_waiting_opponent(fixture, snapshot, user, now):
    """Describe only the exact unfinished winner branch feeding the empty seat."""
    if (fixture is None or snapshot.state != 'active' or not user.is_authenticated
            or fixture.admin_result or snapshot.is_confirmed(fixture)
            or bool(fixture.player1_id) == bool(fixture.player2_id)):
        return None
    player = fixture.player1 or fixture.player2
    if player.user_id != user.pk:
        return None
    result = {
        'fixture_id': fixture.pk,
        'round_name': snapshot.round_names[(fixture.mode_id, fixture.level)],
        'deciding_fixture': None,
    }
    if not isinstance(fixture.mode, Knockout) or fixture.mode.double_elimination:
        return result
    missing_slot = 2 if fixture.player1_id else 1
    sources = []
    for source in snapshot.by_stage[fixture.mode_id]:
        extras = source.extras if isinstance(source.extras, dict) else {}
        propagation = extras.get('propagate')
        target = propagation.get('winner') if isinstance(propagation, dict) else None
        if (isinstance(target, dict) and target.get('fixture_id') == fixture.pk
                and target.get('player_slot') == missing_slot):
            sources.append(source)
    if len(sources) != 1:
        return result
    source = sources[0]
    if (source.pk == fixture.pk or source.admin_result or snapshot.is_confirmed(source)
            or not source.player1_id or not source.player2_id
            or user.pk in (source.player1.user_id, source.player2.user_id)):
        return result
    link = getattr(source, 'game_link', None)
    status, _ = _operational_status(
        source, link, is_confirmed=False, pair_ready=_pair_ready(source, snapshot, now),
    )
    result['deciding_fixture'] = {
        'id': source.pk,
        'player1': _player_payload(source.player1),
        'player2': _player_payload(source.player2),
        'is_confirmed': False,
        'can_watch': can_watch_fixture(source, link, user,
                                       tournament_state=snapshot.state, is_confirmed=False),
        'external_room_id': link.external_room_id if link else None,
        'operational_status': status,
    }
    return result


def serialize_fixture(fixture, snapshot, user, now, playability):
    stage = fixture.mode
    player1, player2 = fixture.player1, fixture.player2
    player1_user = player1.user if player1 and player1.user_id else None
    player2_user = player2.user if player2 and player2.user_id else None
    is_player1 = bool(player1_user and player1_user.pk == user.pk)
    is_player2 = bool(player2_user and player2_user.pk == user.pk)
    current_user = player1_user if is_player1 else player2_user if is_player2 else None
    opponent = player2_user if is_player1 else player1_user if is_player2 else None
    game_link = getattr(fixture, 'game_link', None)
    live = game_link.live_snapshot if game_link else None
    is_confirmed = snapshot.is_confirmed(fixture)
    is_current_round = bool(
        snapshot.current_stage and stage.pk == snapshot.current_stage.pk
        and fixture.level == snapshot.current_level
    )
    pair_ready = _pair_ready(fixture, snapshot, now)
    status_started_at = parse_datetime(live['started_at']) if isinstance(live, dict) and live.get('started_at') else None
    started_at = status_started_at or fixture.read_started_at or (
        game_link.created_at if game_link and game_link.status in ('playing', 'completed') else None
    )
    ended_at = fixture.admin_resolved_at or (game_link.completed_at if game_link else None)
    last_activity_at = (game_link.live_updated_at if game_link else None) or started_at or fixture.created_at
    if isinstance(live, dict) and 'event_revision' in live:
        # A status transition says nothing about the latest accepted game action.
        last_activity_at = None
    operational_status, stalled = _operational_status(
        fixture, game_link, is_confirmed=is_confirmed, pair_ready=pair_ready,
    )
    winner_id = fixture.admin_winner_id
    if winner_id is None and fixture.score1 is not None and fixture.score2 is not None:
        winner_id = (fixture.player1_id if fixture.score1 > fixture.score2 else
                     fixture.player2_id if fixture.score2 > fixture.score1 else None)

    def account_payload(account, participant):
        return {'id': account.pk, 'username': account.username,
                'participant_id': participant.pk} if account else None

    own_participant = player1 if is_player1 else player2 if is_player2 else None
    other_participant = player2 if is_player1 else player1 if is_player2 else None
    return {
        'id': fixture.pk, 'stage_id': str(stage.pk), 'stage_name': stage.name or stage.identifier,
        'round_name': snapshot.round_names[(stage.pk, fixture.level)], 'round_index': fixture.level,
        'is_current_round': is_current_round, 'operational_status': operational_status,
        'ready_at': fixture.created_at.isoformat(),
        'started_at': started_at.isoformat() if started_at else None,
        'last_activity_at': last_activity_at.isoformat() if last_activity_at else None,
        'last_status_at': game_link.live_updated_at.isoformat() if game_link and game_link.live_updated_at else None,
        'ended_at': ended_at.isoformat() if ended_at else None,
        'duration_seconds': max(0, int(((ended_at or now) - started_at).total_seconds())) if started_at else None,
        'stalled': stalled, 'admin_resolution': fixture.admin_result,
        'winner_id': winner_id if is_confirmed else None,
        'bracket': ({'position': fixture.extras.get('position'),
                     'winner_to': fixture.extras.get('propagate', {}).get('winner')}
                    if isinstance(stage, Knockout) and not stage.double_elimination
                    and isinstance(fixture.extras, dict) else None),
        'player1': _player_payload(player1),
        'player2': _player_payload(player2),
        'current_user': account_payload(current_user, own_participant),
        'opponent': account_payload(opponent, other_participant),
        'is_current_user': current_user is not None,
        'can_play': playability['can_play'], 'playability': playability,
        'can_watch': can_watch_fixture(fixture, game_link, user,
                                       tournament_state=snapshot.state,
                                       is_confirmed=is_confirmed),
        'score1': fixture.score1, 'score2': fixture.score2, 'is_confirmed': is_confirmed,
        'confirmations': fixture.read_confirmation_count,
        'required_confirmations': snapshot.required_confirmations,
        'editable': not is_confirmed and pair_ready,
        'has_confirmed': fixture.read_has_confirmed,
        'game_result': game_link.raw_result if game_link and game_link.raw_result else None,
        'external_room_id': game_link.external_room_id if game_link else None,
        'live': live,
    }
