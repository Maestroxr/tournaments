"""Live lobby summaries and explicitly requested personal history."""
from django.db.models import Case, IntegerField, Q, Value, When

from tournaments.models import HeadToHeadTable

from .list_pages import page_bounds, queryset_page


def table_queries(user):
    closed = (HeadToHeadTable.STATUS_COMPLETED, HeadToHeadTable.STATUS_CANCELLED)
    own = HeadToHeadTable.objects.filter(Q(host=user) | Q(guest=user)).select_related('host', 'guest', 'winner')
    public = HeadToHeadTable.objects.filter(
        mode=HeadToHeadTable.MODE_MATCH, game_format__in=['match', 'money'],
        status=HeadToHeadTable.STATUS_OPEN, guest__isnull=True,
    ).exclude(host=user).select_related('host', 'guest', 'winner').order_by('-created_at', '-pk')
    ongoing = own.exclude(status__in=closed).alias(page_priority=Case(
        When(status=HeadToHeadTable.STATUS_PLAYING, then=Value(0)),
        When(status=HeadToHeadTable.STATUS_READY, then=Value(1)),
        default=Value(2), output_field=IntegerField(),
    )).order_by('page_priority', '-created_at', '-pk')
    return {
        'public': public, 'ongoing': ongoing,
        'history': own.filter(status__in=closed).order_by('-updated_at', '-pk'),
    }


def table_page(request, queries, serialize):
    scope = request.GET.get('scope')
    game_format = request.GET.get('format', 'all')
    if scope not in queries or game_format not in ('all', 'match', 'money'):
        raise ValueError('Invalid game list filter')
    offset, limit = page_bounds(request.GET)
    queryset = queries[scope]
    if game_format != 'all':
        queryset = queryset.filter(game_format=game_format)
    return queryset_page(queryset, serialize, offset, limit)
