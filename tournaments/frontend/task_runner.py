"""Run durable tasks with expiring, token-checked ownership."""
import logging
import time
import uuid
from datetime import timedelta
from enum import Enum
from functools import partial

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Q
from django.utils import timezone

from .models import Task
from .task_ownership import fence_task_ownership, task_ownership

logger = logging.getLogger(__name__)
LEASE_SECONDS = 120
EXPIRY_INTERVAL_SECONDS = 60
MAX_RETRY_SECONDS = 300
ENTRY_EXPIRY_BATCH_SIZE = 200
START_BATCH_SIZE = 10
BATCH_SECONDS = 8


class TaskRunOutcome(Enum):
    COMPLETED = 'completed'
    RETRY_SCHEDULED = 'failed; retry scheduled'
    NOT_OWNED = 'deferred; not owned'


class RetryTaskBatch(RuntimeError):
    """Keep committed page progress; revisit failed items on the next scan."""
    def __init__(self, message, checkpoint):
        super().__init__(message)
        self.checkpoint = checkpoint


def deliver_admin_command(*, command_id, heartbeat):
    from gamelink.commands import deliver_admin_command as deliver

    if heartbeat is not None and not heartbeat():
        logger.warning('event=task_lease_lost handler=deliver_admin_command command_id=%s', command_id)
        return False
    return deliver(command_id)


def expire_unstarted_games(*, heartbeat, cursor=0, stop_id=None):
    from .entry_lifecycle import expire_unstarted_tables

    if heartbeat is not None and not heartbeat():
        logger.warning('event=task_lease_lost handler=expire_unstarted_games')
        return False
    return expire_unstarted_tables(heartbeat=heartbeat, cursor=cursor, stop_id=stop_id,
                                  max_items=20, max_seconds=8)


def reconcile_searches(*, heartbeat, cursor=0, stop_id=None):
    from .search_lifecycle import reconcile_searches_locked
    return reconcile_searches_locked(heartbeat=heartbeat, cursor=cursor,
                                    stop_id=stop_id, max_batches=2)


def _cancel_tournament_for_insufficient_players(tournament):
    """Cancel a due tournament whose roster never reached its minimum.

    Mirrors the cancellation core of ``api_admin_tournament_draft``: paid
    entry fees are refunded through the existing registration helpers, the
    tournament is unpublished, and roster/draw state is cleared. Afterwards
    the tournament reads as a draft, so the recurring scanner never picks it
    up again. Generates no fixtures, stamps no ``playable_at``, sends no push.
    """
    from .api import _refund_tournament_roster

    if tournament.entry_fee > 0:
        _refund_tournament_roster(tournament, None)
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


def start_scheduled_tournaments(*, heartbeat, cursor=0, stop_id=None, bounded=False):
    """Start published tournaments whose scheduled start time has been reached.

    One recurring scanner: each due tournament is locked and re-checked before
    the existing start flow runs, so concurrent workers cannot double-start.
    Tournaments below the minimum are cancelled and their entry fees refunded.
    """
    from tournaments.models import Fixture, Tournament

    from .api import _start_tournament_at_capacity

    now = timezone.now()
    batch_started = time.perf_counter()
    candidates = (
        Tournament.objects.filter(
            published=True, starts_at__lte=now, results_confirmed_at__isnull=True,
        ).annotate(
            has_fixtures=Exists(Fixture.objects.filter(mode__tournament_id=OuterRef('pk'))),
        ).filter(has_fixtures=False)
    )
    stop_id = stop_id or candidates.order_by('-pk').values_list('pk', flat=True).first()
    candidate_ids = list(candidates.filter(pk__gt=cursor, pk__lte=stop_id).order_by('pk')
                         .values_list('pk', flat=True)[:START_BATCH_SIZE]) if stop_id is not None else []
    started = 0
    deferred_ids = []
    continuation = None
    for index, tournament_id in enumerate(candidate_ids):
        if bounded and index > 0 and time.perf_counter() - batch_started >= BATCH_SECONDS:
            continuation = {'cursor': cursor, 'stop_id': stop_id}
            break
        if heartbeat is not None and not heartbeat():
            logger.warning('event=task_lease_lost handler=start_scheduled_tournaments tournament_id=%s', tournament_id)
            return False
        cursor = tournament_id
        try:
            with transaction.atomic():
                try:
                    tournament = Tournament.objects.select_for_update().get(pk=tournament_id)
                except Tournament.DoesNotExist:
                    continue
                fence_task_ownership()
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
            logger.warning('event=tournament_start_deferred tournament_id=%s reason=validation_error', tournament_id,
                           exc_info=True)
            deferred_ids.append(tournament_id)
            continue
        started += 1
        logger.info('event=tournament_start_processed tournament_id=%s outcome=%s',
                    tournament_id, 'started' if tournament.published else 'cancelled_insufficient_players')
    if bounded and continuation is None and stop_id is not None and candidates.filter(pk__gt=cursor, pk__lte=stop_id).exists():
        continuation = {'cursor': cursor, 'stop_id': stop_id}
    if deferred_ids:
        message = f'Tournament start validation failed for tournaments: {deferred_ids}'
        if bounded:
            raise RetryTaskBatch(message, continuation or {})
        raise RuntimeError(message)
    if bounded:
        logger.debug('event=tournament_start_batch processed=%s continuation=%s duration_ms=%s',
                     started, bool(continuation), int((time.perf_counter() - batch_started) * 1000))
        return {'processed': started, 'continuation': continuation}
    return started


