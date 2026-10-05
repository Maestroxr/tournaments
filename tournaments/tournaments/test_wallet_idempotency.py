from decimal import Decimal
from threading import Barrier, Thread
from unittest import skipUnless

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from .models import HeadToHeadTable, Tournament, WalletTransaction as Ledger


class WalletIdempotencyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='wallet-owner')
        self.other = User.objects.create(username='wallet-other')
        self.tournament = Tournament.objects.create(name='Wallet cup', podium_spec=[], starts_at=timezone.now())
        self.table = HeadToHeadTable.objects.create(
            code='WALLET', host=self.user, mode='match', amount=10, fee_percent=0, fee_per_player=0,
        )
        Ledger.create_entry(user=self.user, amount=100, kind=Ledger.KIND_DEPOSIT)

    def test_tournament_prize_replay_returns_the_original_transaction(self):
        first = Ledger.create_entry(user=self.user, tournament=self.tournament,
                                    amount=20, kind=Ledger.KIND_TOURNAMENT_PRIZE)
        second = Ledger.create_entry(user=self.user, tournament=self.tournament,
                                     amount=20, kind=Ledger.KIND_TOURNAMENT_PRIZE)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Ledger.balance_for_user(self.user), Decimal('120'))

    def test_different_winner_or_prize_cannot_replace_an_award(self):
        Ledger.create_entry(user=self.user, tournament=self.tournament,
                            amount=20, kind=Ledger.KIND_TOURNAMENT_PRIZE)
        for user, amount in ((self.other, 20), (self.user, 21)):
            with self.subTest(user=user.pk, amount=amount), self.assertRaises(ValidationError):
                Ledger.create_entry(user=user, tournament=self.tournament,
                                    amount=amount, kind=Ledger.KIND_TOURNAMENT_PRIZE)

    def test_database_rejects_a_second_prize_even_when_helper_is_bypassed(self):
        for field, parent, kind in (
            ('tournament', self.tournament, Ledger.KIND_TOURNAMENT_PRIZE),
            ('head_to_head_table', self.table, Ledger.KIND_HEAD_TO_HEAD_PRIZE),
        ):
            Ledger.create_entry(user=self.user, amount=20, kind=kind, **{field: parent})
            with self.subTest(kind=kind), self.assertRaises(IntegrityError), transaction.atomic():
                Ledger.objects.create(user=self.other, amount=20, balance_after=20, kind=kind,
                                      **{field: parent})

    def test_refund_uses_paid_remainder_and_allows_a_new_registration_cycle(self):
        Ledger.create_entry(user=self.user, tournament=self.tournament,
                            amount=-10, kind=Ledger.KIND_TOURNAMENT_ENTRY)
        # An earlier partial refund is financial history, not a reason to skip
        # the remaining paid entry or to refund the whole entry fee again.
        Ledger.create_entry(user=self.user, tournament=self.tournament,
                            amount=3, kind=Ledger.KIND_TOURNAMENT_REFUND)
        refund = Ledger.refund_entry_fees(user=self.user, tournament=self.tournament)
        self.assertEqual(refund.amount, Decimal('7'))
        self.assertIsNone(Ledger.refund_entry_fees(user=self.user, tournament=self.tournament))
        Ledger.create_entry(user=self.user, tournament=self.tournament,
                            amount=-12, kind=Ledger.KIND_TOURNAMENT_ENTRY)
        self.assertEqual(Ledger.refund_entry_fees(user=self.user, tournament=self.tournament).amount, 12)
        self.assertEqual(Ledger.balance_for_user(self.user), 100)

    def test_stale_paid_registration_does_not_refund_twice(self):
        from frontend.api import _refund_registration
        from .models import Participant, TournamentRegistration
        self.tournament.entry_fee = Decimal('10')
        self.tournament.save(update_fields=['entry_fee'])
        registration = TournamentRegistration.objects.create(
            tournament=self.tournament, participant=Participant.create_for_user(self.user), payment_status='paid',
        )
        stale = TournamentRegistration.objects.get(pk=registration.pk)
        Ledger.create_entry(user=self.user, tournament=self.tournament,
                            amount=-10, kind=Ledger.KIND_TOURNAMENT_ENTRY)
        _refund_registration(self.tournament, registration, None)
        _refund_registration(self.tournament, stale, None)
        self.assertEqual(Ledger.objects.filter(kind=Ledger.KIND_TOURNAMENT_REFUND).count(), 1)

    def test_cancellation_refund_cannot_release_a_settled_loser_reservation(self):
        Ledger.create_entry(user=self.user, head_to_head_table=self.table,
                            amount=-10, kind=Ledger.KIND_HEAD_TO_HEAD_ENTRY)
        HeadToHeadTable.objects.filter(pk=self.table.pk).update(status='completed')
        with self.assertRaises(ValidationError):
            Ledger.refund_entry_fees(user=self.user, head_to_head_table=self.table)
        self.assertEqual(Ledger.balance_for_user(self.user), 90)

    def test_cancellation_settlement_releases_only_remaining_reserve(self):
        from frontend.game_formats import settle
        Ledger.create_entry(user=self.user, head_to_head_table=self.table,
                            amount=-10, kind=Ledger.KIND_HEAD_TO_HEAD_ENTRY)
        Ledger.create_entry(user=self.user, head_to_head_table=self.table,
                            amount=3, kind=Ledger.KIND_HEAD_TO_HEAD_REFUND)
        for _ in range(2):
            with transaction.atomic():
                table = HeadToHeadTable.objects.select_for_update().get(pk=self.table.pk)
                settle(table, {'status': 'cancelled', 'room_id': 'cancelled-room'})
        refunds = list(Ledger.objects.filter(kind=Ledger.KIND_HEAD_TO_HEAD_REFUND).values_list('amount', flat=True))
        self.assertCountEqual(refunds, [Decimal('3'), Decimal('7')])
        self.assertEqual(Ledger.balance_for_user(self.user), 100)

    def test_refund_rolls_back_with_cancellation_failure(self):
        Ledger.create_entry(user=self.user, head_to_head_table=self.table,
                            amount=-10, kind=Ledger.KIND_HEAD_TO_HEAD_ENTRY)
        with self.assertRaises(RuntimeError), transaction.atomic():
            Ledger.refund_entry_fees(user=self.user, head_to_head_table=self.table)
            raise RuntimeError('cancellation failed')
        self.assertEqual(Ledger.balance_for_user(self.user), 90)


