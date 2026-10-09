"""Filter and order in SQL before building five card summaries."""
from decimal import Decimal

from django.db.models import (
    Case, CharField, Count, DecimalField, Exists, F, FloatField, OuterRef,
    Q, Subquery, Sum, Value, When,
)
from django.db.models.functions import Cast, Coalesce, Floor, Greatest, Mod, NullIf, Round

from tournaments.models import Fixture, Mode, Participation, WalletTransaction

from .tournament_list_reads import _confirmed_filter, _fixture_reads, tournament_list_snapshots
from .list_pages import page_bounds, page_payload


def _with_state(qs):
    fixtures = _fixture_reads().filter(mode__tournament_id=OuterRef('pk'))
    empty_stages = Mode.objects.non_polymorphic().filter(tournament_id=OuterRef('pk')).filter(
        ~Exists(Fixture.objects.filter(mode_id=OuterRef('pk'))),
    )
    return qs.alias(
        page_has_fixtures=Exists(fixtures),
        page_has_pending=Exists(fixtures.filter(~_confirmed_filter())),
        page_has_empty_stage=Exists(empty_stages),
    ).alias(page_state=Case(
        When(page_has_fixtures=False, then=Value('open')),
        When(Q(page_has_pending=True) | Q(page_has_empty_stage=True), then=Value('active')),
        default=Value('finished'), output_field=CharField(),
    ))


def _personal_loss(user):
    participation = Participation.objects.filter(
        tournament_id=OuterRef('mode__tournament_id'), participant__user_id=user.pk,
    ).order_by('slot_id').values('participant_id')[:1]
    return _fixture_reads().filter(mode__tournament_id=OuterRef('pk')).annotate(
        page_participant_id=Subquery(participation),
    ).filter(_confirmed_filter()).filter(
        Q(player1_id=F('page_participant_id')) | Q(player2_id=F('page_participant_id')),
    ).filter(
        Q(admin_result='double_no_show')
        | (Q(admin_winner__isnull=False) & ~Q(admin_winner_id=F('page_participant_id')))
        | Q(player1_id=F('page_participant_id'), score1__lt=F('score2'))
        | Q(player2_id=F('page_participant_id'), score2__lt=F('score1')),
    )


def _with_prize(qs):
    money = DecimalField(max_digits=16, decimal_places=2)
    net = WalletTransaction.objects.filter(
        tournament_id=OuterRef('pk'), kind__in=(
            WalletTransaction.KIND_TOURNAMENT_ENTRY, WalletTransaction.KIND_TOURNAMENT_REFUND,
        ),
    ).order_by().values('tournament_id').annotate(total=Sum('amount')).values('total')
    collected = Greatest(-Coalesce(Subquery(net), Value(Decimal('0.00'))), Value(Decimal('0.00')))
    # Match Decimal.quantize's half-even cents, including on SQLite where
    # division of two integer-valued NUMERIC expressions would truncate.
    qs = qs.alias(page_pool_cents=Round(
        Cast(collected, FloatField()) * (Value(100.0) - Cast('platform_fee_percent', FloatField())), 6,
    )).alias(
        page_pool_floor=Floor('page_pool_cents'),
        page_pool_fraction=F('page_pool_cents') - Floor('page_pool_cents'),
        page_pool_parity=Mod(Floor('page_pool_cents'), Value(2.0)),
    )
    rounded_pool = Case(
        When(page_pool_fraction=0.5, page_pool_parity=0.0, then=F('page_pool_floor')),
        default=Round('page_pool_cents'), output_field=FloatField(),
    ) / Value(100.0)
    return qs.alias(page_prize=Case(
        When(prize_type='text', then=Value(Decimal('0.00'))),
        When(Q(prize_money__gt=0) | Q(entry_fee__lte=0), then=F('prize_money')),
        default=rounded_pool,
        output_field=money,
    ))


def tournament_page(qs, request, serialize):
    params = request.GET
    try:
        offset, limit = page_bounds(params)
        points = params.get('points')
        points = int(points) if points else None
        if points is not None and not 1 <= points <= 32767:
            raise ValueError('Invalid points')
    except (TypeError, ValueError) as error:
        raise ValueError('Invalid pagination or match length') from error
    state = params.get('state', '')
    scope = params.get('scope', 'public')
    buy_in = params.get('buy_in', 'all')
    sort = params.get('sort', 'recent')
    joined = params.get('joined', '0')
    if (state not in ('', 'open', 'active', 'finished', 'live')
            or scope not in ('public', 'ongoing', 'history')
            or buy_in not in ('all', 'free', 'paid')
            or sort not in ('recent', 'prize', 'filling') or joined not in ('0', '1')):
        raise ValueError('Invalid tournament filter')
    qs = _with_state(qs)
    if scope != 'public' or joined == '1':
        if not request.user.is_authenticated:
            qs = qs.none()
        else:
            qs = qs.filter(Exists(Participation.objects.filter(
                tournament_id=OuterRef('pk'), participant__user_id=request.user.pk,
            )))
    if scope == 'ongoing':
        qs = qs.exclude(page_state='finished')
    elif scope == 'history' and request.user.is_authenticated:
        qs = qs.alias(page_has_loss=Exists(_personal_loss(request.user))).filter(
            Q(page_state='finished') | Q(page_has_loss=True),
        )
    if state == 'live':
        qs = qs.filter(Q(page_state='active') | Q(page_state='open', registration_closed_at__isnull=True))
    elif state == 'open':
        qs = qs.filter(page_state='open', registration_closed_at__isnull=True)
    elif state:
        qs = qs.filter(page_state=state)
    # Options describe the entire selected status/ownership, not just this page.
    lengths = list(qs.order_by('target_points').values_list('target_points', flat=True).distinct())
    if buy_in != 'all':
        qs = qs.filter(entry_fee__lte=0) if buy_in == 'free' else qs.filter(entry_fee__gt=0)
    if points is not None:
        qs = qs.filter(target_points=points)
    query = params.get('q', '').strip()
    if query or sort == 'prize':
        qs = _with_prize(qs)
    if query:
        qs = qs.alias(
            page_entry_text=Cast('entry_fee', CharField()),
            page_points_text=Cast('target_points', CharField()),
            page_prize_text=Cast('page_prize', CharField()),
        ).filter(
            Q(name__icontains=query) | Q(prize_text__icontains=query)
            | Q(time_control__icontains=query) | Q(page_entry_text__icontains=query)
            | Q(page_points_text__icontains=query) | Q(page_prize_text__icontains=query),
        )
    if sort == 'filling':
        roster = Participation.objects.filter(tournament_id=OuterRef('pk')).order_by().values(
            'tournament_id',
        ).annotate(total=Count('pk')).values('total')
        qs = qs.alias(page_occupancy=Cast(Coalesce(Subquery(roster), Value(0)), FloatField())
                      / Cast(Coalesce(NullIf('max_players', Value(0)), Value(8)), FloatField()))
        order = ('-page_occupancy', '-starts_at', '-pk')
    elif sort == 'prize':
        order = ('-page_prize', '-starts_at', '-pk')
    else:
        order = ('-starts_at', '-pk')
    count = qs.count()
    snapshots = tournament_list_snapshots(qs.order_by(*order)[offset:offset + limit], request.user)
    return page_payload(
        [serialize(snapshot.tournament, request, read_snapshot=snapshot) for snapshot in snapshots],
        count, offset, limit, match_lengths=lengths,
    )
