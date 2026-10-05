"""Fence local task mutations without holding locks during remote requests."""
from contextlib import contextmanager
from contextvars import ContextVar

from django.db import connection

_owned_task = ContextVar('tournament_owned_task', default=None)


@contextmanager
def task_ownership(owned):
    token = _owned_task.set(owned)
    try:
        yield
    finally:
        _owned_task.reset(token)


def fence_task_ownership():
    owned = _owned_task.get()
    if owned is None:
        return
    if not connection.in_atomic_block:
        raise RuntimeError('Task ownership fencing requires an atomic transaction')
    # Business parent locks precede the queue row. Claim/completion never hold
    # business locks, so the lease row cannot introduce an opposite lock order.
    if owned.select_for_update().only('pk').first() is None:
        raise RuntimeError('Tournament task lease was replaced before mutation')
