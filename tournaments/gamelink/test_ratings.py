"""Exercise ratings through settlement and signed callback boundaries."""
from unittest.mock import patch

from django.test import TestCase, RequestFactory

from frontend import test_game_formats as format_tests
from gamelink import tests as callback_tests
from gamelink.views import ResultCallbackView
from tournaments.models import PlayerRating, RatingResult, HeadToHeadTable, WalletTransaction


@callback_tests.gamelink_settings
class TournamentRatingTests(callback_tests.ResultCallbackTestBase):
    def rated_body(self, **changes):
        return self.result_body(rating_policy='server-v1', end_reason='move', **changes)

    def test_signed_result_updates_both_users_once_and_exposes_private_history(self):
        body = self.rated_body()
        self.assertEqual(self.deliver(body).status_code, 200)
        self.assertEqual(self.deliver(body).status_code, 200)
        self.assertEqual(RatingResult.objects.count(), 1)
        self.assertEqual(PlayerRating.objects.get(user=self.user1).value, 1016)
        self.assertEqual(PlayerRating.objects.get(user=self.user2).value, 984)
        self.client.force_login(self.user1)
        response = self.client.get('/api/auth/me')
        self.assertEqual(response.status_code, 200)
        rating = response.json()['rating']
        self.assertEqual(rating['games_played'], 1)
        self.assertEqual(rating['history'][0]['opponent'], self.user2.username)
        self.assertEqual(rating['history'][0]['source'], 'tournament')
        self.assertEqual(rating['history'][0]['delta'], 16)
        self.client.logout()
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)

    def test_invalid_signature_never_changes_rating_or_fixture(self):
        self.assertEqual(self.deliver(self.rated_body(), signature='invalid').status_code, 401)
        self.assertFalse(RatingResult.objects.exists())
        self.fixture.refresh_from_db()
        self.assertIsNone(self.fixture.score1)

    def test_old_results_settle_but_are_not_retroactively_rated(self):
        self.assertEqual(self.deliver(self.result_body()).status_code, 200)
        self.assertFalse(RatingResult.objects.exists())

    def test_preplay_forfeit_is_not_rated(self):
        body = self.rated_body()
        body.update(end_reason='forfeit', match_id=None)
        self.assertEqual(self.deliver(body).status_code, 200)
        self.assertFalse(RatingResult.objects.exists())

    def test_admin_result_is_not_rated(self):
        body = self.rated_body()
        body['end_reason'] = 'admin'
        self.assertEqual(self.deliver(body).status_code, 200)
        self.assertFalse(RatingResult.objects.exists())

    def test_guest_participant_result_is_not_rated(self):
        self.fixture.player2.user = None
        self.fixture.player2.save(update_fields=['user'])
        self.assertEqual(self.deliver(self.rated_body()).status_code, 200)
        self.assertFalse(RatingResult.objects.exists())

    def test_rating_failure_rolls_back_result(self):
        with patch('gamelink.ratings.record_result', side_effect=RuntimeError('storage failed')):
            with self.assertRaises(RuntimeError):
                self.deliver(self.rated_body())
        self.fixture.refresh_from_db()
        self.game_link.refresh_from_db()
        self.assertIsNone(self.fixture.score1)
        self.assertEqual(self.game_link.status, 'pending')
        self.assertFalse(PlayerRating.objects.exists())


