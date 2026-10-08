"""Batched card summaries; full bracket history belongs to detail/progress reads.

All data lives for one GET only. Ticket issuance and writes use fresh locked rows.
"""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, F, IntegerField, Min, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Cast, Coalesce, Floor

from tournaments.models import Fixture, Mode, Participation, TournamentRegistration, WalletTransaction

from .tournament_reads import TournamentReadSnapshot


class TournamentListReadSnapshot(TournamentReadSnapshot):
    """The serializer's read interface, backed by summaries and personal fixtures."""

    def __init__(self, tournament, roster, stages, stage_summaries):
        self.tournament = tournament
        self._participant_count = roster.get('total', 0)
        self.required_confirmations = 1 + roster.get('online', 0) // 2
        self.participations = []
        self.registrations = []
        self.fixtures = []
        self._collected_entry_fees = Decimal('0.00')
        self._has_confirmed_loss = False
        self.current_stage = None
        self.current_level = None
        has_fixtures = False
        for stage in stages:
            summary = stage_summaries.get(stage.pk)
            has_fixtures = has_fixtures or summary is not None
            if self.current_stage is None and (summary is None or summary['pending_level'] is not None):
                self.current_stage = stage
                self.current_level = summary['pending_level'] if summary else 0
        self.state = (
            'draft' if not tournament.published else
            'open' if not has_fixtures else
            'active' if self.current_stage is not None else 'finished'
        )

    @property
    def participant_count(self):
        return self._participant_count

    def has_confirmed_loss(self, participation):
        return self._has_confirmed_loss

    def is_confirmed(self, fixture):
        return fixture.confirmed_result(
            confirmation_count=fixture.read_confirmation_count,
            required_confirmations=fixture.read_required_confirmations,
        )


def _fixture_reads(tournament_ids):
    confirmations = Fixture.confirmations.through.objects.filter(
        fixture_id=OuterRef('pk'),
    ).order_by().values('fixture_id').annotate(total=Count('pk')).values('total')
    online = Participation.objects.filter(
        tournament_id=OuterRef('mode__tournament_id'), participant__user__isnull=False,
    ).order_by().values('tournament_id').annotate(total=Count('pk')).values('total')
    required = Cast(
        Floor(Coalesce(Subquery(online), Value(0)) / Value(2.0)) + Value(1),
        output_field=IntegerField(),
    )
    return Fixture.objects.filter(mode__tournament_id__in=tournament_ids).annotate(
        read_confirmation_count=Coalesce(Subquery(confirmations), Value(0)),
        read_required_confirmations=required,
    )


def _confirmed_filter():
    return Fixture.confirmed_result_filter(
        confirmation_count='read_confirmation_count',
        required_confirmations=F('read_required_confirmations'),
    )


def _load_personal_fixtures(snapshots, user):
    active_ids = [pk for pk, snapshot in snapshots.items() if snapshot.state == 'active']
    if not active_ids:
        return
    # No extras, audits, round names or completed games are materialized here.
    pending = _fixture_reads(active_ids).filter(~_confirmed_filter()).select_related(
        'mode', 'player1__user', 'player2__user',
    ).only(
        'pk', 'mode_id', 'mode__tournament_id', 'level', 'player1_id', 'player2_id',
        'player1__user_id', 'player1__user__id', 'player2__user_id', 'player2__user__id',
        'score1', 'score2', 'auto_confirmed', 'admin_result', 'admin_winner_id', 'playable_at',
    ).order_by('mode_id', 'level', 'pk')
    own = list(pending.filter(Q(player1__user_id=user.pk) | Q(player2__user_id=user.pk)))
    opponent_ids = {
        player.user_id for fixture in own for player in (fixture.player1, fixture.player2)
        if player is not None and player.user_id is not None and player.user_id != user.pk
    }
    # A candidate can only be offered when it is also the opponent's earliest
    # unresolved pairing. Missing-player and ambiguous pairings still block it.
    opponent_tournaments = {fixture.mode.tournament_id for fixture in own}
    others = pending.filter(
        mode__tournament_id__in=opponent_tournaments,
    ).filter(Q(player1__user_id__in=opponent_ids) | Q(player2__user_id__in=opponent_ids)).exclude(
        pk__in=[fixture.pk for fixture in own],
    ) if opponent_ids else []
    for fixture in [*own, *others]:
        snapshot = snapshots[fixture.mode.tournament_id]
        fixture.mode.tournament = snapshot.tournament
        snapshot.fixtures.append(fixture)


