"""Concurrency checks to run only against a disposable PostgreSQL test DB."""
from decimal import Decimal
import json
from threading import Barrier, Thread
from unittest import skipUnless
from uuid import uuid4

from django.contrib.auth.models import User
from django.db import connection, connections, transaction
from django.test import RequestFactory, TransactionTestCase

from frontend.api import api_admin_user_wallet
from tournaments.models import AdminWalletAdjustment, WalletTransaction


@skipUnless(connection.vendor == 'postgresql', 'Requires real PostgreSQL row locks')
class ConcurrentWalletAdjustmentTests(TransactionTestCase):
    def test_concurrent_retry_has_one_ledger_effect_and_matching_receipts(self):
        staff = User.objects.create_user(username='concurrent-wallet-admin', is_staff=True)
        player = User.objects.create_user(username='concurrent-wallet-player')
        payload = {
            'operation_id': str(uuid4()), 'action': 'deposit',
            'amount': '10.00', 'note': 'Concurrent correction',
        }
        start = Barrier(2, timeout=5)
        results, failures = [], []

        def adjust():
            database = connections['default']
            try:
                request = RequestFactory().post('/unused/', payload, content_type='application/json')
                request.user = staff
                with transaction.atomic():
                    with database.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout TO '5s'")
                    start.wait()
                    response = api_admin_user_wallet(request, pk=player.pk)
                results.append((response.status_code, response.content))
            except Exception as error:
                failures.append(error)
            finally:
                database.close()

        threads = [Thread(target=adjust, daemon=True) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0][0], 200)
        self.assertEqual(results[1][0], 200)
        # PostgreSQL jsonb may reorder receipt object keys; compare the recorded
        # response values rather than their incidental serialization order.
        self.assertEqual(json.loads(results[0][1]), json.loads(results[1][1]))
        self.assertEqual(AdminWalletAdjustment.objects.count(), 1)
        self.assertEqual(WalletTransaction.objects.count(), 1)
        self.assertEqual(WalletTransaction.balance_for_user(player), Decimal('10.00'))
