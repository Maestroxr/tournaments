from django.core.management.base import BaseCommand

from frontend.tasks import schedule_tasks


class Command(BaseCommand):
    help = 'Ensure recurring expiry and pending admin commands have durable Tasks.'

    def handle(self, *args, **options):
        created = schedule_tasks()
        self.stdout.write(f'Created {created} tournament task(s).')