def _load_losses(snapshots, user):
    own_ids = [pk for pk, snapshot in snapshots.items()
               if snapshot.state in ('active', 'finished') and snapshot.participation_for(user) is not None]
    if not own_ids:
        return
    own_participant = Participation.objects.filter(
        tournament_id=OuterRef('mode__tournament_id'), participant__user_id=user.pk,
    ).order_by('slot_id').values('participant_id')[:1]
    losses = _fixture_reads(own_ids).annotate(
        read_participant_id=Subquery(own_participant),
    ).filter(_confirmed_filter()).filter(
        Q(player1_id=F('read_participant_id')) | Q(player2_id=F('read_participant_id')),
    ).filter(
        Q(admin_result='double_no_show')
        | (Q(admin_winner__isnull=False) & ~Q(admin_winner_id=F('read_participant_id')))
        | Q(player1_id=F('read_participant_id'), score1__lt=F('score2'))
        | Q(player2_id=F('read_participant_id'), score2__lt=F('score1')),
    ).order_by().values_list('mode__tournament_id', flat=True).distinct()
    for tournament_id in losses:
        snapshots[tournament_id]._has_confirmed_loss = True


def tournament_list_snapshots(tournaments, user, *, state=None):
    """A bounded number of reads for the list, regardless of tournament count."""
    tournaments = list(tournaments)
    if not tournaments:
        return []
    tournament_ids = [tournament.pk for tournament in tournaments]
    rosters = {row['tournament_id']: row for row in Participation.objects.filter(
        tournament_id__in=tournament_ids,
    ).order_by().values('tournament_id').annotate(
        total=Count('pk'), online=Count('pk', filter=Q(participant__user__isnull=False)),
    )}
    stages = defaultdict(list)
    # Card fields need only stage IDs, not polymorphic subclasses or round names.
    for stage in Mode.objects.non_polymorphic().filter(tournament_id__in=tournament_ids).only(
        'pk', 'tournament_id',
    ).order_by('pk'):
        stages[stage.tournament_id].append(stage)
    summaries = {row['mode_id']: row for row in _fixture_reads(tournament_ids).order_by().values(
        'mode_id',
    ).annotate(pending_level=Min('level', filter=~_confirmed_filter()))}
    snapshots = {}
    for tournament in tournaments:
        snapshot = TournamentListReadSnapshot(
            tournament, rosters.get(tournament.pk, {}), stages[tournament.pk], summaries,
        )
        if not state or snapshot.state == state:
            snapshots[tournament.pk] = snapshot
    if not snapshots:
        return []
    selected_ids = list(snapshots)
    participations = Participation.objects.filter(tournament_id__in=selected_ids)
    if not user.is_authenticated or not user.is_staff:
        visible = Q(podium_position__isnull=False)
        if user.is_authenticated:
            visible |= Q(participant__user_id=user.pk)
        participations = participations.filter(visible)
    for participation in participations.select_related('participant').only(
        'pk', 'tournament_id', 'participant_id', 'podium_position',
        'participant__name', 'participant__user_id',
    ):
        snapshots[participation.tournament_id].participations.append(participation)
    if user.is_authenticated:
        registrations = TournamentRegistration.objects.filter(tournament_id__in=selected_ids)
        if not user.is_staff:
            registrations = registrations.filter(participant__user_id=user.pk)
        for registration in registrations.select_related('participant').only(
            'pk', 'tournament_id', 'participant_id', 'status', 'checked_in_at', 'payment_status',
            'participant__user_id',
        ):
            snapshots[registration.tournament_id].registrations.append(registration)
    fees = WalletTransaction.objects.filter(
        tournament_id__in=selected_ids, kind__in=(
            WalletTransaction.KIND_TOURNAMENT_ENTRY, WalletTransaction.KIND_TOURNAMENT_REFUND,
        ),
    ).order_by().values('tournament_id').annotate(total=Sum('amount'))
    for row in fees:
        net = row['total'] or Decimal('0.00')
        snapshots[row['tournament_id']]._collected_entry_fees = max(-net, Decimal('0.00'))
    if user.is_authenticated:
        _load_losses(snapshots, user)
        _load_personal_fixtures(snapshots, user)
    return list(snapshots.values())
