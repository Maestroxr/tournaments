"""Tournament progression and worker ownership regressions from the outage."""
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from frontend.models import Task
from frontend.entry_lifecycle import expire_unstarted_tables
from frontend.task_runner import (
    expire_tournament_entry_deadlines, expire_unstarted_games, run_task,
    start_scheduled_tournaments,
)
from gamelink.models import GameLink
from tournaments.models import (
    DirectPlaySettings, Fixture, HeadToHeadTable, Knockout, Participant,
    Participation, Tournament, WalletTransaction,
)


class IncidentRecoveryTests(TestCase):
    def make_bracket(self, size=4, *, start=True):
        tournament = Tournament.objects.create(
            name=f'Recovery bracket {size}', published=True,
            starts_at=timezone.now() - timedelta(hours=1), min_players=2,
            podium_spec=['main.placements[0]'], prize_money=Decimal('100.00'),
        )
        stage = Knockout.objects.create(tournament=tournament, identifier='main')
        for index in range(size):
            user = User.objects.create(username=f'recovery-{tournament.pk}-{index}')
            Participation.objects.create(
                tournament=tournament, participant=Participant.get_or_create_for_user(user),
                slot_id=index,
            )
        if start:
            tournament.update_state()
            self.assertEqual(stage.fixtures.count(), size - 1)
        return tournament, stage

    def expired_bracket(self):
        tournament, stage = self.make_bracket()
        stage.fixtures.filter(level=0).update(
            playable_at=timezone.now() - timedelta(minutes=20),
        )
        return tournament, stage

    def expiry_task(self):
        return Task.objects.create(
            key='incident-expiry', name=Task.NAME_EXPIRE_TOURNAMENT_ENTRY_DEADLINES,
        )

    def test_normal_32_player_bracket_finishes_and_awards_once(self):
        tournament, stage = self.make_bracket(32)
        recorded = 0
        while tournament.current_stage is not None:
            fixtures = list(stage.fixtures.filter(level=stage.current_level))
            self.assertTrue(fixtures)
            for fixture in fixtures:
                self.assertIsNotNone(fixture.player1_id)
                self.assertIsNotNone(fixture.player2_id)
                with transaction.atomic():
                    fixture.score1, fixture.score2 = 5, 0
                    fixture.auto_confirmed = True
                    fixture.save(update_fields=['score1', 'score2', 'auto_confirmed'])
                    tournament.update_state()
                recorded += 1
                self.assertLessEqual(recorded, 31)
        self.assertEqual(recorded, 31)
        self.assertEqual(tournament.state, 'finished')
        tournament.update_state()
        prizes = WalletTransaction.objects.filter(
            tournament=tournament, kind=WalletTransaction.KIND_TOURNAMENT_PRIZE,
        )
        self.assertEqual(prizes.count(), 1)
        self.assertEqual(prizes.get().amount, Decimal('100.00'))

    def test_all_absent_cascade_finishes_without_awarding_a_prize(self):
        tournament, stage = self.make_bracket(8)
        with transaction.atomic():
            stage.fixtures.filter(level=0).update(
                admin_result='double_no_show', admin_resolved_at=timezone.now(),
            )
            tournament.update_state()
        self.assertIsNone(tournament.current_stage)
        self.assertFalse(WalletTransaction.objects.filter(
            tournament=tournament, kind=WalletTransaction.KIND_TOURNAMENT_PRIZE,
        ).exists())

    def test_one_survivor_cascade_awards_once_in_the_same_call(self):
        tournament, stage = self.make_bracket(8)
        first = stage.fixtures.filter(level=0).order_by('pk').first()
        with transaction.atomic():
            stage.fixtures.filter(level=0).exclude(pk=first.pk).update(
                admin_result='double_no_show', admin_resolved_at=timezone.now(),
            )
            Fixture.objects.filter(pk=first.pk).update(
                admin_result='advance', admin_winner_id=first.player1_id,
                admin_resolved_at=timezone.now(),
            )
            tournament.update_state()
        self.assertIsNone(tournament.current_stage)
        prizes = WalletTransaction.objects.filter(
            tournament=tournament, kind=WalletTransaction.KIND_TOURNAMENT_PRIZE,
        )
        self.assertEqual(prizes.count(), 1)
        self.assertEqual(prizes.get().user_id, first.player1.user_id)
        tournament.update_state()
        self.assertEqual(prizes.count(), 1)

    def test_failed_expiry_batch_keeps_error_and_retry_attempt(self):
        self.expired_bracket()
        task = self.expiry_task()
        with patch('gamelink.views._resolve_double_no_show_locked',
                   side_effect=RuntimeError('injected fixture failure')) as resolver:
            self.assertFalse(run_task(task.pk))
        self.assertEqual(resolver.call_count, 2)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_PENDING)
        self.assertEqual(task.attempts, 1)
        self.assertIn('expiry failed for fixtures', task.last_error)
        self.assertGreater(task.run_at, timezone.now())

    def test_one_failed_fixture_does_not_rollback_an_independent_fixture(self):
        _, stage = self.expired_bracket()
        first, second = list(stage.fixtures.filter(level=0).order_by('pk'))
        from gamelink.views import _resolve_double_no_show_locked

        def resolve(fixture, link, now):
            if fixture.pk == first.pk:
                raise RuntimeError('injected first fixture failure')
            return _resolve_double_no_show_locked(fixture, link, now)

        with patch('gamelink.views._resolve_double_no_show_locked', side_effect=resolve):
            self.assertFalse(run_task(self.expiry_task().pk))
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.admin_result, '')
        self.assertEqual(second.admin_result, 'double_no_show')

    def test_lost_lease_stops_expiry_without_resolving_a_fixture(self):
        self.expired_bracket()
        heartbeat = Mock(return_value=False)
        with patch('gamelink.views._resolve_double_no_show_locked') as resolver:
            self.assertIs(expire_tournament_entry_deadlines(heartbeat=heartbeat), False)
        heartbeat.assert_called_once()
        resolver.assert_not_called()

    def test_lost_lease_between_fixtures_keeps_new_owner_untouched(self):
        self.expired_bracket()
        task = self.expiry_task()
        replacement = uuid.uuid4()

        def resolve(fixture, link, now):
            Task.objects.filter(pk=task.pk).update(lease_token=replacement)
            return False

        with patch('gamelink.views._resolve_double_no_show_locked', side_effect=resolve) as resolver:
            self.assertFalse(run_task(task.pk))
        resolver.assert_called_once()
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_RUNNING)
        self.assertEqual(task.lease_token, replacement)
        self.assertEqual(task.last_error, '')

    def test_empty_expiry_batch_is_a_successful_noop(self):
        task = self.expiry_task()
        self.assertTrue(run_task(task.pk))
        task.refresh_from_db()
        self.assertEqual(task.last_error, '')
        self.assertEqual(task.attempts, 0)

    def test_paused_tournament_is_excluded_before_candidate_processing(self):
        tournament, stage = self.expired_bracket()
        Tournament.objects.filter(pk=tournament.pk).update(entry_deadline_paused=True)
        heartbeat = Mock(return_value=True)
        self.assertEqual(expire_tournament_entry_deadlines(heartbeat=heartbeat), 0)
        heartbeat.assert_not_called()
        self.assertFalse(stage.fixtures.exclude(admin_result='').exists())

    def test_pause_after_candidate_selection_is_rechecked_under_lock(self):
        tournament, stage = self.expired_bracket()

        def pause():
            Tournament.objects.filter(pk=tournament.pk).update(entry_deadline_paused=True)
            return True

        self.assertEqual(expire_tournament_entry_deadlines(heartbeat=pause), 0)
        self.assertFalse(stage.fixtures.exclude(admin_result='').exists())

    def test_bound_and_authorized_rooms_do_not_fill_expiry_batch(self):
        _, stage = self.expired_bracket()
        first, eligible = list(stage.fixtures.filter(level=0).order_by('pk'))
        older = timezone.now() - timedelta(hours=2)
        Fixture.objects.filter(pk=first.pk).update(playable_at=older)
        GameLink.objects.create(
            fixture=first, status='playing', expires_at=timezone.now(),
        )
        for link_fields in (
            {'external_room_id': str(uuid.uuid4())},
            {'entry_authorized_at': timezone.now()},
        ):
            fixture = Fixture.objects.create(
                mode=stage, level=0, player1=first.player1, player2=first.player2,
                playable_at=older,
            )
            GameLink.objects.create(fixture=fixture, expires_at=timezone.now(), **link_fields)
        with patch('frontend.task_runner.ENTRY_EXPIRY_BATCH_SIZE', 1), patch(
            'gamelink.views._resolve_double_no_show_locked', return_value=True,
        ) as resolver:
            self.assertEqual(expire_tournament_entry_deadlines(heartbeat=None), 1)
        self.assertEqual(resolver.call_args.args[0].pk, eligible.pk)

    def test_blocked_candidate_page_cannot_starve_a_later_playable_fixture(self):
        _, stage = self.expired_bracket()
        first, eligible = list(stage.fixtures.filter(level=0).order_by('pk'))
        with patch('frontend.task_runner.ENTRY_EXPIRY_BATCH_SIZE', 1), \
                patch('frontend.task_runner._personally_ready_fixture_ids', return_value={eligible.pk}), \
                patch('gamelink.views._resolve_double_no_show_locked', return_value=True) as resolver:
            skipped = expire_tournament_entry_deadlines(heartbeat=None, bounded=True)
            self.assertEqual(skipped['processed'], 0)
            self.assertEqual(skipped['continuation']['cursor'], first.pk)
            resumed = expire_tournament_entry_deadlines(heartbeat=None, bounded=True, **skipped['continuation'])
        self.assertEqual(resumed['processed'], 1)
        self.assertIsNone(resumed['continuation'])
        resolver.assert_called_once()
        self.assertEqual(resolver.call_args.args[0].pk, eligible.pk)

    def test_start_scanner_stops_when_lease_is_lost(self):
        tournament, stage = self.make_bracket(start=False)
        self.assertIs(start_scheduled_tournaments(heartbeat=lambda: False), False)
        self.assertFalse(stage.fixtures.exists())
        tournament.refresh_from_db()
        self.assertTrue(tournament.published)

    def test_invalid_start_does_not_block_later_candidate_pages(self):
        from frontend.api import _start_tournament_at_capacity
        cups = [self.make_bracket(start=False) for _ in range(3)]
        task = Task.objects.create(key='start-fairness', name=Task.NAME_START_SCHEDULED_TOURNAMENTS)

        def start(tournament):
            if tournament.pk == cups[0][0].pk:
                raise ValidationError('invalid first draw')
            return _start_tournament_at_capacity(tournament)

        with patch('frontend.task_runner.START_BATCH_SIZE', 1), \
                patch('frontend.api._start_tournament_at_capacity', side_effect=start):
            self.assertFalse(run_task(task.pk))
            task.refresh_from_db()
            self.assertEqual(task.kwargs['cursor'], cups[0][0].pk)
            for _ in range(2):
                Task.objects.filter(pk=task.pk).update(run_at=timezone.now())
                self.assertTrue(run_task(task.pk))
        self.assertFalse(cups[0][1].fixtures.exists())
        self.assertTrue(cups[1][1].fixtures.exists())
        self.assertTrue(cups[2][1].fixtures.exists())
        task.refresh_from_db()
        self.assertEqual(task.kwargs, {})  # The next cycle retries the invalid first cup too.

    def test_start_scanner_does_not_lock_started_tournaments(self):
        self.make_bracket()
        heartbeat = Mock(return_value=True)
        self.assertEqual(start_scheduled_tournaments(heartbeat=heartbeat), 0)
        heartbeat.assert_not_called()

    def test_invalid_scheduled_start_remains_open_with_retry_error(self):
        tournament, stage = self.make_bracket(start=False)
        task = Task.objects.create(key='scheduled-start', name=Task.NAME_START_SCHEDULED_TOURNAMENTS)
        with patch('frontend.api._start_tournament_at_capacity', side_effect=ValidationError('invalid draw')):
            self.assertFalse(run_task(task.pk))
        task.refresh_from_db()
        tournament.refresh_from_db()
        self.assertEqual(task.attempts, 1)
        self.assertIn('start validation failed', task.last_error)
        self.assertTrue(tournament.published)
        self.assertFalse(stage.fixtures.exists())


