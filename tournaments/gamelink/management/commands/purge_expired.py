"""
Scheduled cleanup for the game link (plan §8).

Run on the same schedule as the game server's `run_tasks`; once a minute is fine and once an hour
is enough. Nothing here is urgent — but a `SeenNonce` table that is never purged grows without
bound, and a fixture whose link is stuck `pending` stays unscorable-by-machine and unexplained.
"""

import datetime

from django.core.management.base import BaseCommand, CommandError

from ...housekeeping import DEFAULT_NONCE_RETENTION, purge_expired


class Command(BaseCommand):

    help = 'Delete aged-out game link audit rows and close game links that were never played.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--nonce-hours',
            type = float,
            default = DEFAULT_NONCE_RETENTION.total_seconds() / 3600,
            help = 'How long a seen nonce is remembered, in hours. Must stay above twice '
                   'GAMELINK_CLOCK_SKEW or the command refuses to run, because purging a nonce '
                   'while its message is still inside the timestamp window re-opens a replay.')

    def handle(self, *args, **options):
        try:
            counts = purge_expired(nonce_retention = datetime.timedelta(hours = options['nonce_hours']))
        except ValueError as error:
            # A `CommandError` exits non-zero without a traceback, which is what a cron job's mail
            # should look like.
            raise CommandError(str(error)) from error

        self.stdout.write(self.style.SUCCESS(
            f'Purged {counts["nonces"]} seen nonces and {counts["tickets"]} issued tickets; '
            f'cancelled {counts["links"]} game links that were never played'))
