"""SQLite write admission for the project's pinned Django 4.2 backend."""
from django.db.backends.sqlite3.base import DatabaseWrapper as SQLiteDatabaseWrapper


class DatabaseWrapper(SQLiteDatabaseWrapper):
    def _start_transaction_under_autocommit(self):
        # Deferred BEGIN can read a snapshot and then fail immediately when
        # upgrading to a writer, bypassing busy_timeout. Reserve the writer
        # before any reads so concurrent workers wait instead. Django continues
        # to manage commit, rollback and nested savepoints normally.
        self.cursor().execute('BEGIN IMMEDIATE')
