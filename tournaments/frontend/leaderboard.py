"""Read-only leaderboard over the canonical player ratings."""
from django.db.models import F, Window
from django.db.models.functions import Rank
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from tournaments.models import PlayerRating

from .list_pages import page_bounds, page_payload


def _player(row, position):
    return {
        'user_id': row['user_id'],
        'username': row['user__username'],
        'rating': row['value'],
        'games_played': row['games_played'],
        'position': position,
    }


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
    ranked = eligible.annotate(position=Window(
        expression=Rank(), order_by=F('value').desc(),
    )).order_by('-value', 'user_id').values(
        'user_id', 'user__username', 'value', 'games_played', 'position',
    )
    players = [_player(row, row['position']) for row in ranked[offset:offset + limit]]

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
    return JsonResponse(page_payload(players, count, offset, limit, me=me))
