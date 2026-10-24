"""Money and template regressions confirmed by the October 24 review."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tournaments.models import (
    AdminWalletAdjustment, Participant, Participation, Tournament,
    TournamentRegistration, WalletTransaction,
)


class ManualWalletIdempotencyTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='wallet-review-admin', is_staff=True)
        self.player = User.objects.create_user(username='wallet-review-player')
        self.client.force_login(self.staff)
        self.url = reverse('api-admin-user-wallet', kwargs={'pk': self.player.pk})
        self.payload = {
            'operation_id': str(uuid4()), 'action': 'deposit',
            'amount': '10.00', 'note': 'Verified correction',
        }

    def post(self, **changes):
        return self.client.post(self.url, {**self.payload, **changes}, content_type='application/json')

    def test_retry_returns_the_original_receipt_after_other_activity(self):
        first = self.post()
        self.assertEqual(first.status_code, 200, first.content)
        WalletTransaction.create_entry(user=self.player, amount=Decimal('5.00'), kind='deposit')
        retry = self.post()
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertEqual(retry.json(), first.json())
        self.assertEqual(AdminWalletAdjustment.objects.count(), 1)
        self.assertEqual(WalletTransaction.balance_for_user(self.player), Decimal('15.00'))

    def test_key_cannot_be_reused_with_different_intent_actor_or_wallet(self):
        self.assertEqual(self.post().status_code, 200)
        for changes in ({'amount': '11.00'}, {'note': 'Another correction'}, {'action': 'withdraw'}):
            self.assertEqual(self.post(**changes).status_code, 409)
        other = User.objects.create_user(username='other-wallet', is_staff=True)
        other_url = reverse('api-admin-user-wallet', kwargs={'pk': other.pk})
        self.assertEqual(self.client.post(other_url, self.payload, content_type='application/json').status_code, 409)
        self.client.force_login(other)
        self.assertEqual(self.post().status_code, 409)
        self.assertEqual(WalletTransaction.objects.count(), 1)

    def test_identical_new_intent_can_use_a_new_key(self):
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(self.post(operation_id=str(uuid4())).status_code, 200)
        self.assertEqual(WalletTransaction.balance_for_user(self.player), Decimal('20.00'))

    def test_missing_key_is_rejected_without_writing(self):
        self.assertEqual(self.post(operation_id=None).status_code, 400)
        self.assertFalse(WalletTransaction.objects.exists())

    def test_failure_to_persist_receipt_rolls_back_wallet_entry(self):
        with patch.object(AdminWalletAdjustment.objects, 'create', side_effect=RuntimeError('receipt unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'receipt unavailable'):
                self.post()
        self.assertFalse(WalletTransaction.objects.exists())
        self.assertFalse(AdminWalletAdjustment.objects.exists())


class WithdrawalAndBreadcrumbTests(TestCase):
    def setUp(self):
        self.player = User.objects.create_user(username='withdraw-review-player', is_staff=True)
        self.participant = Participant.get_or_create_for_user(self.player)
        self.tournament = Tournament.objects.create(
            name='<img src=x onerror="window.reviewMarker=1">', creator=self.player,
            published=True, entry_fee=Decimal('100.00'), podium_spec=[],
            starts_at=timezone.now() + timedelta(days=1),
        )
        Participation.objects.create(tournament=self.tournament, participant=self.participant, slot_id=0)
        self.registration = TournamentRegistration.objects.create(
            tournament=self.tournament, participant=self.participant,
            payment_status=TournamentRegistration.PAYMENT_WAIVED,
        )
        self.client.force_login(self.player)
        self.legacy_url = reverse('withdraw-tournament', kwargs={'pk': self.tournament.pk})
        self.api_url = reverse('api-withdraw', kwargs={'pk': self.tournament.pk})

    def test_legacy_get_cannot_change_membership_or_wallet(self):
        self.assertEqual(self.client.get(self.legacy_url).status_code, 405)
        self.assertEqual(self.tournament.participations.count(), 1)
        self.assertFalse(WalletTransaction.objects.exists())

    def test_waived_legacy_post_and_api_retry_never_mint_a_refund(self):
        self.assertEqual(self.client.post(self.legacy_url).status_code, 302)
        self.assertEqual(self.client.post(self.api_url).status_code, 200)
        self.assertEqual(self.tournament.participations.count(), 0)
        self.assertFalse(WalletTransaction.objects.exists())
        self.registration.refresh_from_db()
        self.assertEqual(self.registration.payment_status, TournamentRegistration.PAYMENT_WAIVED)

    def test_paid_legacy_post_refunds_actual_reserve_once_after_fee_changes(self):
        WalletTransaction.create_entry(user=self.player, amount=Decimal('75.00'), kind='deposit')
        WalletTransaction.create_entry(
            user=self.player, amount=Decimal('-75.00'),
            kind=WalletTransaction.KIND_TOURNAMENT_ENTRY, tournament=self.tournament,
        )
        self.registration.payment_status = TournamentRegistration.PAYMENT_PAID
        self.registration.save(update_fields=['payment_status'])
        self.assertEqual(self.client.post(self.legacy_url).status_code, 302)
        self.assertEqual(self.client.post(self.api_url).status_code, 200)
        self.assertEqual(WalletTransaction.balance_for_user(self.player), Decimal('75.00'))
        self.assertEqual(WalletTransaction.objects.filter(kind=WalletTransaction.KIND_TOURNAMENT_REFUND).count(), 1)

    def test_manual_closure_blocks_both_paths_without_refund(self):
        self.tournament.registration_closed_at = timezone.now()
        self.tournament.registration_closed_reason = 'manual'
        self.tournament.save(update_fields=['registration_closed_at', 'registration_closed_reason'])
        for url in (self.legacy_url, self.api_url):
            self.assertEqual(self.client.post(url).status_code, 412)
        self.assertEqual(self.tournament.participations.count(), 1)
        self.assertFalse(WalletTransaction.objects.exists())

    def test_tournament_name_is_escaped_in_rendered_breadcrumb(self):
        response = self.client.get(reverse('update-tournament', kwargs={'pk': self.tournament.pk}))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotContains(response, '<img src=x onerror=')
        self.assertContains(response, '&lt;img src=x onerror=')
