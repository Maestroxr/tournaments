"""Run durable tasks with expiring, token-checked ownership."""
import logging
import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
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


def _cancel_tournament_for_insufficient_players(tournament):
    """Cancel a due tournament whose roster never reached its minimum.

    Mirrors the cancellation core of ``api_admin_tournament_draft``: paid
    entry fees are refunded through the existing registration helpers, the
    tournament is unpublished, and roster/draw state is cleared. Afterwards
    the tournament reads as a draft, so the recurring scanner never picks it
    up again. Generates no fixtures, stamps no ``playable_at``, sends no push.
    """
    from .api import _ensure_registration, _refund_registration

    if tournament.entry_fee > 0:
        for participation in tournament.participations.select_related('participant__user'):
            registration = _ensure_registration(tournament, participation.participant)
            _refund_registration(tournament, registration, None)
    tournament.published = False
    tournament.registration_closed_at = None
    # 'insufficient_players_at_start' does not fit the 20-char reason field;
    # this is its fitting form under the existing reason convention.
    tournament.registration_closed_reason = 'insufficient_players'
    tournament.clear_draw()
    tournament.results_confirmed_at = None
    tournament.participations.all().delete()
    tournament.registrations.all().delete()
    tournament.save(update_fields=[
        'published', 'registration_closed_at', 'registration_closed_reason', 'draw_order',
        'draw_generated_at', 'draw_confirmed_at', 'results_confirmed_at',
    ])


def start_scheduled_tournaments(*, heartbeat):
    """Start published tournaments whose scheduled start time has been reached.

    One recurring scanner: each due tournament is locked and re-checked before
    the existing start flow runs, so concurrent workers cannot double-start.
    Tournaments without enough players yet are skipped and retried next cycle.
    """
    from tournaments.models import Tournament

    from .api import _start_tournament_at_capacity

    now = timezone.now()
    candidate_ids = list(
        Tournament.objects.filter(published=True, starts_at__lte=now).values_list('pk', flat=True)
    )
    started = 0
    for tournament_id in candidate_ids:
        if heartbeat is not None:
            heartbeat()
        try:
            with transaction.atomic():
                try:
                    tournament = Tournament.objects.select_for_update().get(pk=tournament_id)
                except Tournament.DoesNotExist:
                    continue
                if (
                    not tournament.published
                    or tournament.starts_at is None
                    or tournament.starts_at > timezone.now()
                    or tournament.state != 'open'
                ):
                    continue
                # Same participant count the start flow gates on: only a short
                # roster diverts to cancellation. A start failure with enough
                # players (e.g. an invalid bracket definition) keeps the
                # existing retry behavior below instead of cancelling.
                if tournament.participations.count() >= tournament.min_players:
                    _start_tournament_at_capacity(tournament)
                else:
                    _cancel_tournament_for_insufficient_players(tournament)
        except ValidationError:
            # A start failure with enough players (e.g. an invalid bracket
            # definition): leave the tournament open and retry on the next
            # scheduled cycle. Short rosters never reach this branch — they
            # are cancelled, not retried.
            logger.info('Scheduled start deferred tournament=%s', tournament_id)
            continue
        started += 1
    return started


HANDLERS = {
    Task.NAME_DELIVER_ADMIN_COMMAND: deliver_admin_command,
    Task.NAME_EXPIRE_UNSTARTED_GAMES: expire_unstarted_games,
    Task.NAME_START_SCHEDULED_TOURNAMENTS: start_scheduled_tournaments,
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
    if task.name in (Task.NAME_EXPIRE_UNSTARTED_GAMES, Task.NAME_START_SCHEDULED_TOURNAMENTS):
        changes.update(
            status=Task.STATUS_PENDING,
            run_at=finished_at + timedelta(seconds=EXPIRY_INTERVAL_SECONDS),
            attempts=0,
        )
    return bool(owned.update(**changes))