def _personally_ready_fixture_ids(tournament_id):
    """Fresh, read-only candidate filtering; admission policy has no feature gate."""
    from gamelink.playability import personally_ready_fixture_ids
    from tournaments.models import Fixture, Participation

    fixtures = list(Fixture.objects.filter(mode__tournament_id=tournament_id)
                    .select_related('player1', 'player2')
                    .annotate(read_confirmation_count=Count('confirmations')))
    required = 1 + Participation.objects.filter(
        tournament_id=tournament_id, participant__user__isnull=False,
    ).count() // 2
    return personally_ready_fixture_ids(
        fixtures, is_confirmed=lambda fixture: fixture.confirmed_result(
            confirmation_count=fixture.read_confirmation_count,
            required_confirmations=required,
        ),
    )


def expire_tournament_entry_deadlines(*, heartbeat, cursor=0, stop_id=None, bounded=False):
    """Resolve tournament fixtures whose 10-minute entry deadline expired.

    Request-independent: covers fixtures where neither player ever opens the
    match (no heartbeat/request ever arrives). Reuses the existing resolvers
    so single-fresh still yields opponent_no_show and zero-fresh yields
    double_no_show; both-fresh is left alone. Idempotent under row locks.
    """
    from gamelink.entry_presence import expire_presence
    if heartbeat is None or heartbeat():
        expire_presence()
    from gamelink.views import (
        TOURNAMENT_ENTRY_WINDOW,
        _entry_deadline_fields,
        _resolve_double_no_show_locked,
        _try_resolve_no_show,
    )
    from tournaments.models import Fixture, Tournament

    batch_started = time.perf_counter()
    now = timezone.now()
    cutoff = now - TOURNAMENT_ENTRY_WINDOW
    potential_query = (
        Fixture.objects.filter(
            mode__tournament__published=True,
            mode__tournament__results_confirmed_at__isnull=True,
            mode__tournament__entry_deadline_paused=False,
            playable_at__lte=cutoff,
            playable_at__isnull=False,
            player1__isnull=False,
            player2__isnull=False,
            admin_result='',
            score1__isnull=True,
            score2__isnull=True,
        ).filter(
            Q(game_link__isnull=True) | Q(
                game_link__status='pending',
                game_link__external_room_id='',
                game_link__entry_authorized_at__isnull=True,
            ),
        )
    )
    stop_id = stop_id or potential_query.order_by('-pk').values_list('pk', flat=True).first()
    potential_candidates = list(potential_query.filter(pk__gt=cursor, pk__lte=stop_id).order_by('pk')
                                .values_list('pk', 'mode__tournament_id')[:ENTRY_EXPIRY_BATCH_SIZE]) if stop_id is not None else []
    # Cursor progress includes personally blocked rows. Every candidate page
    # yields the writer, even if legacy clocks cover future group matches.
    eligible_by_tournament = {}
    candidates = potential_candidates
    continuation = None
    resolved = 0
    failed_ids = []
    for index, (fixture_id, tournament_id) in enumerate(candidates):
        if bounded and index > 0 and time.perf_counter() - batch_started >= BATCH_SECONDS:
            continuation = {'cursor': cursor, 'stop_id': stop_id}
            break
        cursor = fixture_id
        if heartbeat is not None and not heartbeat():
            logger.warning(
                'event=task_lease_lost handler=expire_tournament_entry_deadlines '
                'tournament_id=%s fixture_id=%s resolved=%s', tournament_id, fixture_id, resolved,
            )
            return False
        if tournament_id not in eligible_by_tournament:
            eligible_by_tournament[tournament_id] = _personally_ready_fixture_ids(tournament_id)
        if fixture_id not in eligible_by_tournament[tournament_id]:
            continue
        try:
            with transaction.atomic():
                # Admission and administrative results take these locks in the
                # same order. Avoid a fixture -> tournament lock inversion.
                try:
                    tournament = Tournament.objects.select_for_update().get(pk=tournament_id)
                except Tournament.DoesNotExist:
                    continue
                fence_task_ownership()
                if tournament.entry_deadline_paused or tournament.state != 'active':
                    logger.debug('event=entry_expiry_skipped tournament_id=%s fixture_id=%s reason=paused_or_inactive',
                                 tournament_id, fixture_id)
                    continue
                try:
                    fixture = Fixture.objects.select_for_update(of=('self',)).select_related('mode').get(
                        pk=fixture_id, mode__tournament_id=tournament.pk,
                    )
                except Fixture.DoesNotExist:
                    continue
                # Reuse the locked tournament for deadline and progression
                # checks; a separately loaded object could have stale policy.
                fixture.mode.tournament = tournament
                if fixture.is_confirmed or fixture.admin_result:
                    continue
                if fixture.playable_at is None:
                    continue
                if fixture.player1_id is None or fixture.player2_id is None:
                    continue
                # The prefilter is only a scheduling hint. Re-read while the
                # tournament is locked, including results written this batch.
                if fixture.pk not in _personally_ready_fixture_ids(tournament.pk):
                    logger.debug('event=entry_expiry_skipped tournament_id=%s fixture_id=%s reason=personal_match_blocked',
                                 tournament_id, fixture_id)
                    continue
                fixture_now = timezone.now()
                entry_deadline, _ = _entry_deadline_fields(fixture, fixture_now)
                if entry_deadline is None or fixture_now < entry_deadline:
                    continue
                from gamelink.models import GameLink

                game_link = GameLink.objects.select_for_update().filter(
                    fixture_id=fixture.pk,
                ).first()
                if game_link is not None:
                    if (game_link.status != 'pending' or game_link.external_room_id
                            or game_link.entry_authorized_at is not None):
                        logger.debug('event=entry_expiry_skipped tournament_id=%s fixture_id=%s reason=admitted_or_terminal',
                                     tournament_id, fixture_id)
                        continue
                    outcome = _try_resolve_no_show(fixture, game_link, fixture_now)
                    if outcome is not None:
                        resolved += 1
                else:
                    if _resolve_double_no_show_locked(fixture, None, fixture_now):
                        resolved += 1
        except Exception:
            failed_ids.append(fixture_id)
            logger.exception('event=entry_expiry_failed tournament_id=%s fixture_id=%s', tournament_id, fixture_id)
            continue
    batch_log = logger.warning if failed_ids else logger.info if resolved else logger.debug
    batch_log(
        'event=entry_expiry_batch candidates=%s resolved=%s failed=%s skipped=%s duration_ms=%s',
        len(candidates), resolved, len(failed_ids), len(candidates) - resolved - len(failed_ids),
        int((time.perf_counter() - batch_started) * 1000),
    )
    if bounded and continuation is None and stop_id is not None and potential_query.filter(pk__gt=cursor, pk__lte=stop_id).exists():
        continuation = {'cursor': cursor, 'stop_id': stop_id}
    if failed_ids:
        # Successful fixtures remain committed, but this batch must retain its
        # attempts/error and retry instead of looking like a successful no-op.
        message = f'Tournament entry expiry failed for fixtures: {failed_ids}'
        if bounded:
            raise RetryTaskBatch(message, continuation or {})
        raise RuntimeError(message)
    if bounded:
        return {'processed': resolved, 'continuation': continuation}
    return resolved


