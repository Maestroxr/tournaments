from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from tournaments.models import Participant, Participation, Tournament, WalletTransaction


class TournamentPrizeTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='prize-organizer', is_staff=True)
        self.winner = User.objects.create_user(username='prize-winner')
        self.other = User.objects.create_user(username='prize-other')
        self.client.force_login(self.staff)
        self.player_client = Client()
        for user in (self.winner, self.other):
            WalletTransaction.create_entry(
                user=user, amount='1000.00', kind=WalletTransaction.KIND_DEPOSIT,
            )
        self.payload = {
            'name': 'Fixed prize tournament', 'template': 'knockout',
            'min_players': 2, 'max_players': 8, 'open_registration': True,
            'entry_fee': 100, 'prize_money': 1000, 'prize_type': 'coins',
            'prize_text': '', 'platform_fee_percent': 10,
            'starts_at': (timezone.now() + timedelta(days=1)).isoformat(),
        }

    def create_tournament(self, **overrides):
        response = self.client.post(
            reverse('api-admin-tournaments'), {**self.payload, **overrides},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        return Tournament.objects.get(pk=response.json()['id']), response.json()

    def collect_entries(self, tournament):
        for user in (self.winner, self.other):
            WalletTransaction.create_entry(
                user=user, amount='-100.00',
                kind=WalletTransaction.KIND_TOURNAMENT_ENTRY,
                tournament=tournament,
            )

    def set_winner(self, tournament):
        Participation.objects.create(
            tournament=tournament,
            participant=Participant.get_or_create_for_user(self.winner),
            slot_id=0, podium_position=0,
        )

    def assert_api_prize(self, tournament, amount, configured):
        for client, prefix in ((self.client, 'api-admin-'), (self.player_client, 'api-')):
            with self.subTest(audience=prefix):
                listing = client.get(reverse(f'{prefix}tournaments'))
                self.assertEqual(listing.status_code, 200, listing.content)
                listed = next(item for item in listing.json() if item['id'] == tournament.pk)
                detail = client.get(reverse(f'{prefix}tournament-detail', args=[tournament.pk]))
                self.assertEqual(detail.status_code, 200, detail.content)
                for data in (listed, detail.json()):
                    self.assertEqual(Decimal(data['prize_money']), Decimal(amount))
                    self.assertEqual(Decimal(str(data['prizeMoney'])), Decimal(amount))
                    if prefix == 'api-admin-':
                        self.assertEqual(Decimal(data['configured_prize_money']), Decimal(configured))

    def test_paid_entry_fixed_prize_is_visible_before_any_entries(self):
        tournament, created = self.create_tournament()
        self.assertEqual(tournament.prize_money, Decimal('1000.00'))
        self.assertEqual(tournament.collected_entry_fees, Decimal('0.00'))
        self.assertEqual(Decimal(created['prize_money']), Decimal('1000.00'))
        self.assertEqual(Decimal(created['configured_prize_money']), Decimal('1000.00'))
        self.assert_api_prize(tournament, '1000.00', '1000.00')

    def test_collected_entries_and_refunds_do_not_change_fixed_prize(self):
        tournament, _ = self.create_tournament()
        self.collect_entries(tournament)
        self.assertEqual(tournament.collected_entry_fees, Decimal('200.00'))
        self.assert_api_prize(tournament, '1000.00', '1000.00')
        WalletTransaction.create_entry(
            user=self.other, amount='100.00',
            kind=WalletTransaction.KIND_TOURNAMENT_REFUND,
            tournament=tournament,
        )
        self.assertEqual(tournament.collected_entry_fees, Decimal('100.00'))
        self.assert_api_prize(tournament, '1000.00', '1000.00')

    def test_fixed_prize_pays_exactly_once(self):
        tournament, _ = self.create_tournament()
        self.collect_entries(tournament)
        self.set_winner(tournament)
        tournament.award_prize_money()
        tournament.award_prize_money()
        prize = WalletTransaction.objects.get(
            tournament=tournament, kind=WalletTransaction.KIND_TOURNAMENT_PRIZE,
        )
        self.assertEqual(prize.user_id, self.winner.pk)
        self.assertEqual(prize.amount, Decimal('1000.00'))
        self.assertEqual(WalletTransaction.balance_for_user(self.winner), Decimal('1900.00'))
        self.assertEqual(WalletTransaction.balance_for_user(self.other), Decimal('900.00'))

    def test_gift_keeps_description_and_never_pays_coins(self):
        tournament, created = self.create_tournament(prize_type='text', prize_text='Backgammon board')
        self.assertEqual(tournament.prize_money, Decimal('0.00'))
        self.assertEqual(created['prize_type'], 'text')
        self.assertEqual(created['prize_text'], 'Backgammon board')
        self.collect_entries(tournament)
        self.set_winner(tournament)
        tournament.award_prize_money()
        self.assertFalse(WalletTransaction.objects.filter(
            tournament=tournament, kind=WalletTransaction.KIND_TOURNAMENT_PRIZE,
        ).exists())
        self.assertEqual(WalletTransaction.balance_for_user(self.winner), Decimal('900.00'))
        self.assert_api_prize(tournament, '0.00', '0.00')

    def test_automatic_pool_keeps_zero_configuration_during_draft_edit(self):
        tournament, _ = self.create_tournament(prize_money=0)
        self.collect_entries(tournament)
        self.assert_api_prize(tournament, '180.00', '0.00')
        tournament.published = False
        tournament.save(update_fields=['published'])
        detail = self.client.get(reverse('api-admin-tournament-detail', args=[tournament.pk]))
        self.assertEqual(detail.status_code, 200, detail.content)
        response = self.client.put(
            reverse('api-admin-tournament-detail', args=[tournament.pk]),
            {**self.payload, 'name': 'Renamed automatic tournament',
             'prize_money': detail.json()['configured_prize_money']},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        tournament.refresh_from_db()
        self.assertEqual(tournament.prize_money, Decimal('0.00'))
        self.assertEqual(tournament.effective_prize_money, Decimal('180.00'))
        WalletTransaction.create_entry(
            user=self.other, amount='100.00',
            kind=WalletTransaction.KIND_TOURNAMENT_REFUND,
            tournament=tournament,
        )
        self.assertEqual(tournament.effective_prize_money, Decimal('90.00'))
