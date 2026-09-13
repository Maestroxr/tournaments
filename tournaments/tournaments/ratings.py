"""Elo v1: initial 1000, K=32, expected score 1/(1+10**((R2-R1)/400)).

One nearest-integer delta (half upwards) is applied with opposite signs so every
result is zero-sum. Stakes, cube, win margin and match length do not weight Elo.
Only trusted settlement callers decide eligibility; client match saves never call
this module. Historical results are deliberately not backfilled.
"""
import math

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from .models import PlayerRating, RatingResult

ALGORITHM = 'elo-v1'


@transaction.atomic
def record_result(*, player1_id, player2_id, winner_id, reason, source, fixture=None, table=None):
    if player1_id == player2_id or winner_id not in (player1_id, player2_id):
        raise ValidationError('A rated result requires two distinct players and their winner.')
    if (fixture is None) == (table is None):
        raise ValidationError('A rated result requires exactly one fixture or table.')
    origin = {'fixture': fixture} if fixture is not None else {'table': table}
    # Lock existing identities before creating rating rows; ordering prevents
    # deadlocks when concurrent matches involve the same players in reverse seats.
    users = list(User.objects.select_for_update().filter(pk__in=[player1_id, player2_id]).order_by('pk'))
    if len(users) != 2:
        raise ValidationError('Both rated players must exist.')
    existing = RatingResult.objects.filter(**origin).first()
    if existing is not None:
        return existing
    ratings = {user.pk: PlayerRating.objects.get_or_create(user=user)[0] for user in users}
    first, second = ratings[player1_id], ratings[player2_id]
    difference = max(-12000, min(12000, second.value - first.value))
    expected = 1 / (1 + 10 ** (difference / 400))
    score = 1 if winner_id == player1_id else 0
    magnitude = math.floor(32 * abs(score - expected) + 0.5)
    delta = magnitude if score else -magnitude
    result = RatingResult.objects.create(
        **origin, player1_id=player1_id, player2_id=player2_id, winner_id=winner_id,
        player1_before=first.value, player1_after=first.value + delta,
        player2_before=second.value, player2_after=second.value - delta,
        reason=reason, source=source, algorithm=ALGORITHM,
    )
    for rating, change in ((first, delta), (second, -delta)):
        rating.value += change
        rating.games_played += 1
        rating.save(update_fields=['value', 'games_played'])
    return result


def serialize_rating(user):
    rating = PlayerRating.objects.filter(user=user).first()
    results = RatingResult.objects.filter(Q(player1=user) | Q(player2=user)).select_related('player1', 'player2')[:20]
    history = []
    for result in results:
        first = result.player1_id == user.pk
        before = result.player1_before if first else result.player2_before
        after = result.player1_after if first else result.player2_after
        opponent = result.player2 if first else result.player1
        history.append({
            'id': result.pk, 'played_at': result.played_at.isoformat(),
            'opponent': opponent.get_full_name() or opponent.username,
            'before': before, 'after': after, 'delta': after - before,
            'result': 'win' if result.winner_id == user.pk else 'loss',
            'source': result.source, 'reason': result.reason,
        })
    return {'value': rating.value if rating else 1000,
            'games_played': rating.games_played if rating else 0,
            'algorithm': ALGORITHM, 'history': history}
