"""Revision metadata follows database commits, independent of broker restarts."""
import json

from django.db import transaction
from django.db.models import F

from .models import LobbyRevision

REVISION_HEADER = 'X-Club-Revision'


def advance(groups, resource, using='default'):
    # The caller's transaction also rolls back these increments. Sort scopes
    # so private games lock both players' revision rows in a consistent order.
    with transaction.atomic(using=using):
        for scope in sorted(groups):
            row, _ = LobbyRevision.objects.using(using).get_or_create(resource=resource, scope=scope)
            LobbyRevision.objects.using(using).filter(pk=row.pk).update(sequence=F('sequence') + 1)


def current(resource, user_id=None, using='default'):
    from .lobby_events import TABLE_GROUP, TOURNAMENT_GROUP, user_group

    scopes = [TOURNAMENT_GROUP] if resource == 'tournaments' else [TABLE_GROUP]
    if resource == 'tables' and user_id is not None:
        scopes.append(user_group(user_id))
    rows = {row.scope: row for row in LobbyRevision.objects.using(using).filter(
        resource=resource, scope__in=scopes)}
    return {
        'generation': ':'.join(str(rows[scope].generation) if scope in rows else '0' for scope in scopes),
        'sequence': sum(rows[scope].sequence for scope in scopes if scope in rows),
    }


def current_revisions(user_id):
    return {resource: current(resource, user_id) for resource in ('tournaments', 'tables')}


def versioned_read(resource):
    """Capture before reading rows: concurrent writes must never be acknowledged early."""
    from functools import wraps

    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            revision = current(resource, getattr(request.user, 'pk', None)) if request.method == 'GET' else None
            response = view(request, *args, **kwargs)
            if revision is not None and response.status_code == 200:
                response[REVISION_HEADER] = json.dumps(revision, separators=(',', ':'))
                response['Cache-Control'] = 'private, no-store'
            return response
        return wrapped
    return decorate
