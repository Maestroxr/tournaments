import uuid
from datetime import timedelta
from threading import Event, Thread
from unittest import skipUnless
from unittest.mock import patch

from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from tournaments.models import Tournament

from .models import Task
from .task_ownership import fence_task_ownership
from .task_runner import HANDLERS, run_task, start_scheduled_tournaments


class TaskMutationOwnershipTests(TestCase):
    def test_replaced_owner_cannot_mutate_business_data(self):
        tournament = Tournament.objects.create(name='Fence cup', podium_spec=[], starts_at=timezone.now(), published=True)
        task = Task.objects.create(key='fence-test', name=Task.NAME_START_SCHEDULED_TOURNAMENTS)
        replacement = uuid.uuid4()

        def handler(**kwargs):
            Task.objects.filter(pk=task.pk).update(lease_token=replacement)
            with transaction.atomic():
                locked = Tournament.objects.select_for_update().get(pk=tournament.pk)
                fence_task_ownership()
                locked.published = False
                locked.save(update_fields=['published'])

        with patch.dict(HANDLERS, {task.name: handler}):
            self.assertFalse(run_task(task.pk))
        tournament.refresh_from_db()
        task.refresh_from_db()
        self.assertTrue(tournament.published)
        self.assertEqual(task.lease_token, replacement)
        self.assertEqual(task.status, 'running')

    def test_scheduled_start_scan_resumes_without_revisiting_prior_page(self):
        cups = [Tournament.objects.create(name=f'Queued cup {n}', podium_spec=[], starts_at=timezone.now() - timedelta(hours=1),
                                         published=True, min_players=2) for n in range(3)]
        with patch('frontend.task_runner.START_BATCH_SIZE', 1):
            first = start_scheduled_tournaments(heartbeat=None, bounded=True)
            self.assertEqual(first['processed'], 1)
            self.assertEqual(first['continuation']['cursor'], cups[0].pk)
            second = start_scheduled_tournaments(heartbeat=None, bounded=True, **first['continuation'])
            self.assertEqual(second['continuation']['cursor'], cups[1].pk)
            third = start_scheduled_tournaments(heartbeat=None, bounded=True, **second['continuation'])
            self.assertIsNone(third['continuation'])
        self.assertFalse(Tournament.objects.filter(pk__in=[cup.pk for cup in cups], published=True).exists())


@skipUnless(connection.vendor == 'postgresql', 'Requires real PostgreSQL task claims')
class ConcurrentTaskOwnershipTests(TransactionTestCase):
    def test_only_one_worker_executes_the_same_due_task(self):
        task = Task.objects.create(key='concurrent-claim', name=Task.NAME_DELIVER_ADMIN_COMMAND)
        entered, release = Event(), Event()
        results, errors = [], []

        def handler(**kwargs):
            entered.set()
            if not release.wait(timeout=8):
                raise RuntimeError('Claim test did not release handler')
            return True

        def execute():
            database = connections['default']
            try:
                with database.cursor() as cursor:
                    cursor.execute("SET lock_timeout TO '5s'")
                results.append(run_task(task.pk))
            except Exception as error:
                errors.append(error)
            finally:
                database.close()

        first, second = Thread(target=execute, daemon=True), Thread(target=execute, daemon=True)
        with patch.dict(HANDLERS, {task.name: handler}):
            try:
                first.start()
                self.assertTrue(entered.wait(timeout=5), 'First worker did not claim task')
                second.start()
                second.join(timeout=5)
                self.assertFalse(second.is_alive(), 'Second worker waited on an executing handler')
                self.assertEqual(results, [False])
            finally:
                release.set()
                first.join(timeout=10)
                if second.ident is not None:
                    second.join(timeout=10)
        self.assertFalse(first.is_alive())
        self.assertEqual(errors, [])
        self.assertCountEqual(results, [False, True])

    def test_worker_waiting_for_parent_cannot_mutate_after_lease_replacement(self):
        cup = Tournament.objects.create(name='Blocked cup', podium_spec=[], starts_at=timezone.now(), published=True)
        task = Task.objects.create(key='blocked-owner', name=Task.NAME_START_SCHEDULED_TOURNAMENTS)
        replacement = uuid.uuid4()
        waiting = Event()
        results, errors = [], []

        def handler(**kwargs):
            waiting.set()
            with transaction.atomic():
                locked = Tournament.objects.select_for_update().get(pk=cup.pk)
                fence_task_ownership()
                locked.published = False
                locked.save(update_fields=['published'])
            return True

        def execute():
            database = connections['default']
            try:
                with database.cursor() as cursor:
                    cursor.execute("SET lock_timeout TO '5s'")
                results.append(run_task(task.pk))
            except Exception as error:
                errors.append(error)
            finally:
                database.close()

        worker = Thread(target=execute, daemon=True)
        with patch.dict(HANDLERS, {task.name: handler}):
            try:
                with transaction.atomic():
                    Tournament.objects.select_for_update().get(pk=cup.pk)
                    worker.start()
                    self.assertTrue(waiting.wait(timeout=5))
                    Task.objects.filter(pk=task.pk).update(lease_token=replacement)
            finally:
                if worker.ident is not None:
                    worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results, [False])
        cup.refresh_from_db()
        task.refresh_from_db()
        self.assertTrue(cup.published)
        self.assertEqual(task.lease_token, replacement)
