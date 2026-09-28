"""Persist tournament work before immediate delivery or the next cron cycle."""
from gamelink.models import AdminGameCommand

from .models import Task


def enqueue_admin_command(command_id):
    task, _ = Task.objects.get_or_create(
        key=f'admin-command:{command_id}',
        defaults={
            'name': Task.NAME_DELIVER_ADMIN_COMMAND,
            'kwargs': {'command_id': str(command_id)},
        },
    )
    return task


def schedule_tasks():
    _, created = Task.objects.get_or_create(
        key='expire-unstarted-games',
        defaults={'name': Task.NAME_EXPIRE_UNSTARTED_GAMES},
    )
    created_count = int(created)
    pending_ids = AdminGameCommand.objects.filter(status='pending').values_list('pk', flat=True)
    for command_id in pending_ids.iterator():
        _, created = Task.objects.get_or_create(
            key=f'admin-command:{command_id}',
            defaults={
                'name': Task.NAME_DELIVER_ADMIN_COMMAND,
                'kwargs': {'command_id': str(command_id)},
            },
        )
        created_count += int(created)
    return created_count
