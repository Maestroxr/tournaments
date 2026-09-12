from datetime import date, timedelta
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError
from django.utils import timezone
from billing.operations import run_reports
from billing.tranzila import ProviderError


class Command(BaseCommand):
    help = 'Read Tranzila reports, recover verified pending orders and flag discrepancies. Never charges cards.'

    def add_arguments(self, parser):
        parser.add_argument('--date-from', type=date.fromisoformat)
        parser.add_argument('--date-to', type=date.fromisoformat)
        parser.add_argument('--max-pages', type=int, default=20)

    def handle(self, *args, **options):
        end = options['date_to'] or timezone.localdate()
        start = options['date_from'] or end - timedelta(days=7)
        try:
            run = run_reports(start, end, max_pages=options['max_pages'])
        except (ProviderError, IntegrityError, ValueError):
            raise CommandError('Reconciliation unavailable: check configuration, range or an existing run.') from None
        self.stdout.write(f'Run {run.pk}: {run.status}; checked={run.checked}; recovered={run.recovered}; issues={run.issues}')
        if run.status != 'success':
            raise CommandError('Report coverage is incomplete; review the run and retry the same range.')
