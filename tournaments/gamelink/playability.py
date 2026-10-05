"""Personal fixture ordering shared by reads, admission and scoring."""


def earliest_unresolved_fixtures(fixtures, user_id=None, *, participant_id=None, is_confirmed=None):
    """Keep every earliest candidate so ambiguous assignments fail closed.

    An unresolved fixture with a missing opponent still blocks later personal
    fixtures. Stage/round order applies to this player's own schedule, not to
    unrelated matches elsewhere in the tournament.
    """
    if user_id is not None and participant_id is not None:
        raise ValueError('Choose either user_id or participant_id.')
    if user_id is None and participant_id is None:
        return []
    confirmed = is_confirmed or (lambda fixture: fixture.is_confirmed)

    def assigned_to_player(fixture):
        if participant_id is not None:
            return participant_id in (fixture.player1_id, fixture.player2_id)
        for player in (fixture.player1, fixture.player2):
            if player is None:
                continue
            if player.user_id == user_id:
                return True
        return False

    assigned = [
        fixture for fixture in fixtures
        if assigned_to_player(fixture) and not confirmed(fixture)
    ]
    if not assigned:
        return []
    earliest = min((fixture.mode_id, fixture.level) for fixture in assigned)
    return [fixture for fixture in assigned if (fixture.mode_id, fixture.level) == earliest]


def personally_ready_fixture_ids(fixtures, *, is_confirmed=None):
    """Pairs whose two participants each have this one earliest open fixture.

    Deliberately independent of activation timestamps and online accounts: model
    activation and expiry also need the same rule for offline participants.
    """
    confirmed = is_confirmed or (lambda fixture: fixture.is_confirmed)
    pending = [fixture for fixture in fixtures if not confirmed(fixture)]
    assigned = {}
    for fixture in pending:
        for participant_id in (fixture.player1_id, fixture.player2_id):
            if participant_id is not None:
                assigned.setdefault(participant_id, []).append(fixture)
    current = {
        participant_id: earliest_unresolved_fixtures(
            rows, participant_id=participant_id, is_confirmed=lambda _: False,
        ) for participant_id, rows in assigned.items()
    }
    return {
        fixture.pk for fixture in pending
        if fixture.player1_id is not None and fixture.player2_id is not None
        and all(
            len(current[participant_id]) == 1 and current[participant_id][0].pk == fixture.pk
            for participant_id in (fixture.player1_id, fixture.player2_id)
        )
    }