class DirectPlayWorkerRecoveryTests(TestCase):
    def setUp(self):
        DirectPlaySettings.load()
        self.host = User.objects.create(username='worker-host')
        self.guest = User.objects.create(username='worker-guest')
        self.sequence = 0
        WalletTransaction.create_entry(
            user=self.host, amount=1000, kind=WalletTransaction.KIND_DEPOSIT,
        )

    def table(self, *, status='open', legacy=False):
        self.sequence += 1
        table = HeadToHeadTable.objects.create(
            code=f'WK{self.sequence:04}', host=self.host,
            guest=self.guest if status != 'open' else None,
            mode='match', is_quick_match=True, game_format='legacy' if legacy else 'match',
            status=status, amount=100, fee_percent=5, fee_per_player=5,
            rules_snapshot={'fee_percent': 5, 'old_contract': True},
        )
        WalletTransaction.create_entry(
            user=self.host, amount=-100, kind=WalletTransaction.KIND_HEAD_TO_HEAD_ENTRY,
            head_to_head_table=table,
        )
        return table

    def test_worker_reconciles_unmatched_search_and_preserves_paired_contract(self):
        unmatched = self.table(legacy=True)
        paired = self.table(status='ready', legacy=True)
        original_contract = paired.rules_snapshot.copy()
        self.assertTrue(expire_unstarted_games(heartbeat=None))
        self.assertTrue(expire_unstarted_games(heartbeat=None))
        unmatched.refresh_from_db()
        paired.refresh_from_db()
        self.assertEqual(unmatched.status, 'cancelled')
        self.assertEqual(unmatched.settlement['reason'], 'legacy_search_closed')
        self.assertEqual(paired.status, 'ready')
        self.assertEqual(paired.rules_snapshot, original_contract)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), 900)
        self.assertEqual(unmatched.wallet_transactions.filter(
            kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND,
        ).count(), 1)

    def test_worker_does_not_reconcile_after_losing_lease(self):
        table = self.table(legacy=True)
        self.assertIs(expire_unstarted_games(heartbeat=lambda: False), False)
        table.refresh_from_db()
        self.assertEqual(table.status, 'open')
        self.assertEqual(WalletTransaction.balance_for_user(self.host), 900)

    def test_remote_failure_is_visible_without_cancelling_game_or_blocking_other_expiry(self):
        remote_table = self.table(status='playing')
        open_table = self.table()
        old = timezone.now() - timedelta(hours=1)
        HeadToHeadTable.objects.filter(pk__in=[remote_table.pk, open_table.pk]).update(
            created_at=old, updated_at=old,
        )
        task = Task.objects.create(key='direct-expiry', name=Task.NAME_EXPIRE_UNSTARTED_GAMES)
        with patch('frontend.entry_lifecycle.remote_expiry', side_effect=OSError('offline')):
            self.assertFalse(run_task(task.pk))
        remote_table.refresh_from_db()
        open_table.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(remote_table.status, 'playing')
        self.assertEqual(open_table.status, 'cancelled')
        self.assertIn('entry expiry failed for tables', task.last_error)
        self.assertEqual(task.attempts, 1)
        self.assertEqual(WalletTransaction.balance_for_user(self.host), 900)

    def test_lease_lost_during_remote_request_prevents_local_cancellation(self):
        table = self.table(status='playing')
        HeadToHeadTable.objects.filter(pk=table.pk).update(
            updated_at=timezone.now() - timedelta(hours=1),
        )
        with patch('frontend.entry_lifecycle.remote_expiry', return_value='cancelled'):
            heartbeat = Mock(side_effect=[True, False])
            self.assertIs(expire_unstarted_tables(heartbeat=heartbeat), False)
        table.refresh_from_db()
        self.assertEqual(table.status, 'playing')
        self.assertEqual(WalletTransaction.balance_for_user(self.host), 900)

    def test_user_scoped_expiry_does_not_cancel_an_unrelated_search(self):
        table = self.table()
        HeadToHeadTable.objects.filter(pk=table.pk).update(
            created_at=timezone.now() - timedelta(hours=1),
        )
        self.assertTrue(expire_unstarted_tables(user_id=self.guest.pk))
        table.refresh_from_db()
        self.assertEqual(table.status, 'open')