@skipUnless(connection.vendor == 'postgresql', 'Requires real PostgreSQL concurrency')
class ConcurrentWalletTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create(username='concurrent-wallet')
        self.tournament = Tournament.objects.create(name='Concurrent cup', podium_spec=[], starts_at=timezone.now())
        Ledger.create_entry(user=self.user, amount=100, kind=Ledger.KIND_DEPOSIT)

    def parallel(self, operation):
        gate = Barrier(2)
        results, errors = [], []

        def run():
            database = connections['default']
            try:
                with database.cursor() as cursor:
                    cursor.execute("SET lock_timeout TO '5s'")
                gate.wait(timeout=5)
                result = operation()
                results.append(result.pk if result is not None else None)
            except Exception as error:
                errors.append(error)
            finally:
                database.close()

        threads = [Thread(target=run, daemon=True) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertTrue(all(not thread.is_alive() for thread in threads), 'Wallet operation stalled')
        self.assertEqual(errors, [])
        return results

    def test_two_workers_award_only_one_prize(self):
        results = self.parallel(lambda: Ledger.create_entry(
            user=self.user, tournament=self.tournament, amount=20, kind=Ledger.KIND_TOURNAMENT_PRIZE))
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(Ledger.balance_for_user(self.user), 120)

    def test_two_cancellations_refund_only_one_paid_reserve(self):
        Ledger.create_entry(user=self.user, tournament=self.tournament,
                            amount=-10, kind=Ledger.KIND_TOURNAMENT_ENTRY)
        results = self.parallel(lambda: Ledger.refund_entry_fees(user=self.user, tournament=self.tournament))
        self.assertEqual(results.count(None), 1)
        self.assertEqual(Ledger.objects.filter(kind=Ledger.KIND_TOURNAMENT_REFUND).count(), 1)
        self.assertEqual(Ledger.balance_for_user(self.user), 100)
