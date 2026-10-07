import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import connection
from django.test import RequestFactory, TransactionTestCase
from django.utils import timezone
from tournaments.models import Participant, Participation, Tournament, WalletTransaction

from . import api

DEFINITION = """
stages:
  - id: main
    name: Main round
    mode: knockout
podium:
  - main.placements[0]
  - main.placements[1]
"""


class TournamentJoinTests(TransactionTestCase):
    def setUp(self):
        self.player = User.objects.create_user(username='joining-player')
        self.tournament = Tournament.load(
            DEFINITION,
            'Join cup',
            creator=self.player,
            published=True,
            starts_at=timezone.now() + timedelta(hours=1),
            min_players=2,
            max_players=2,
            entry_fee=Decimal('10.00'),
        )
        WalletTransaction.create_entry(
            user=self.player,
            amount=100,
            kind=WalletTransaction.KIND_DEPOSIT,
        )
        self.factory = RequestFactory()

    def join(self, pk=None):
        request = self.factory.post('/api/tournaments/join', {}, content_type='application/json')
        request.user = self.player
        serialize = api._serialize_tournament
        prepare = Participant.get_or_create_for_user

        def serialize_unlocked(*args, **kwargs):
            self.assertFalse(connection.in_atomic_block, 'Response must be built after releasing the lock')
            return serialize(*args, **kwargs)

        def prepare_unlocked(*args, **kwargs):
            self.assertFalse(connection.in_atomic_block, 'Participant preparation must not hold the tournament lock')
            return prepare(*args, **kwargs)

        with (
            patch.object(api, '_serialize_tournament', side_effect=serialize_unlocked),
            patch.object(Participant, 'get_or_create_for_user', side_effect=prepare_unlocked),
        ):
            return api.api_join(request, pk=self.tournament.pk if pk is None else pk)

    def test_paid_registration_and_replay_charge_once(self):
        first = self.join()
        replay = self.join()

        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertTrue(json.loads(replay.content)['is_joined'])
        self.assertEqual(self.tournament.participations.count(), 1)
        self.assertEqual(self.tournament.registrations.count(), 1)
        self.assertEqual(self.tournament.wallet_transactions.filter(
            kind=WalletTransaction.KIND_TOURNAMENT_ENTRY,
        ).count(), 1)
        self.assertEqual(WalletTransaction.balance_for_user(self.player), Decimal('90.00'))

    def test_last_seat_closes_capacity_and_registered_player_can_replay(self):
        other = Participant.objects.create(name='other-player')
        Participation.objects.create(tournament=self.tournament, participant=other, slot_id=0)

        first = self.join()
        replay = self.join()

        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.registration_closed_reason, 'capacity')
        self.assertEqual(self.tournament.participations.count(), 2)
        self.assertEqual(WalletTransaction.balance_for_user(self.player), Decimal('90.00'))

    def test_manual_closure_still_rejects_registered_player(self):
        self.assertEqual(self.join().status_code, 200)
        self.tournament.registration_closed_at = timezone.now()
        self.tournament.registration_closed_reason = 'manual'
        self.tournament.save(update_fields=['registration_closed_at', 'registration_closed_reason'])

        response = self.join()

        self.assertEqual(response.status_code, 412)
        self.assertEqual(WalletTransaction.balance_for_user(self.player), Decimal('90.00'))

    def test_missing_tournament_does_not_create_participant(self):
        response = self.join(pk=self.tournament.pk + 1)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Participant.objects.filter(user=self.player).exists())

    def withdraw(self):
        request = self.factory.post('/api/tournaments/withdraw', {}, content_type='application/json')
        request.user = self.player
        return api.api_withdraw(request, pk=self.tournament.pk)

    def test_withdraw_from_full_tournament_refunds_once_and_reopens_registration(self):
        other = Participant.objects.create(name='other-player')
        Participation.objects.create(tournament=self.tournament, participant=other, slot_id=0)
        self.assertEqual(self.join().status_code, 200)

        first = self.withdraw()
        replay = self.withdraw()

        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertFalse(json.loads(first.content)['is_joined'])
        self.assertEqual(self.tournament.participations.count(), 1)
        self.assertEqual(WalletTransaction.balance_for_user(self.player), Decimal('100.00'))
        self.assertEqual(self.tournament.wallet_transactions.filter(
            kind=WalletTransaction.KIND_TOURNAMENT_REFUND,
        ).count(), 1)
        self.tournament.refresh_from_db()
        self.assertIsNone(self.tournament.registration_closed_at)
        self.assertEqual(self.tournament.registration_closed_reason, '')

    def test_manual_closure_blocks_withdrawal_without_refunding_or_removing_player(self):
        self.assertEqual(self.join().status_code, 200)
        self.tournament.registration_closed_at = timezone.now()
        self.tournament.registration_closed_reason = 'manual'
        self.tournament.save(update_fields=['registration_closed_at', 'registration_closed_reason'])

        response = self.withdraw()

        self.assertEqual(response.status_code, 412)
        self.assertEqual(self.tournament.participations.count(), 1)
        self.assertEqual(WalletTransaction.balance_for_user(self.player), Decimal('90.00'))
        self.assertFalse(self.tournament.wallet_transactions.filter(
            kind=WalletTransaction.KIND_TOURNAMENT_REFUND,
        ).exists())
