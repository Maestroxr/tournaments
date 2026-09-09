from django.core.management.base import BaseCommand

from gamelink.commands import deliver_admin_command
from gamelink.models import AdminGameCommand


class Command(BaseCommand):
    help = 'Retry pending tournaments-to-game administrative commands.'

    def handle(self, *args, **options):
        delivered = 0
        for command_id in AdminGameCommand.objects.filter(status='pending').values_list('pk', flat=True)[:100]:
            delivered += int(deliver_admin_command(command_id))
        self.stdout.write(f'Delivered {delivered} admin game command(s).')
