"""Exercise real file-backed concurrent writers, not the in-memory test DB."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest import TestCase

from django.conf import settings
from tournaments.db.backends.sqlite3.base import DatabaseWrapper


class SQLiteConcurrencyTests(TestCase):
    def test_waiting_writer_reads_the_committed_value(self):
        with TemporaryDirectory() as folder:
            config = deepcopy(settings.DATABASES['default'])
            config['NAME'] = str(Path(folder) / 'concurrent.sqlite3')
            config['OPTIONS'] = {'timeout': 5}
            first = DatabaseWrapper(config, alias='concurrency-test')
            attempted = Event()
            acquired = Event()

            def second_writer():
                second = DatabaseWrapper(deepcopy(config), alias='concurrency-test-2')
                try:
                    second.ensure_connection()
                    attempted.set()
                    second._start_transaction_under_autocommit()
                    acquired.set()
                    with second.cursor() as cursor:
                        cursor.execute('SELECT amount FROM balance')
                        amount = cursor.fetchone()[0]
                        cursor.execute('UPDATE balance SET amount = %s', [amount + 1])
                    second.connection.commit()
                    return amount
                finally:
                    second.close()

            try:
                with first.cursor() as cursor:
                    cursor.execute('CREATE TABLE balance (amount integer)')
                    cursor.execute('INSERT INTO balance VALUES (0)')
                first._start_transaction_under_autocommit()
                with first.cursor() as cursor:
                    cursor.execute('SELECT amount FROM balance')
                    self.assertEqual(cursor.fetchone()[0], 0)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(second_writer)
                    try:
                        self.assertTrue(attempted.wait(2))
                        self.assertFalse(acquired.wait(.1))
                        with first.cursor() as cursor:
                            cursor.execute('UPDATE balance SET amount = 1')
                        first.connection.commit()
                    finally:
                        first.connection.rollback()
                    self.assertEqual(future.result(timeout=6), 1)
                with first.cursor() as cursor:
                    cursor.execute('SELECT amount FROM balance')
                    self.assertEqual(cursor.fetchone()[0], 2)
            finally:
                first.close()