class DirectPlayRatingTests(TestCase):
    # Reuse funded-table setup, without inheriting the unrelated format tests.
    setUp = format_tests.GameFormatTests.setUp
    create = format_tests.GameFormatTests.create
    funded = format_tests.GameFormatTests.funded

    def deliver(self, table, **changes):
        body = dict(status='completed', room_id='rating-room', winner_seat='p1',
                    match_id='rating-match', rating_policy='server-v1', end_reason='move',
                    financial_result=dict(format=table.game_format, cube=1, win_type='single'))
        body.update(changes)
        return ResultCallbackView()._record_direct_play(
            RequestFactory().post('/api/gamelink/result/'), table.pk, body)

    def test_money_quick_match_updates_once(self):
        table = self.funded()
        self.assertEqual(self.deliver(table).status_code, 200)
        self.assertEqual(self.deliver(table).status_code, 200)
        result = RatingResult.objects.get()
        self.assertEqual(result.source, 'quick')
        self.assertEqual(result.player1_after, 1016)
        self.assertEqual(PlayerRating.objects.get(user=self.host).games_played, 1)

    def test_public_match_and_rematch_use_updated_ratings(self):
        for _ in range(2):
            table = self.funded(game_format='match', target_points=5)
            self.assertEqual(self.deliver(table).status_code, 200)
        self.assertEqual(RatingResult.objects.count(), 2)
        self.assertEqual(PlayerRating.objects.get(user=self.host).value, 1031)
        self.assertEqual(PlayerRating.objects.get(user=self.guest).value, 969)
        self.assertEqual(set(RatingResult.objects.values_list('source', flat=True)), {'public'})

    def test_friend_match_remains_unrated(self):
        table = self.funded(game_format='match', mode='friend')
        self.assertEqual(self.deliver(table).status_code, 200)
        self.assertFalse(RatingResult.objects.exists())

    def test_cancellation_remains_unrated(self):
        table = self.funded()
        self.assertEqual(self.deliver(table, status='cancelled', winner_seat=None).status_code, 200)
        self.assertFalse(RatingResult.objects.exists())

    def test_untrusted_and_administrative_endings_are_unrated(self):
        for changes in ({'rating_policy': None}, {'end_reason': 'admin'},
                        {'end_reason': 'state_update'}, {'end_reason': 'forfeit'},
                        {'match_id': None}, {'end_reason': 'unknown'}):
            with self.subTest(changes=changes):
                table = self.funded(game_format='match')
                self.assertEqual(self.deliver(table, **changes).status_code, 200)
                self.assertFalse(RatingResult.objects.exists())

    def test_player_loss_endings_count(self):
        for reason in ('give_up', 'leave', 'time', 'disconnect', 'double_response'):
            with self.subTest(reason=reason):
                table = self.funded(game_format='match')
                self.assertEqual(self.deliver(table, end_reason=reason, winner_seat='p2').status_code, 200)
        self.assertEqual(PlayerRating.objects.get(user=self.guest).games_played, 5)
        self.assertTrue(all(row.winner_id == self.guest.pk for row in RatingResult.objects.all()))

    def test_invalid_financial_result_does_not_rate(self):
        table = self.funded()
        self.assertEqual(self.deliver(table, financial_result={'format': 'money', 'cube': 3, 'win_type': 'single'}).status_code, 409)
        self.assertFalse(RatingResult.objects.exists())
        table.refresh_from_db()
        self.assertEqual(table.status, 'ready')

    def test_legacy_public_result_also_rates_with_server_policy(self):
        table = HeadToHeadTable.objects.create(
            host=self.host, guest=self.guest, mode='match', status='ready',
            amount=100, fee_percent=5, fee_per_player=5)
        for user in (self.host, self.guest):
            WalletTransaction.create_entry(user=user, amount=-100,
                kind=WalletTransaction.KIND_HEAD_TO_HEAD_ENTRY, head_to_head_table=table)
        self.assertEqual(self.deliver(table).status_code, 200)
        self.assertEqual(RatingResult.objects.get().source, 'public')

    def test_rating_failure_rolls_back_financial_settlement(self):
        table = self.funded()
        balance = WalletTransaction.balance_for_user(self.host)
        with patch('gamelink.ratings.record_result', side_effect=RuntimeError('storage failed')):
            with self.assertRaises(RuntimeError):
                self.deliver(table)
        table.refresh_from_db()
        self.assertEqual(table.status, 'ready')
        self.assertEqual(WalletTransaction.balance_for_user(self.host), balance)
