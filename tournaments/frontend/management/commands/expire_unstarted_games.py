from django.core.management.base import BaseCommand
from frontend.entry_lifecycle import expire_unstarted_tables


class Command(BaseCommand):
    help = 'Cancel direct games whose players did not arrive within ten minutes; release reservations.'

    def handle(self, *args, **options):
        expire_unstarted_tables()
