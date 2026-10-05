"""Serialize fixtures using one response's already loaded tournament state."""
from django.utils.dateparse import parse_datetime

from tournaments.models import Knockout


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
    assigned_accounts = [account for account in (player1_user, player2_user) if account is not None]
    pair_ready = bool(fixture.playable_at and fixture.playable_at <= now and player1 and player2)
    if pair_ready:
        for account in assigned_accounts:
            personal = snapshot.current_user_fixtures(account)
            if len(personal) != 1 or personal[0].pk != fixture.pk:
                pair_ready = False
                break
    status_started_at = parse_datetime(live['started_at']) if isinstance(live, dict) and live.get('started_at') else None
    started_at = status_started_at or fixture.read_started_at or (
        game_link.created_at if game_link and game_link.status in ('playing', 'completed') else None
    )
    ended_at = fixture.admin_resolved_at or (game_link.completed_at if game_link else None)
    last_activity_at = (game_link.live_updated_at if game_link else None) or started_at or fixture.created_at
    if isinstance(live, dict) and 'event_revision' in live:
        # A status transition says nothing about the latest accepted game action.
        last_activity_at = None
    live_status = live.get('status') if isinstance(live, dict) else None
    live_playing = bool(game_link and game_link.status in ('pending', 'playing')
                        and (game_link.status == 'playing' or live_status == 'playing'))
    live_state = (live.get('state') or {}) if isinstance(live, dict) else {}
    presence = live_state.get('presence') or {}
    stalled = bool(not is_confirmed and live_playing and presence.get('needsAdminAdjudication'))
    if is_confirmed:
        operational_status = 'completed'
    elif fixture.score1 is not None or fixture.read_confirmation_count:
        operational_status = 'review'
    elif stalled:
        operational_status = 'stalled'
    elif live_playing:
        operational_status = 'playing'
    elif pair_ready:
        operational_status = 'waiting'
    elif bool(player1) != bool(player2):
        operational_status = 'waiting_opponent'
    else:
        operational_status = 'upcoming'
    winner_id = fixture.admin_winner_id
    if winner_id is None and fixture.score1 is not None and fixture.score2 is not None:
        winner_id = (fixture.player1_id if fixture.score1 > fixture.score2 else
                     fixture.player2_id if fixture.score2 > fixture.score1 else None)

    def player_payload(player, account):
        return {'id': player.pk, 'user_id': account.pk if account else None,
                'name': player.name, 'username': account.username if account else None} if player else None

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
        'player1': player_payload(player1, player1_user),
        'player2': player_payload(player2, player2_user),
        'current_user': account_payload(current_user, own_participant),
        'opponent': account_payload(opponent, other_participant),
        'is_current_user': current_user is not None,
        'can_play': playability['can_play'], 'playability': playability,
        'score1': fixture.score1, 'score2': fixture.score2, 'is_confirmed': is_confirmed,
        'confirmations': fixture.read_confirmation_count,
        'required_confirmations': snapshot.required_confirmations,
        'editable': not is_confirmed and pair_ready,
        'has_confirmed': fixture.read_has_confirmed,
        'game_result': game_link.raw_result if game_link and game_link.raw_result else None,
        'external_room_id': game_link.external_room_id if game_link else None,
        'live': live,
    }
