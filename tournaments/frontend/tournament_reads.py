"""Request-local tournament state for read-only JSON endpoints.

Never reuse this view after a write or to authorize a ticket. Mutation endpoints
resolve the tournament, round and confirmations afresh under their row locks.
"""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Exists, OuterRef, Subquery, Sum

from tournaments.models import Fixture, FixtureAudit, Knockout, WalletTransaction


class TournamentReadSnapshot:
    def __init__(self, tournament, user, *, include_live=False):
        self.tournament = tournament
        self.stages = list(tournament.stages.order_by('pk'))
        self.participations = list(
            tournament.participations.select_related('participant__user')
        )
        self.registrations = list(
            tournament.registrations.select_related('participant')
        )
        self.required_confirmations = 1 + sum(
            item.participant.user_id is not None for item in self.participations
        ) // 2
        confirmations = Fixture.confirmations.through.objects.filter(
            fixture_id=OuterRef('pk'), user_id=user.pk if user.is_authenticated else None,
        )
        started = FixtureAudit.objects.filter(
            fixture_id=OuterRef('pk'), action='live_started',
        ).order_by('created_at', 'pk')
        related = ['player1__user', 'player2__user']
        if include_live:
            related.append('game_link')
        self.fixtures = list(
            Fixture.objects.filter(mode__tournament=tournament)
            .select_related(*related).defer('player1__user__password', 'player2__user__password')
            .annotate(
                read_confirmation_count=Count('confirmations'),
                read_has_confirmed=Exists(confirmations),
                read_started_at=Subquery(started.values('created_at')[:1]),
            ).order_by('mode_id', 'level', 'pk')
        )
        self.by_stage = defaultdict(list)
        self.stage_levels = {}
        self.stage_current_levels = {}
        self.round_names = {}
        stages_by_id = {stage.pk: stage for stage in self.stages}
        for stage in self.stages:
            # These instances belong only to this response, never a write path.
            stage.tournament = tournament
        for fixture in self.fixtures:
            fixture.mode = stages_by_id[fixture.mode_id]
            self.by_stage[fixture.mode_id].append(fixture)
        self.current_stage = None
        for stage in self.stages:
            fixtures = self.by_stage[stage.pk]
            levels = max((item.level for item in fixtures), default=-1) + 1
            current = next(
                (item.level for item in fixtures if not self.is_confirmed(item)),
                levels,
            )
            self.stage_levels[stage.pk] = levels
            self.stage_current_levels[stage.pk] = current
            tree_count = sum(isinstance(item.extras, dict) and item.extras.get('tree') == 1
                             for item in fixtures)
            for level in range(levels):
                self.round_names[(stage.pk, level)] = (
                    stage.get_level_name(level, levels=levels, tree_fixture_count=tree_count)
                    if isinstance(stage, Knockout) else stage.get_level_name(level)
                )
            if self.current_stage is None and (levels == 0 or current < levels):
                self.current_stage = stage
        self.current_level = (
            self.stage_current_levels[self.current_stage.pk]
            if self.current_stage is not None else None
        )
        self.state = (
            'draft' if not tournament.published else
            'open' if not self.fixtures else
            'active' if self.current_stage is not None else 'finished'
        )

    def is_confirmed(self, fixture):
        return fixture.confirmed_result(
            confirmation_count=fixture.read_confirmation_count,
            required_confirmations=self.required_confirmations,
        )

    @property
    def participant_count(self):
        return len(self.participations)

    def participation_for(self, user):
        return next((item for item in self.participations
                     if item.participant.user_id == user.pk), None)

    def registration_for(self, user):
        return next((item for item in self.registrations
                     if item.participant.user_id == user.pk), None)

    @property
    def podium_participations(self):
        return sorted(
            (item for item in self.participations if item.podium_position is not None),
            key=lambda item: item.podium_position,
        )

    def has_confirmed_loss(self, participation):
        participant_id = participation.participant_id
        return any(
            participant_id in (item.player1_id, item.player2_id)
            and self.is_confirmed(item) and (
                item.admin_result == 'double_no_show'
                or (item.admin_winner_id is not None and item.admin_winner_id != participant_id)
                or (item.score1 is not None and item.score2 is not None and (
                    (item.player1_id == participant_id and item.score1 < item.score2)
                    or (item.player2_id == participant_id and item.score2 < item.score1)
                ))
            ) for item in self.fixtures
        )

    @property
    def collected_entry_fees(self):
        if not hasattr(self, '_collected_entry_fees'):
            net = self.tournament.wallet_transactions.filter(kind__in=(
                WalletTransaction.KIND_TOURNAMENT_ENTRY,
                WalletTransaction.KIND_TOURNAMENT_REFUND,
            )).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            self._collected_entry_fees = max(-net, Decimal('0.00'))
        return self._collected_entry_fees

    @property
    def effective_prize_money(self):
        tournament = self.tournament
        if tournament.prize_money > 0 or tournament.entry_fee <= 0:
            return tournament.prize_money
        return (self.collected_entry_fees * (Decimal('100.00') - tournament.platform_fee_percent)
                / Decimal('100.00')).quantize(Decimal('0.01'))

    def current_user_fixtures(self, user):
        if not user.is_authenticated or self.state != 'active':
            return []
        if not hasattr(self, '_personal_current_by_user'):
            from gamelink.playability import earliest_unresolved_fixtures
            assigned = defaultdict(list)
            for fixture in self.fixtures:
                if self.is_confirmed(fixture):
                    continue
                for player in (fixture.player1, fixture.player2):
                    if player is not None and player.user_id is not None:
                        assigned[player.user_id].append(fixture)
            self._personal_current_by_user = {
                user_id: earliest_unresolved_fixtures(rows, user_id, is_confirmed=lambda _: False)
                for user_id, rows in assigned.items()
            }
        return self._personal_current_by_user.get(user.pk, [])
