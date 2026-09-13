"""Rating eligibility for authenticated, server-authoritative result callbacks."""

from tournaments.ratings import record_result


RATED_END_REASONS = frozenset({
    'move', 'double_response', 'bear_off', 'give_up', 'leave', 'time', 'disconnect',
})


def eligible_result(body):
    # Only rooms created after the game server removed client-declared outcomes
    # carry this persisted policy marker. Old queued results remain unranked.
    return (
        body.get('rating_policy') == 'server-v1'
        and body.get('status') == 'completed'
        and isinstance(body.get('match_id'), str) and bool(body['match_id'])
        and body.get('end_reason') in RATED_END_REASONS
        and body.get('winner_seat') in ('p1', 'p2')
    )


def rate_table(table, body):
    if table.status != table.STATUS_COMPLETED or table.is_friend_game or not eligible_result(body):
        return
    winner_id = table.host_id if body['winner_seat'] == 'p1' else table.guest_id
    if winner_id != table.winner_id:
        return
    record_result(
        player1_id=table.host_id, player2_id=table.guest_id,
        winner_id=winner_id, reason=body['end_reason'],
        source='quick' if table.is_quick_match else 'public', table=table,
    )


def rate_fixture(fixture, body):
    if not eligible_result(body) or not fixture.player1_id or not fixture.player2_id:
        return
    player1_id, player2_id = fixture.player1.user_id, fixture.player2.user_id
    if not player1_id or not player2_id or player1_id == player2_id or fixture.score1 == fixture.score2:
        return
    winner_seat = 'p1' if fixture.score1 > fixture.score2 else 'p2'
    if body['winner_seat'] != winner_seat:
        return
    record_result(
        player1_id=player1_id, player2_id=player2_id,
        winner_id=player1_id if winner_seat == 'p1' else player2_id,
        reason=body['end_reason'], source='tournament', fixture=fixture,
    )
