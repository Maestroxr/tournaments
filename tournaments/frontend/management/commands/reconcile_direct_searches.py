from django.core.management.base import BaseCommand

from frontend.search_lifecycle import reconcile_searches_locked


class Command(BaseCommand):
    help = 'Close unsupported unmatched direct-play searches and release their reservations.'

    def handle(self, *args, **options):
        cancelled = reconcile_searches_locked()
        self.stdout.write(f'Closed {len(cancelled)} unmatched searches: {cancelled}')
