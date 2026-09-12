import time
from importlib.util import find_spec

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from frontend.push import configured, discover_ready_matches, deliver_pending


class Command(BaseCommand):
    help = 'Deliver opt-in tournament and direct-play phone notifications; run as a supervised worker.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
        parser.add_argument('--interval', type=int, default=5)

    def handle(self, *args, **options):
        if not configured():
            raise CommandError('Set WEB_PUSH_PUBLIC_KEY, WEB_PUSH_PRIVATE_KEY and WEB_PUSH_SUBJECT first.')
        if find_spec('pywebpush') is None:
            raise CommandError('Install the repository requirements before running push delivery.')
        if options['interval'] < 1:
            raise CommandError('The interval must be positive.')
        while True:
            close_old_connections()
            queued = discover_ready_matches()
            sent = deliver_pending()
            if queued or sent or options['once']:
                self.stdout.write(f'Queued {queued}; delivered {sent}.')
            if options['once']:
                break
            time.sleep(options['interval'])
