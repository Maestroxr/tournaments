"""Signed result boundary -> real reservations, settlement and rating records.

Payloads follow game/link/outbox.py::build_result_body, but are synthetic:
board classification and withholding callbacks between series games belong to
the game-server suite. No board data is trusted by this receiver.
"""
import uuid
from decimal import Decimal

from django.db import transaction
from django.test import TestCase

from frontend import test_game_formats as format_tests
from gamelink import tests as callback_tests
from tournaments.models import DirectPlaySettings, PlayerRating, RatingResult, WalletTransaction


@callback_tests.gamelink_settings
class LossSettlementCallbackTests(TestCase):
    setUp = format_tests.GameFormatTests.setUp
    create = format_tests.GameFormatTests.create
    funded = format_tests.GameFormatTests.funded
    balance = format_tests.GameFormatTests.balance
    serialize = callback_tests.ResultCallbackTestBase.serialize
    deliver = callback_tests.ResultCallbackTestBase.deliver

    def body(self, table, reason, cube, win_type, winner='p1'):
        return {
            'v': 1, 'tournament_id': 0, 'fixture_id': -table.pk,
            'room_id': str(uuid.uuid4()), 'match_id': str(uuid.uuid4()),
            'status': 'completed', 'target_points': table.target_points,
            'seats': {'p1': 'white', 'p2': 'black'},
            'score': {'p1': table.target_points if winner == 'p1' else 0,
                      'p2': table.target_points if winner == 'p2' else 0},
            'winner_seat': winner, 'end_reason': reason,
            'finished_at': '2026-09-13T12:00:00Z', 'rating_policy': 'server-v1',
            'financial_result': {'format': table.game_format, 'cube': cube, 'win_type': win_type},
        }

    def assert_settlement(self, *, reason, cube, win_type, transfer,
                          game_format='money', mode='match', winner='p1'):
        before = {u.pk: self.balance(u) for u in (self.host, self.guest)}
        previous_ratings = RatingResult.objects.count()
        table = self.funded(game_format=game_format, mode=mode,
                            target_points=5 if game_format == 'match' else 1)
        body = self.body(table, reason, cube, win_type, winner)
        response = self.deliver(body)
        self.assertEqual(response.status_code, 200, response.content)
        fee = Decimal(transfer) * Decimal('.05')
        winning_user = self.host if winner == 'p1' else self.guest
        for user in (self.host, self.guest):
            delta = Decimal(transfer) - fee if user == winning_user else -Decimal(transfer)
            self.assertEqual(self.balance(user), before[user.pk] + delta)
        self.assertEqual(sum(self.balance(u) - before[u.pk] for u in (self.host, self.guest)), -fee)
        table.refresh_from_db()
        self.assertEqual(table.status, 'completed')
        self.assertEqual(table.winner_id, winning_user.pk)
        self.assertEqual(Decimal(table.settlement['transfer']), Decimal(transfer))
        self.assertEqual(Decimal(table.settlement['fee']), fee)
        expected_ratings = previous_ratings + (0 if mode == 'friend' else 1)
        self.assertEqual(RatingResult.objects.count(), expected_ratings)
        balances = [self.balance(u) for u in (self.host, self.guest)]
        entries = WalletTransaction.objects.count()
        ratings = list(PlayerRating.objects.order_by('pk').values('value', 'games_played'))
        # A transport retry is signed with a fresh nonce; it must acknowledge
        # the same result without paying or rating either participant again.
        response = self.deliver(body)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['status'], 'already_recorded')
        self.assertEqual(WalletTransaction.objects.count(), entries)
        self.assertEqual([self.balance(u) for u in (self.host, self.guest)], balances)
        self.assertEqual(RatingResult.objects.count(), expected_ratings)
        self.assertEqual(list(PlayerRating.objects.order_by('pk').values('value', 'games_played')), ratings)

    def test_money_player_loss_reasons_obey_same_multipliers_jacoby_and_cap(self):
        for reason in ('give_up', 'leave', 'time', 'disconnect'):
            for cube, win_type, transfer in (
                (1, 'backgammon', 100),
                (2, 'single', 200),
                (2, 'gammon', 400),
                (2, 'backgammon', 600),
                (8, 'backgammon', 2400),
                (32, 'backgammon', 6400),
            ):
                with self.subTest(
                    reason=reason,
                    cube=cube,
                    win_type=win_type,
                ):
                    with transaction.atomic():
                        self.assert_settlement(
                            reason=reason,
                            cube=cube,
                            win_type=win_type,
                            transfer=transfer,
                        )
                        transaction.set_rollback(True)

    def test_jacoby_disabled_contract_preserves_backgammon_multiplier(self):
        settings = DirectPlaySettings.load()
        settings.format_profiles['money']['jacoby'] = False
        settings.save()
        self.assert_settlement(reason='disconnect', cube=1, win_type='backgammon', transfer=300)

    def test_declined_double_uses_single_at_old_cube_value(self):
        self.assert_settlement(reason='double_response', cube=2, win_type='single', transfer=200)

    def test_guest_winner_gets_same_net_amount(self):
        self.assert_settlement(reason='disconnect', cube=2, win_type='backgammon', transfer=600, winner='p2')

    def test_public_and_friend_series_final_results_use_fixed_stake(self):
        # Includes give_up only when that game completed the series. A
        # below-target game resignation must not emit this final callback.
        for mode in ('match', 'friend'):
            for reason in ('give_up', 'leave', 'time', 'disconnect'):
                with self.subTest(mode=mode, reason=reason):
                    self.assert_settlement(reason=reason, cube=64, win_type='backgammon',
                                           transfer=100, game_format='match', mode=mode)

    def test_tampered_or_invalid_results_leave_reservations_and_rating_untouched(self):
        table = self.funded()
        body = self.body(table, 'disconnect', 2, 'gammon')
        balances = [self.balance(u) for u in (self.host, self.guest)]
        entries = WalletTransaction.objects.count()
        self.assertEqual(self.deliver(body, signature='invalid').status_code, 401)
        body['financial_result']['cube'] = 3
        self.assertEqual(self.deliver(body).status_code, 409)
        table.refresh_from_db()
        self.assertEqual(table.status, 'ready')
        self.assertEqual(WalletTransaction.objects.count(), entries)
        self.assertEqual([self.balance(u) for u in (self.host, self.guest)], balances)
        self.assertFalse(RatingResult.objects.exists())

    def test_nonfinal_playing_message_cannot_release_series_reservations(self):
        table = self.funded(game_format='match', target_points=5)
        body = self.body(table, 'give_up', 1, 'gammon')
        body.update(status='playing', score={'p1': 2, 'p2': 0})
        entries = WalletTransaction.objects.count()
        self.assertEqual(self.deliver(body).status_code, 400)
        self.assertEqual(WalletTransaction.objects.count(), entries)
        table.refresh_from_db()
        self.assertEqual(table.status, 'ready')
        self.assertEqual(self.balance(self.host), 9900)
        self.assertEqual(self.balance(self.guest), 9900)
        self.assertFalse(RatingResult.objects.exists())
