"""SQLite write admission for the project's pinned Django 4.2 backend."""
import logging
from time import monotonic

from django.db import OperationalError
from django.db.backends.sqlite3.base import DatabaseWrapper as SQLiteDatabaseWrapper
from tournaments.observability import incident_event


class DatabaseWrapper(SQLiteDatabaseWrapper):
    def _start_transaction_under_autocommit(self):
        # Deferred BEGIN can read a snapshot and then fail immediately when
        # upgrading to a writer, bypassing busy_timeout. Reserve the writer
        # before any reads so concurrent workers wait instead. Django continues
        # to manage commit, rollback and nested savepoints normally.
        self._observe_transaction('begin_immediate', lambda: self.cursor().execute('BEGIN IMMEDIATE'))
        self._incident_writer_started = monotonic()

    def _commit(self):
        result = self._observe_transaction('commit', super()._commit)
        self._report_writer_end('commit')
        return result

    def _rollback(self):
        try:
            return super()._rollback()
        finally:
            self._report_writer_end('rollback')

    def _report_writer_end(self, operation):
        started = getattr(self, '_incident_writer_started', None)
        self._incident_writer_started = None
        if started is None:
            return
        duration = (monotonic() - started) * 1000
        if duration >= 1000:
            incident_event('sqlite_writer_held', level=logging.WARNING,
                           operation=operation, alias=self.alias, duration_ms=round(duration, 1))

    def _observe_transaction(self, operation, callback):
        started = monotonic()
        try:
            return callback()
        except OperationalError as error:
            if 'locked' in str(error).lower():
                incident_event('sqlite_transaction_locked', level=logging.ERROR,
                               operation=operation, alias=self.alias,
                               wait_ms=round((monotonic() - started) * 1000, 1),
                               timeout_seconds=self.settings_dict.get('OPTIONS', {}).get('timeout', 5),
                               error_type=type(error).__name__)
            raise
        finally:
            duration = (monotonic() - started) * 1000
            if duration >= 1000:
                incident_event('sqlite_transaction_slow', level=logging.WARNING,
                               operation=operation, alias=self.alias, duration_ms=round(duration, 1))
