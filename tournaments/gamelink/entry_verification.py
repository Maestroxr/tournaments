"""Short, socket-owned admission confirmations, serialized by fixture row locks."""
import json
import uuid

from django.conf import settings

from . import entry_presence

CONFIRM_SECONDS = 5
_memory = {}


def _key(fixture_id):
    return entry_presence._keys(fixture_id, 'verification')[0]


def _read(fixture_id):
    if entry_presence._uses_memory():
        return _memory.get(fixture_id)
    raw = entry_presence._client(settings.REDIS_URL).get(_key(fixture_id))
    return json.loads(raw) if raw else None


def _write(fixture_id, value):
    if entry_presence._uses_memory():
        _memory[fixture_id] = value
    else:
        entry_presence._client(settings.REDIS_URL).set(_key(fixture_id), json.dumps(value), ex=60)


def clear(fixture_id):
    if entry_presence._uses_memory():
        _memory.pop(fixture_id, None)
    else:
        entry_presence._client(settings.REDIS_URL).delete(_key(fixture_id))


def _live(fixture_id, seat, owner, now):
    return bool(owner and entry_presence.attempt_present(
        fixture_id, seat, owner['token'], owner['channel'], now))


def current(fixture, now):
    if not fixture.player1_id or not fixture.player2_id:
        return None
    value = _read(fixture.pk)
    pair = [fixture.player1.user_id, fixture.player2.user_id]
    if not value or value['pair'] != pair or value['until'] <= now.timestamp():
        return None
    return value


def update(fixture, seat, token, channel, now, *, verification_id=None, reserved=False):
    """Only a response to the current round can confirm a current connection.

    An existing reserved room retains its durable pair grant; a returning screen
    must still confirm itself, while the game service checks both actual sockets.
    """
    value = current(fixture, now)
    changed = False
    if value is None:
        value = {'id': uuid.uuid4().hex, 'pair': [fixture.player1.user_id, fixture.player2.user_id],
                 'until': now.timestamp() + CONFIRM_SECONDS, 'owners': {}}
        changed = True
    if verification_id == value['id'] and entry_presence.attempt_present(
            fixture.pk, seat, token, channel, now):
        owner = {'token': token, 'channel': channel}
        if value['owners'].get(seat) != owner:
            value['owners'][seat] = owner
            changed = True
    if changed:
        _write(fixture.pk, value)
    own = value['owners'].get(seat)
    own_ready = (own == {'token': token, 'channel': channel}
                 and _live(fixture.pk, seat, own, now))
    both = own_ready and (reserved or all(
        _live(fixture.pk, other, value['owners'].get(other), now) for other in ('p1', 'p2')))
    return value['id'], bool(both), changed, max(0.01, value['until'] - now.timestamp())


def can_admit(fixture, seat, token, verification_id, now, *, reserved=False):
    value = current(fixture, now)
    if not value or value['id'] != verification_id:
        return False
    own = value['owners'].get(seat)
    if not own or own['token'] != token or not _live(fixture.pk, seat, own, now):
        return False
    return reserved or all(_live(fixture.pk, other, value['owners'].get(other), now)
                           for other in ('p1', 'p2'))


def pair_verified(fixture, now):
    value = current(fixture, now)
    return bool(value and all(_live(fixture.pk, seat, value['owners'].get(seat), now)
                              for seat in ('p1', 'p2')))


def seat_verified(fixture, seat, now):
    value = current(fixture, now)
    return bool(value and _live(fixture.pk, seat, value['owners'].get(seat), now))


def release_owner(fixture_id, seat, token, channel):
    """Another tab leaving must not invalidate the confirmed live tab."""
    value = _read(fixture_id)
    if value and value['owners'].get(seat) == {'token': token, 'channel': channel}:
        clear(fixture_id)
        return True
    return False
