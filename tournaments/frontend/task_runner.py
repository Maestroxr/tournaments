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
    Tournaments below the minimum are cancelled and their entry fees refunded.
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


def expire_tournament_entry_deadlines(*, heartbeat):
    """Resolve tournament fixtures whose 10-minute entry deadline expired.

    Request-independent: covers fixtures where neither player ever opens the
    match (no heartbeat/request ever arrives). Reuses the existing resolvers
    so single-fresh still yields opponent_no_show and zero-fresh yields
    double_no_show; both-fresh is left alone. Idempotent under row locks.
    """
    from gamelink.views import (
        TOURNAMENT_ENTRY_WINDOW,
        _entry_deadline_fields,
        _resolve_double_no_show_locked,
        _try_resolve_no_show,
    )
    from tournaments.models import Fixture, Tournament

    now = timezone.now()
    cutoff = now - TOURNAMENT_ENTRY_WINDOW
    candidate_ids = list(
        Fixture.objects.filter(
            playable_at__lte=cutoff,
            playable_at__isnull=False,
            player1__isnull=False,
            player2__isnull=False,
            admin_result='',
            score1__isnull=True,
            score2__isnull=True,
        ).order_by('playable_at').values_list('pk', flat=True)[:200]
    )
    resolved = 0
    for fixture_id in candidate_ids:
        if heartbeat is not None:
            heartbeat()
        try:
            with transaction.atomic():
                try:
                    fixture = Fixture.objects.select_for_update().get(pk=fixture_id)
                except Fixture.DoesNotExist:
                    continue
                if fixture.is_confirmed or fixture.admin_result:
                    continue
                if fixture.playable_at is None:
                    continue
                if fixture.player1_id is None or fixture.player2_id is None:
                    continue
                entry_deadline, _ = _entry_deadline_fields(fixture, now)
                if entry_deadline is None or now < entry_deadline:
                    continue
                try:
                    tournament = Tournament.objects.select_for_update().get(
                        pk=fixture.mode.tournament_id,
                    )
                except Tournament.DoesNotExist:
                    continue
                if tournament.state != 'active':
                    continue
                from gamelink.models import GameLink

                try:
                    game_link = GameLink.objects.select_for_update().filter(
                        fixture_id=fixture.pk,
                    ).first()
                except Exception:
                    continue
                if game_link is not None:
                    outcome = _try_resolve_no_show(fixture, game_link, now)
                    if outcome is not None:
                        resolved += 1
                else:
                    if _resolve_double_no_show_locked(fixture, None, now):
                        resolved += 1
        except Exception:
            logger.exception('Tournament entry expiry failed fixture=%s', fixture_id)
            continue
    return resolved


HANDLERS = {
    Task.NAME_DELIVER_ADMIN_COMMAND: deliver_admin_command,
    Task.NAME_EXPIRE_UNSTARTED_GAMES: expire_unstarted_games,
    Task.NAME_START_SCHEDULED_TOURNAMENTS: start_scheduled_tournaments,
    Task.NAME_EXPIRE_TOURNAMENT_ENTRY_DEADLINES: expire_tournament_entry_deadlines,
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
    if task.name in (Task.NAME_EXPIRE_UNSTARTED_GAMES, Task.NAME_START_SCHEDULED_TOURNAMENTS, Task.NAME_EXPIRE_TOURNAMENT_ENTRY_DEADLINES):
        changes.update(
            status=Task.STATUS_PENDING,
            run_at=finished_at + timedelta(seconds=EXPIRY_INTERVAL_SECONDS),
            attempts=0,
        )
    return bool(owned.update(**changes))
