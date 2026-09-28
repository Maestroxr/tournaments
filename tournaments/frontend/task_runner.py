"""Run durable tasks with expiring, token-checked ownership."""
import logging
import uuid
from datetime import timedelta

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from .models import Task

logger = logging.getLogger(__name__)
LEASE_SECONDS = 120
EXPIRY_INTERVAL_SECONDS = 60
MAX_RETRY_SECONDS = 300


def deliver_admin_command(*, command_id, heartbeat):
    from gamelink.commands import deliver_admin_command as deliver

    return deliver(command_id)


def expire_unstarted_games(*, heartbeat):
    from .entry_lifecycle import expire_unstarted_tables

    return expire_unstarted_tables(heartbeat=heartbeat)


HANDLERS = {
    Task.NAME_DELIVER_ADMIN_COMMAND: deliver_admin_command,
    Task.NAME_EXPIRE_UNSTARTED_GAMES: expire_unstarted_games,
}


def runnable(now=None):
    now = now or timezone.now()
    return Task.objects.filter(
        Q(status=Task.STATUS_PENDING, run_at__lte=now)
        | Q(status=Task.STATUS_RUNNING, locked_until__lte=now)
    )


def refresh_lease(task_id, lease_token):
    now = timezone.now()
    return bool(Task.objects.filter(
        pk=task_id, status=Task.STATUS_RUNNING, lease_token=lease_token,
    ).update(locked_until=now + timedelta(seconds=LEASE_SECONDS), updated_at=now))


def run_task(task_id):
    now = timezone.now()
    lease_token = uuid.uuid4()
    with transaction.atomic():
        claimed = runnable(now).filter(pk=task_id).update(
            status=Task.STATUS_RUNNING,
            lease_token=lease_token,
            locked_until=now + timedelta(seconds=LEASE_SECONDS),
            attempts=F('attempts') + 1,
            updated_at=now,
        )
    if not claimed:
        return False
    owned = Task.objects.filter(pk=task_id, status=Task.STATUS_RUNNING, lease_token=lease_token)
    task = owned.first()
    if task is None:
        return False
    try:
        handler = HANDLERS[task.name]
        result = handler(
            **task.kwargs,
            heartbeat=lambda: refresh_lease(task_id, lease_token),
        )
        if result is False:
            raise RuntimeError('Task handler did not complete')
    except Exception as error:
        finished_at = timezone.now()
        retry_seconds = min(5 * 2 ** min(task.attempts - 1, 6), MAX_RETRY_SECONDS)
        owned.update(
            status=Task.STATUS_PENDING,
            run_at=finished_at + timedelta(seconds=retry_seconds),
            lease_token=None,
            locked_until=None,
            last_error=str(error)[:2000],
            last_finished_at=finished_at,
            updated_at=finished_at,
        )
        logger.exception('Tournament task failed task=%s name=%s', task.pk, task.name)
        return False
    finished_at = timezone.now()
    changes = {
        'status': Task.STATUS_DONE,
        'lease_token': None,
        'locked_until': None,
        'last_error': '',
        'last_finished_at': finished_at,
        'updated_at': finished_at,
    }
    if task.name == Task.NAME_EXPIRE_UNSTARTED_GAMES:
        changes.update(
            status=Task.STATUS_PENDING,
            run_at=finished_at + timedelta(seconds=EXPIRY_INTERVAL_SECONDS),
            attempts=0,
        )
    return bool(owned.update(**changes))
