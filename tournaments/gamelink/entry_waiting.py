"""Adapt authenticated socket actions to the existing locked admission flow."""
import json

from django.db import transaction
from django.http import HttpRequest
from tournaments.models import Fixture, Tournament

from . import entry_presence
from .views import TournamentGameReadyView


def state(user, tournament_id, token, channel, *, join=False, fixture_id=None):
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

    try:
        response = TournamentGameReadyView().post(
            request, tournament_id, presence_change=presence_change, expected_fixture=fixture_id,
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
    Fixture.objects.select_for_update().filter(pk=fixture_id).first()
    changed = entry_presence.change(fixture_id, seat, token, channel,
                                    'disconnect' if disconnected else 'leave')
    if changed and not disconnected:
        transaction.on_commit(lambda: entry_presence.notify_fixture(fixture_id))
