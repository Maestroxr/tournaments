"""Adapt authenticated socket actions to the existing locked admission flow."""
import json

from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone
from tournaments.models import Fixture, Tournament

from . import entry_presence, entry_verification
from .models import GameLink
from .views import TournamentGameReadyView, _clear_unissued_entry, _reserved_entry


def state(user, tournament_id, token, channel, *, join=False, fixture_id=None, verification_id=None):
    request = HttpRequest()
    request.user = user
    request.method = 'POST'
    joined = []

    def presence_change(fixture, seat, link, now):
        if not join:
            return False
        was_present = entry_presence.seat_present(fixture.pk, seat, now)
        entry_presence.change(fixture.pk, seat, token, channel, 'join', now)
        joined.append((fixture.pk, seat))
        # An old HTTP heartbeat must not keep a cancelled socket attempt ready.
        field = f'{seat}_ready_at'
        if getattr(link, field) is not None:
            setattr(link, field, None)
            link.save(update_fields=[field])
        transaction.on_commit(lambda: entry_presence.notify_fixture(fixture.pk))
        return not was_present

    def verification_check(fixture, seat, link, now):
        reserved = _reserved_entry(link, fixture)
        if not entry_presence.attempt_present(fixture.pk, seat, token, channel, now):
            return None, False, None
        if not reserved and not all(entry_presence.seat_present(fixture.pk, other, now)
                                    for other in ('p1', 'p2')):
            return None, False, None
        challenge, ready, changed, remaining = entry_verification.update(
            fixture, seat, token, channel, now, verification_id=verification_id, reserved=reserved)
        if changed:
            transaction.on_commit(lambda: entry_presence.notify_fixture(fixture.pk))
        return challenge, ready, remaining

    try:
        response = TournamentGameReadyView().post(
            request, tournament_id, presence_change=presence_change, expected_fixture=fixture_id,
            verification_check=verification_check,
        )
        if response.status_code != 200:
            for fixture, seat in joined:
                entry_presence.change(fixture, seat, token, channel, 'leave')
            return {'type': 'entry_rejected', 'attempt_id': token, 'status': response.status_code}
        data = json.loads(response.content)
        if fixture_id is not None and data['fixture_id'] != fixture_id:
            return {'type': 'entry_rejected', 'attempt_id': token, 'status': 412}
        return {'type': 'entry_state', 'attempt_id': token, 'state': data}
    except Exception:
        # Redis is outside the SQL transaction. Roll back a marker if admission
        # or push enqueueing failed, with the same owner fence as normal cleanup.
        for fixture, seat in joined:
            entry_presence.change(fixture, seat, token, channel, 'leave')
        raise


@transaction.atomic
def release(binding, channel, *, disconnected=False):
    tournament_id, fixture_id, seat, token = binding
    # Match the admission lock order. Explicit cancellation and paired approval
    # have one ordering even when they arrive at the same instant.
    Tournament.objects.select_for_update().filter(pk=tournament_id).first()
    fixture = Fixture.objects.select_for_update(of=('self',)).select_related(
        'player1__user', 'player2__user').filter(pk=fixture_id).first()
    # A lost/backgrounded waiting screen is no longer ready. Reconnects have a
    # new owner fence, so old socket cleanup cannot remove a resumed attempt.
    changed = entry_presence.change(fixture_id, seat, token, channel, 'leave')
    if changed:
        link = GameLink.objects.select_for_update().filter(fixture_id=fixture_id).first()
        reserved = bool(link and fixture and _reserved_entry(link, fixture))
        if not reserved:
            if not entry_presence.seat_present(fixture_id, seat, timezone.now()):
                entry_verification.clear(fixture_id)
            else:
                entry_verification.release_owner(fixture_id, seat, token, channel)
            if (link and link.entry_authorized_at
                    and (not fixture or not entry_verification.pair_verified(fixture, timezone.now()))):
                _clear_unissued_entry(link)
        transaction.on_commit(lambda: entry_presence.notify_fixture(fixture_id))
