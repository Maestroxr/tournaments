import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from frontend.task_runner import runnable, run_task

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Execute due tournament Tasks and recover abandoned execution leases.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=50,
                            help='Maximum due tasks to attempt in this run (default: 50).')

    def handle(self, *args, **options):
        if options['limit'] < 1:
            raise CommandError('--limit must be positive.')
        ids = list(runnable().values_list('pk', flat=True)[:options['limit']])
        failed = []
        for task_id in ids:
            try:
                close_old_connections()
                done = run_task(task_id)
            except Exception:
                logger.exception('Could not execute tournament Task %s', task_id)
                failed.append(str(task_id))
            else:
                self.stdout.write(f'Task {task_id}: {"completed" if done else "deferred or retry scheduled"}')
        if failed:
            raise CommandError(f'Could not execute tournament Tasks: {", ".join(failed)}')
