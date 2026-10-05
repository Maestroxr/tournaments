import uuid
from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone

from frontend.entry_lifecycle import expire_unstarted_tables
from frontend.models import Task
from frontend.task_runner import HANDLERS, TaskRunOutcome, run_task
from frontend.tasks import enqueue_admin_command, schedule_tasks
from gamelink.commands import queue_admin_command
from gamelink.models import AdminGameCommand, GameLink
from tournaments.models import (
    DirectPlaySettings, Fixture, HeadToHeadTable, Knockout, Tournament, WalletTransaction,
)


class TaskArgumentTests(SimpleTestCase):
    def test_invalid_limit_does_not_query_the_database(self):
        for limit in (0, -1):
            with self.subTest(limit=limit), self.assertRaisesMessage(CommandError, 'positive'):
                call_command('run_tasks', limit=limit)


@override_settings(
    GAMELINK_BACKGAMMON_URL='https://game.example.test',
    GAMELINK_COMMAND_SECRET='task-test-command-secret-0123456789',
    GAMELINK_ISSUER='task-tests',
)
class TournamentTaskTests(TransactionTestCase):
    def setUp(self):
        Task.objects.all().delete()
        DirectPlaySettings.load()
        self.user = User.objects.create_user('task-host')
        self.tournament = Tournament.objects.create(
            name='Task cup', podium_spec=[], starts_at=timezone.now() + timedelta(hours=1),
        )
        self.mode = Knockout.objects.create(tournament=self.tournament)
        schedule_tasks()

    def link(self):
        fixture = Fixture.objects.create(mode=self.mode, level=0)
        return GameLink.objects.create(
            fixture=fixture, expires_at=timezone.now() + timedelta(hours=1),
            external_room_id=str(uuid.uuid4()),
        )

    def command(self):
        return AdminGameCommand.objects.create(game_link=self.link(), body={'action': 'score_update'})

    def table(self):
        table = HeadToHeadTable.objects.create(
            code='TASK01', host=self.user, mode='match', amount='100',
            fee_percent='5', fee_per_player='5',
        )
        HeadToHeadTable.objects.filter(pk=table.pk).update(
            created_at=timezone.now() - timedelta(minutes=11),
        )
        WalletTransaction.create_entry(
            user=self.user, amount=1000, kind=WalletTransaction.KIND_DEPOSIT,
        )
        WalletTransaction.create_entry(
            user=self.user, amount=-100, kind=WalletTransaction.KIND_HEAD_TO_HEAD_ENTRY,
            head_to_head_table=table,
        )
        return table

    def successful_response(self, open_url):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        open_url.return_value = response

    @override_settings(GAMELINK_ENABLED=True)
    def test_queue_creates_durable_task_in_the_same_transaction(self):
        command = queue_admin_command(self.link(), {'action': 'finish'})
        task = Task.objects.get(key=f'admin-command:{command.pk}')
        self.assertEqual(task.kwargs, {'command_id': str(command.pk)})
        self.assertEqual(task.status, 'pending')
        self.assertEqual(enqueue_admin_command(command.pk).pk, task.pk)
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                rolled_back = queue_admin_command(self.link(), {'action': 'finish'})
                raise RuntimeError('rollback')
        self.assertFalse(AdminGameCommand.objects.filter(pk=rolled_back.pk).exists())
        self.assertFalse(Task.objects.filter(key=f'admin-command:{rolled_back.pk}').exists())

    def test_scheduling_backfills_legacy_commands_without_duplicates(self):
        command = self.command()
        schedule_tasks()
        schedule_tasks()
        self.assertEqual(Task.objects.filter(key=f'admin-command:{command.pk}').count(), 1)
        self.assertEqual(Task.objects.filter(name='expire_unstarted_games').count(), 1)

    @patch('gamelink.commands.urlopen')
    def test_retry_waits_until_due_and_refunds_only_once(self, open_url):
        table = self.table()
        command = self.command()
        task = enqueue_admin_command(command.pk)
        open_url.side_effect = URLError('offline')
        with self.assertRaises(CommandError):
            call_command('run_tasks', stdout=StringIO())
        table.refresh_from_db()
        command.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(table.status, 'cancelled')
        self.assertEqual(command.status, 'pending')
        self.assertEqual(task.status, 'pending')
        self.assertGreater(task.run_at, timezone.now())
        self.assertTrue(task.last_error)
        self.assertEqual(WalletTransaction.balance_for_user(self.user), 1000)
        call_command('run_tasks', stdout=StringIO())
        self.assertEqual(open_url.call_count, 1)

        open_url.side_effect = None
        self.successful_response(open_url)
        Task.objects.filter(pk=task.pk).update(run_at=timezone.now() - timedelta(seconds=1))
        call_command('run_tasks', stdout=StringIO())
        call_command('run_tasks', stdout=StringIO())
        command.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(command.status, 'delivered')
        self.assertEqual(task.status, 'done')
        self.assertEqual(task.last_error, '')
        self.assertEqual(open_url.call_count, 2)
        self.assertEqual(WalletTransaction.balance_for_user(self.user), 1000)
        self.assertEqual(table.wallet_transactions.filter(
            kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND,
        ).count(), 1)

    @patch('gamelink.commands.urlopen')
    def test_one_failed_task_does_not_prevent_another_task(self, open_url):
        self.successful_response(open_url)
        command = self.command()
        enqueue_admin_command(command.pk)
        failed_expiry = MagicMock(side_effect=RuntimeError('expiry unavailable'))
        with patch.dict(HANDLERS, {'expire_unstarted_games': failed_expiry}):
            with self.assertRaises(CommandError):
                call_command('run_tasks', stdout=StringIO())
        command.refresh_from_db()
        self.assertEqual(command.status, 'delivered')
        expiry = Task.objects.get(name='expire_unstarted_games')
        self.assertEqual(expiry.status, 'pending')
        self.assertIn('expiry unavailable', expiry.last_error)

    def test_expiry_reschedules_the_same_task(self):
        self.table()
        expiry = Task.objects.get(name='expire_unstarted_games')
        self.assertTrue(run_task(expiry.pk))
        expiry.refresh_from_db()
        self.assertEqual(expiry.status, 'pending')
        self.assertGreater(expiry.run_at, timezone.now() + timedelta(seconds=50))
        self.assertEqual(expiry.attempts, 0)
        self.assertIsNotNone(expiry.last_finished_at)
        self.assertEqual(Task.objects.filter(name='expire_unstarted_games').count(), 1)

    def test_expiry_stops_when_lease_is_lost(self):
        table = self.table()
        expire_unstarted_tables(heartbeat=lambda: False)
        table.refresh_from_db()
        self.assertEqual(table.status, 'open')
        self.assertEqual(WalletTransaction.balance_for_user(self.user), 900)

    def test_worker_cannot_claim_live_lease(self):
        task = enqueue_admin_command(self.command().pk)
        Task.objects.filter(pk=task.pk).update(
            status='running', lease_token=uuid.uuid4(),
            locked_until=timezone.now() + timedelta(minutes=1),
        )
        execute = MagicMock(return_value=True)
        with patch.dict(HANDLERS, {'deliver_admin_command': execute}):
            self.assertFalse(run_task(task.pk))
        execute.assert_not_called()

    def test_crashed_worker_lease_is_recovered(self):
        task = enqueue_admin_command(self.command().pk)
        Task.objects.filter(pk=task.pk).update(
            status='running', lease_token=uuid.uuid4(),
            locked_until=timezone.now() - timedelta(seconds=1),
        )
        execute = MagicMock(return_value=True)
        with patch.dict(HANDLERS, {'deliver_admin_command': execute}):
            call_command('run_tasks', stdout=StringIO())
        execute.assert_called_once()
        task.refresh_from_db()
        self.assertEqual(task.status, 'done')

    def test_second_worker_cannot_execute_claimed_task(self):
        task = enqueue_admin_command(self.command().pk)
        def execute(**kwargs):
            self.assertFalse(run_task(task.pk))
            self.assertTrue(kwargs['heartbeat']())
            return True
        with patch.dict(HANDLERS, {'deliver_admin_command': execute}):
            self.assertTrue(run_task(task.pk))
        task.refresh_from_db()
        self.assertEqual(task.attempts, 1)

    def test_stale_worker_cannot_overwrite_new_owner(self):
        task = enqueue_admin_command(self.command().pk)
        replacement_token = uuid.uuid4()
        def execute(**kwargs):
            Task.objects.filter(pk=task.pk).update(lease_token=replacement_token)
            self.assertFalse(kwargs['heartbeat']())
            return True
        with patch.dict(HANDLERS, {'deliver_admin_command': execute}):
            self.assertFalse(run_task(task.pk))
        task.refresh_from_db()
        self.assertEqual(task.status, 'running')
        self.assertEqual(task.lease_token, replacement_token)

    @patch('gamelink.commands.urlopen')
    def test_cron_runner_honors_batch_limit(self, open_url):
        self.successful_response(open_url)
        # Isolate command delivery from all periodic work seeded by schedule_tasks.
        Task.objects.update(
            run_at=timezone.now() + timedelta(minutes=1),
        )
        for _ in range(3):
            enqueue_admin_command(self.command().pk)
        output = StringIO()
        call_command('run_tasks', limit=2, stdout=output)
        self.assertEqual(AdminGameCommand.objects.filter(status='delivered').count(), 2)
        self.assertEqual(AdminGameCommand.objects.filter(status='pending').count(), 1)
        self.assertEqual(open_url.call_count, 2)
        self.assertIn('count=2 completed=2 failed=0 deferred=0', output.getvalue())
        call_command('run_tasks', stdout=StringIO())
        self.assertEqual(AdminGameCommand.objects.filter(status='delivered').count(), 3)
        self.assertEqual(open_url.call_count, 3)

    @patch('gamelink.commands.urlopen')
    def test_stale_delivery_failure_cannot_reopen_completed_command(self, open_url):
        command = self.command()
        task = enqueue_admin_command(command.pk)
        def newer_worker_delivered(*args, **kwargs):
            AdminGameCommand.objects.filter(pk=command.pk).update(status='delivered')
            Task.objects.filter(pk=task.pk).update(status='done', lease_token=None)
            raise URLError('stale worker failed')
        open_url.side_effect = newer_worker_delivered
        self.assertFalse(run_task(task.pk))
        command.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(command.status, 'delivered')
        self.assertEqual(task.status, 'done')

    def test_retries_continue_after_many_failures_with_capped_backoff(self):
        task = enqueue_admin_command(self.command().pk)
        Task.objects.filter(pk=task.pk).update(attempts=500)
        before = timezone.now()
        with patch.dict(HANDLERS, {'deliver_admin_command': MagicMock(return_value=False)}):
            self.assertFalse(run_task(task.pk))
        task.refresh_from_db()
        self.assertEqual(task.status, 'pending')
        self.assertEqual(task.attempts, 501)
        self.assertGreaterEqual(task.run_at, before + timedelta(seconds=300))
        self.assertLessEqual(task.run_at, timezone.now() + timedelta(seconds=300))

    def test_runner_continues_after_unexpected_claim_error(self):
        enqueue_admin_command(self.command().pk)
        due_ids = list(Task.objects.values_list('pk', flat=True))
        self.assertGreater(len(due_ids), 1)
        failed_id = due_ids[0]

        def claim(task_id):
            if task_id == failed_id:
                raise RuntimeError('claim failed')
            return TaskRunOutcome.COMPLETED

        output = StringIO()
        with patch('frontend.management.commands.run_tasks.run_task_with_outcome',
                   side_effect=claim) as execute:
            with self.assertLogs('frontend.management.commands.run_tasks', level='ERROR'):
                with self.assertRaisesMessage(CommandError, str(failed_id)):
                    call_command('run_tasks', stdout=output)
        self.assertEqual(execute.call_count, len(due_ids))
        self.assertEqual(execute.call_args_list[0].args[0], failed_id)
        self.assertEqual({invocation.args[0] for invocation in execute.call_args_list}, set(due_ids))
        self.assertIn(
            f'count={len(due_ids)} completed={len(due_ids) - 1} failed=1 deferred=0',
            output.getvalue(),
        )

    def test_runner_reports_a_lost_claim_as_deferred_without_failing(self):
        Task.objects.all().delete()
        enqueue_admin_command(self.command().pk)
        output = StringIO()
        with patch('frontend.management.commands.run_tasks.run_task_with_outcome',
                   return_value=TaskRunOutcome.NOT_OWNED):
            call_command('run_tasks', stdout=output)
        self.assertIn('failed=0 deferred=1', output.getvalue())

    def test_runner_reports_a_claimed_failure_and_exits_nonzero(self):
        Task.objects.all().delete()
        task = enqueue_admin_command(self.command().pk)
        output = StringIO()
        with patch.dict(HANDLERS, {'deliver_admin_command': MagicMock(return_value=False)}):
            with self.assertRaises(CommandError):
                call_command('run_tasks', stdout=output)
        self.assertIn('failed=1 deferred=0', output.getvalue())
        task.refresh_from_db()
        self.assertTrue(task.last_error)
        self.assertEqual(task.status, 'pending')

    def test_data_migration_backfills_only_pending_commands_idempotently(self):
        from importlib import import_module
        from types import SimpleNamespace
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        pending = self.command()
        delivered = self.command()
        AdminGameCommand.objects.filter(pk=delivered.pk).update(status='delivered')
        Task.objects.all().delete()
        migration = import_module('frontend.migrations.0008_task')
        historical_apps = MigrationExecutor(connection).loader.project_state(
            [('frontend', '0008_task')],
        ).apps
        editor = SimpleNamespace(connection=connection)
        migration.seed_tasks(historical_apps, editor)
        migration.seed_tasks(historical_apps, editor)
        self.assertEqual(Task.objects.count(), 2)
        self.assertTrue(Task.objects.filter(key=f'admin-command:{pending.pk}').exists())
        self.assertFalse(Task.objects.filter(key=f'admin-command:{delivered.pk}').exists())
