"""Read-only leaderboard over the canonical player ratings."""
from django.db.models import Count, F, OuterRef, Subquery, Window
from django.db.models.functions import Coalesce, Rank
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from tournaments.models import PlayerRating, RatingResult

from .list_pages import page_bounds, page_payload
from .performance import read_leaderboard_performance


def _player(row, position):
    return {
        'user_id': row['user_id'],
        'username': row['user__username'],
        'rating': row['value'],
        'games_played': row['games_played'],
        'position': position,
    }


def _result_count(results, player_field):
    counts = results.order_by().values(player_field).annotate(total=Count('pk')).values('total')
    return Coalesce(Subquery(counts), 0)


@never_cache
@require_GET
def leaderboard(request):
    if not request.user.is_authenticated:
        return JsonResponse({'detail': 'Authentication required'}, status=401)
    try:
        offset, limit = page_bounds(request.GET)
    except ValueError as error:
        return JsonResponse({'detail': str(error)}, status=400)

    eligible = PlayerRating.objects.filter(games_played__gt=0, user__is_active=True)
    count = eligible.count()
    # Rank only by score, then order equal scores by identity for stable pages.
    player = OuterRef('user_id')
    losses = RatingResult.objects.exclude(winner_id=player)
    ranked = eligible.annotate(
        position=Window(expression=Rank(), order_by=F('value').desc()),
        wins=_result_count(RatingResult.objects.filter(winner_id=player), 'winner_id'),
        losses=(
            _result_count(losses.filter(player1_id=player), 'player1_id')
            + _result_count(losses.filter(player2_id=player), 'player2_id')
        ),
    ).order_by('-value', 'user_id').values(
        'user_id', 'user__username', 'value', 'games_played', 'position', 'wins', 'losses',
        linked_identity=F('user__gamelink_account__external_id'),
    )
    rows = list(ranked[offset:offset + limit])
    own = eligible.filter(user_id=request.user.pk).values(
        'user_id', 'user__username', 'value', 'games_played',
    ).first()
    if own is not None:
        me = _player(own, eligible.filter(value__gt=own['value']).count() + 1)
    else:
        me = {
            'user_id': request.user.pk, 'username': request.user.username,
            'rating': None, 'games_played': 0, 'position': None,
        }

    identities = {
        row['user_id']: str(row['linked_identity']) for row in rows if row['linked_identity'] is not None
    }
    performance = read_leaderboard_performance(list(identities.values()))
    available_pr = performance or {}
    players = [
        {
            **_player(row, row['position']),
            'wins': row['wins'],
            'losses': row['losses'],
            'pr': available_pr.get(identities.get(row['user_id'])),
            'pr_unavailable': performance is None and row['user_id'] in identities,
        }
        for row in rows
    ]
    return JsonResponse(page_payload(players, count, offset, limit, me=me))
