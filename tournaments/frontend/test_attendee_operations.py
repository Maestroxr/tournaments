import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from tournaments.models import Participant, Tournament, TournamentRegistration, UserContact, WalletTransaction


DEFINITION = """
stages:
  - id: main
    name: Main round
    mode: knockout
podium:
  - main.placements[0]
  - main.placements[1]
"""


class AttendeeOperationsTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='organizer', is_staff=True)
        self.players = [User.objects.create_user(username=f'player-{index}') for index in range(4)]
        for index, player in enumerate(self.players):
            UserContact.objects.create(user=player, phone_number=f'050-123-45{index:02d}')
        self.tournament = Tournament.load(
            DEFINITION,
            'Operations cup',
            creator=self.staff,
            published=True,
            min_players=2,
            max_players=2,
            entry_fee=Decimal('25.00'),
        )
        for player in self.players:
            WalletTransaction.create_entry(
                user=player,
                amount=Decimal('50.00'),
                kind=WalletTransaction.KIND_DEPOSIT,
                actor=self.staff,
            )
        self.url = reverse('api-admin-tournament-attendees', kwargs={'pk': self.tournament.pk})
        self.client.force_login(self.staff)

    def post_player(self, player, **extra):
        return self.client.post(
            self.url,
            data=json.dumps({'user_id': player.pk, **extra}),
            content_type='application/json',
        )

    def patch(self, participant_ids, action, **extra):
        return self.client.patch(
            self.url,
            data=json.dumps({'participant_ids': participant_ids, 'action': action, **extra}),
            content_type='application/json',
        )

    def participant_id(self, player):
        return Participant.objects.get(user=player).pk

    def test_admin_cannot_add_beyond_capacity(self):
        self.assertEqual(self.post_player(self.players[0]).status_code, 200)
        self.assertEqual(self.post_player(self.players[1]).status_code, 200)
        before = WalletTransaction.balance_for_user(self.players[2])

        response = self.post_player(self.players[2])

        self.assertEqual(response.status_code, 412, response.content)
        self.assertEqual(response.json()['code'], 'capacity_full')
        self.assertFalse(TournamentRegistration.objects.filter(
            tournament=self.tournament, participant__user=self.players[2]).exists())
        self.assertEqual(self.tournament.participations.count(), 2)
        self.assertEqual(WalletTransaction.balance_for_user(self.players[2]), before)

    def test_admin_cannot_add_a_legacy_player_without_a_phone_number(self):
        legacy_player = User.objects.create_user(username='legacy-no-phone')

        response = self.post_player(legacy_player)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('phone_number', response.json()['errors'])
        self.assertFalse(TournamentRegistration.objects.filter(
            tournament=self.tournament,
            participant__user=legacy_player,
        ).exists())

    def test_public_join_can_waitlist_only_after_capacity_closure(self):
        self.post_player(self.players[0])
        self.post_player(self.players[1])
        self.client.force_login(self.players[2])

        response = self.client.post(reverse('api-join', kwargs={'pk': self.tournament.pk}))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['registration_status'], 'waitlisted')
        self.client.force_login(self.staff)
        self.client.post(reverse('api-admin-tournament-reopen-registration', kwargs={'pk': self.tournament.pk}))
        self.client.post(reverse('api-admin-tournament-close-registration', kwargs={'pk': self.tournament.pk}))
        self.client.force_login(self.players[3])
        blocked = self.client.post(reverse('api-join', kwargs={'pk': self.tournament.pk}))
        self.assertEqual(blocked.status_code, 412)

    def test_check_in_does_not_affect_readiness_but_payment_does(self):
        self.post_player(self.players[0])
        participant_id = self.participant_id(self.players[0])

        initial = self.client.get(self.url).json()
        self.assertIsNone(initial['participants'][0]['checked_in_at'])
        self.assertFalse(initial['participants'][0]['requires_attention'])
        self.assertEqual(initial['participants'][0]['attention_reasons'], [])
        self.assertEqual(initial['summary']['attention'], 0)
        self.assertEqual(initial['summary']['ready'], 1)

        unpaid = self.patch([participant_id], 'mark_unpaid').json()
        self.assertTrue(unpaid['participants'][0]['requires_attention'])
        self.assertEqual(unpaid['participants'][0]['attention_reasons'], ['payment'])
        self.assertEqual(unpaid['summary']['attention'], 1)
        self.assertEqual(unpaid['summary']['ready'], 0)

        response = self.patch([participant_id], 'check_in')

        self.assertEqual(response.status_code, 200, response.content)
        row = response.json()['participants'][0]
        self.assertIsNotNone(row['checked_in_at'])
        self.assertTrue(row['requires_attention'])
        self.assertEqual(row['attention_reasons'], ['payment'])
        paid = self.patch([participant_id], 'mark_paid').json()
        self.assertFalse(paid['participants'][0]['requires_attention'])
        self.assertEqual(paid['summary']['ready'], 1)

    def test_registration_attention_does_not_require_check_in(self):
        participant = Participant.get_or_create_for_user(self.players[0])
        registration = TournamentRegistration.objects.create(
            tournament=self.tournament,
            participant=participant,
            payment_status=TournamentRegistration.PAYMENT_PAID,
        )

        self.assertIsNone(registration.checked_in_at)
        self.assertFalse(registration.requires_attention)

        registration.payment_status = TournamentRegistration.PAYMENT_UNPAID
        self.assertTrue(registration.requires_attention)

        registration.status = TournamentRegistration.STATUS_WAITLISTED
        registration.payment_status = TournamentRegistration.PAYMENT_PAID
        self.assertTrue(registration.requires_attention)

    def test_withdrawal_refunds_and_keeps_history(self):
        self.post_player(self.players[0])
        self.post_player(self.players[1])
        participant_id = self.participant_id(self.players[0])
        self.assertEqual(WalletTransaction.balance_for_user(self.players[0]), Decimal('25.00'))

        response = self.patch([participant_id], 'withdraw')

        self.assertEqual(response.status_code, 200, response.content)
        registration = TournamentRegistration.objects.get(
            tournament=self.tournament, participant_id=participant_id)
        self.assertEqual(registration.status, TournamentRegistration.STATUS_WITHDRAWN)
        self.assertEqual(registration.payment_status, TournamentRegistration.PAYMENT_REFUNDED)
        self.assertEqual(WalletTransaction.balance_for_user(self.players[0]), Decimal('50.00'))
        self.assertFalse(self.tournament.participations.filter(participant_id=participant_id).exists())
        self.tournament.refresh_from_db()
        self.assertTrue(self.tournament.registration_open)

    def test_restoring_without_a_refund_charges_the_entry_fee_again(self):
        self.post_player(self.players[0])
        participant_id = self.participant_id(self.players[0])

        response = self.patch([participant_id], 'withdraw', refund=False)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['refunded_count'], 0)
        registration = TournamentRegistration.objects.get(
            tournament=self.tournament, participant_id=participant_id)
        self.assertEqual(registration.status, TournamentRegistration.STATUS_WITHDRAWN)
        self.assertEqual(registration.payment_status, TournamentRegistration.PAYMENT_PAID)
        self.assertEqual(WalletTransaction.balance_for_user(self.players[0]), Decimal('25.00'))

        self.tournament.entry_fee = Decimal('20.00')
        self.tournament.save(update_fields=['entry_fee'])

        restored = self.post_player(self.players[0])

        self.assertEqual(restored.status_code, 200, restored.content)
        self.assertEqual(WalletTransaction.balance_for_user(self.players[0]), Decimal('5.00'))
        self.assertEqual(WalletTransaction.objects.filter(
            user=self.players[0], kind=WalletTransaction.KIND_TOURNAMENT_ENTRY).count(), 2)
        self.assertEqual(WalletTransaction.objects.filter(
            user=self.players[0],
            kind=WalletTransaction.KIND_TOURNAMENT_ENTRY,
        ).first().amount, Decimal('-20.00'))

        removed_again = self.patch([participant_id], 'withdraw', refund=False)
        self.assertEqual(removed_again.status_code, 200, removed_again.content)
        insufficient = self.post_player(self.players[0], charge_again=False)

        self.assertEqual(insufficient.status_code, 400, insufficient.content)
        self.assertEqual(insufficient.json()['code'], 'insufficient_funds')
        self.assertEqual(insufficient.json()['shortfall'], '15.00')
        self.assertEqual(WalletTransaction.balance_for_user(self.players[0]), Decimal('5.00'))
        self.assertEqual(WalletTransaction.objects.filter(
            user=self.players[0], kind=WalletTransaction.KIND_TOURNAMENT_ENTRY).count(), 2)
        registration.refresh_from_db()
        self.assertEqual(registration.status, TournamentRegistration.STATUS_WITHDRAWN)
        self.assertFalse(self.tournament.participations.filter(participant_id=participant_id).exists())

    def test_restoring_to_a_free_tournament_stays_free(self):
        self.tournament.entry_fee = Decimal('0.00')
        self.tournament.save(update_fields=['entry_fee'])
        initial_balance = WalletTransaction.balance_for_user(self.players[0])

        added = self.post_player(self.players[0])
        participant_id = self.participant_id(self.players[0])
        removed = self.patch([participant_id], 'withdraw', refund=False)
        restored = self.post_player(self.players[0], charge_again=True)

        self.assertEqual(added.status_code, 200, added.content)
        self.assertEqual(removed.status_code, 200, removed.content)
        self.assertEqual(restored.status_code, 200, restored.content)
        self.assertEqual(WalletTransaction.balance_for_user(self.players[0]), initial_balance)
        self.assertFalse(WalletTransaction.objects.filter(
            user=self.players[0],
            tournament=self.tournament,
            kind=WalletTransaction.KIND_TOURNAMENT_ENTRY,
        ).exists())

    def test_restore_action_also_charges_a_withdrawn_paid_player(self):
        self.post_player(self.players[0])
        participant_id = self.participant_id(self.players[0])
        self.patch([participant_id], 'withdraw', refund=False)

        restored = self.patch([participant_id], 'restore')

        self.assertEqual(restored.status_code, 200, restored.content)
        self.assertEqual(WalletTransaction.balance_for_user(self.players[0]), Decimal('0.00'))
        self.assertEqual(WalletTransaction.objects.filter(
            user=self.players[0],
            tournament=self.tournament,
            kind=WalletTransaction.KIND_TOURNAMENT_ENTRY,
        ).count(), 2)

    def test_waitlisted_player_can_be_promoted_after_a_place_opens(self):
        self.post_player(self.players[0])
        self.post_player(self.players[1])
        waitlisted = Participant.get_or_create_for_user(self.players[2])
        TournamentRegistration.objects.create(
            tournament=self.tournament,
            participant=waitlisted,
            status=TournamentRegistration.STATUS_WAITLISTED,
            payment_status=TournamentRegistration.PAYMENT_UNPAID,
        )
        first_id = self.participant_id(self.players[0])
        waitlisted_id = self.participant_id(self.players[2])
        self.patch([first_id], 'withdraw')

        response = self.patch([waitlisted_id], 'promote')

        self.assertEqual(response.status_code, 200, response.content)
        registration = TournamentRegistration.objects.get(
            tournament=self.tournament, participant_id=waitlisted_id)
        self.assertEqual(registration.status, TournamentRegistration.STATUS_REGISTERED)
        self.assertEqual(registration.payment_status, TournamentRegistration.PAYMENT_PAID)
        self.assertTrue(self.tournament.participations.filter(participant_id=waitlisted_id).exists())
        self.assertEqual(WalletTransaction.balance_for_user(self.players[2]), Decimal('25.00'))

    def test_internal_note_and_csv_export(self):
        self.post_player(self.players[0])
        participant_id = self.participant_id(self.players[0])
        updated = self.patch([participant_id], 'update_note', note='Bringing a physical board')
        self.assertEqual(updated.status_code, 200, updated.content)

        response = self.client.get(f'{self.url}?format=csv')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        content = response.content.decode('utf-8-sig')
        self.assertIn('player-0', content)
        self.assertIn('Bringing a physical board', content)
