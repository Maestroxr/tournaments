"""Incident diagnostics without SQL parameters, request bodies, or bearer URLs."""
from contextvars import ContextVar
from contextlib import ExitStack
import json
import logging
import os
from time import monotonic
import uuid

from django.conf import settings
from django.db import OperationalError, connections


logger = logging.getLogger('django.incident')
request_context = ContextVar('incident_request_context', default=None)


def incident_event(event, *, level=logging.INFO, **fields):
    context = request_context.get() or {}
    logger.log(level, '%s', json.dumps(
        {'event': event, 'pid': os.getpid(), **context, **fields},
        ensure_ascii=False, default=str, sort_keys=True,
    ))


class QueryDiagnostics:
    def __init__(self):
        self.count = 0
        self.milliseconds = 0.0
        self.write_count = 0

    def __call__(self, execute, sql, params, many, context):
        started = monotonic()
        operation = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else 'UNKNOWN'
        self.count += 1
        self.write_count += operation in ('INSERT', 'UPDATE', 'DELETE', 'BEGIN')
        try:
            return execute(sql, params, many, context)
        except OperationalError as error:
            # The operation type is safe. Full SQL and parameters may include
            # personal data or credentials and are deliberately never recorded.
            if 'locked' in str(error).lower():
                incident_event('db_lock_failed', level=logging.ERROR,
                               operation=operation, alias=context['connection'].alias,
                               wait_ms=round((monotonic() - started) * 1000, 1),
                               error_type=type(error).__name__)
            raise
        finally:
            self.milliseconds += (monotonic() - started) * 1000


class IncidentDiagnosticsMiddleware:
    """Measure sync Django request work even with DEBUG disabled.

    Django adapts this sync middleware when served by Daphne. The temporary
    execute wrappers live on the same thread-local connections as the views.
    """
    def __init__(self, get_response):
        self.get_response = get_response
        incident_event('application_config', level=logging.WARNING if settings.DEBUG else logging.INFO,
                       debug=settings.DEBUG, settings_module=getattr(settings, 'SETTINGS_MODULE', None),
                       database_engine=settings.DATABASES['default']['ENGINE'],
                       database_timeout=settings.DATABASES['default'].get('OPTIONS', {}).get('timeout'))

    def __call__(self, request):
        request.incident_request_id = uuid.uuid4().hex
        request.request_id = request.incident_request_id
        # request.path excludes ?ticket= and ?token= and is never a body/URL.
        token = request_context.set({'request_id': request.incident_request_id,
                                     'method': request.method, 'path': request.path})
        started = monotonic()
        diagnostics = QueryDiagnostics()
        response = None
        try:
            with ExitStack() as stack:
                for connection in connections.all():
                    stack.enter_context(connection.execute_wrapper(diagnostics))
                response = self.get_response(request)
            response['X-Request-ID'] = request.incident_request_id
            return response
        finally:
            duration = (monotonic() - started) * 1000
            status = response.status_code if response is not None else 500
            match = getattr(request, 'resolver_match', None)
            ids = {key: value for key, value in (match.kwargs if match else {}).items()
                   if key in ('pk', 'fixture_id', 'tournament_id') and isinstance(value, int)}
            if status >= 500 or duration >= getattr(settings, 'INCIDENT_SLOW_REQUEST_MS', 1500) \
                    or diagnostics.count >= getattr(settings, 'INCIDENT_QUERY_BUDGET', 100):
                incident_event('request_failed' if status >= 500 else 'request_slow',
                               level=logging.ERROR if status >= 500 else logging.WARNING,
                               status=status, duration_ms=round(duration, 1),
                               db_ms=round(diagnostics.milliseconds, 1), sql_count=diagnostics.count,
                               writes=diagnostics.write_count, route=match.url_name if match else None, **ids)
            request_context.reset(token)