HANDLERS = {
    Task.NAME_RECONCILE_SEARCHES: reconcile_searches,
    Task.NAME_DELIVER_ADMIN_COMMAND: deliver_admin_command,
    Task.NAME_EXPIRE_UNSTARTED_GAMES: expire_unstarted_games,
    Task.NAME_START_SCHEDULED_TOURNAMENTS: partial(start_scheduled_tournaments, bounded=True),
    Task.NAME_EXPIRE_TOURNAMENT_ENTRY_DEADLINES: partial(expire_tournament_entry_deadlines, bounded=True),
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
    """Boolean compatibility API for immediate callers."""
    return run_task_with_outcome(task_id) is TaskRunOutcome.COMPLETED


def run_task_with_outcome(task_id):
    """Distinguish a failed claimed attempt from a concurrent worker's task."""
    from tournaments.observability import request_context

    token = request_context.set({**(request_context.get() or {}), 'task_id': str(task_id)})
    try:
        return _run_task_with_outcome(task_id)
    finally:
        request_context.reset(token)


def _run_task_with_outcome(task_id):
    started_at = time.perf_counter()
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
        logger.debug('event=task_not_owned task_id=%s reason=not_runnable', task_id)
        return TaskRunOutcome.NOT_OWNED
    owned = Task.objects.filter(pk=task_id, status=Task.STATUS_RUNNING, lease_token=lease_token)
    task = owned.first()
    if task is None:
        logger.warning('event=task_lease_lost task_id=%s reason=claim_replaced', task_id)
        return TaskRunOutcome.NOT_OWNED
    from tournaments.observability import request_context
    request_context.set({**(request_context.get() or {}), 'task_name': task.name})
    logger.debug('event=task_claimed task_id=%s task_name=%s attempt=%s', task.pk, task.name, task.attempts)
    try:
        handler = HANDLERS[task.name]
        with task_ownership(owned):
            result = handler(
                **task.kwargs,
                heartbeat=lambda: refresh_lease(task_id, lease_token),
            )
        if result is False:
            raise RuntimeError('Task handler did not complete')
    except Exception as error:
        finished_at = timezone.now()
        retry_seconds = min(5 * 2 ** min(task.attempts - 1, 6), MAX_RETRY_SECONDS)
        retried = owned.update(
            kwargs=error.checkpoint if isinstance(error, RetryTaskBatch) else task.kwargs,
            status=Task.STATUS_PENDING,
            run_at=finished_at + timedelta(seconds=retry_seconds),
            lease_token=None,
            locked_until=None,
            last_error=str(error)[:2000],
            last_finished_at=finished_at,
            updated_at=finished_at,
        )
        logger.exception(
            'event=task_failed task_id=%s task_name=%s attempt=%s retry_scheduled=%s '
            'retry_seconds=%s duration_ms=%s error_type=%s',
            task.pk, task.name, task.attempts, bool(retried), retry_seconds,
            int((time.perf_counter() - started_at) * 1000), type(error).__name__,
        )
        return TaskRunOutcome.RETRY_SCHEDULED if retried else TaskRunOutcome.NOT_OWNED
    finished_at = timezone.now()
    changes = {
        'status': Task.STATUS_DONE,
        'lease_token': None,
        'locked_until': None,
        'last_error': '',
        'last_finished_at': finished_at,
        'updated_at': finished_at,
    }
    if task.name in (Task.NAME_RECONCILE_SEARCHES, Task.NAME_EXPIRE_UNSTARTED_GAMES,
                     Task.NAME_START_SCHEDULED_TOURNAMENTS, Task.NAME_EXPIRE_TOURNAMENT_ENTRY_DEADLINES):
        continuation = result.get('continuation') if isinstance(result, dict) else None
        changes.update(status=Task.STATUS_PENDING, kwargs=continuation or {}, attempts=0,
                       run_at=finished_at + timedelta(seconds=1 if continuation else EXPIRY_INTERVAL_SECONDS))
    completed = bool(owned.update(**changes))
    if not completed:
        logger.warning('event=task_lease_lost task_id=%s task_name=%s phase=completion', task.pk, task.name)
        return TaskRunOutcome.NOT_OWNED
    # Recurring no-op scans need not produce an INFO line on every tick.
    completion_log = logger.info if (
        task.name == Task.NAME_DELIVER_ADMIN_COMMAND or (type(result) is int and result > 0)
    ) else logger.debug
    completion_log('event=task_completed task_id=%s task_name=%s attempt=%s duration_ms=%s',
                   task.pk, task.name, task.attempts, int((time.perf_counter() - started_at) * 1000))
    return TaskRunOutcome.COMPLETED
