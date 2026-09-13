from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import HeadToHeadTable, PlayerRating, RatingResult
from .ratings import record_result, serialize_rating


class RatingTests(TestCase):
    def setUp(self):
        self.first = User.objects.create_user('rated-first')
        self.second = User.objects.create_user('rated-second')

    def table(self):
        return HeadToHeadTable.objects.create(
            code=f'{HeadToHeadTable.objects.count():06d}', host=self.first,
            guest=self.second, mode='match', amount=10, fee_percent=0, fee_per_player=0,
        )

    def record(self, **overrides):
        args = dict(player1_id=self.first.pk, player2_id=self.second.pk,
                    winner_id=self.first.pk, table=self.table(), source='public', reason='move')
        args.update(overrides)
        return record_result(**args)

    def test_initial_rating_is_read_only(self):
        self.assertEqual(serialize_rating(self.first), {
            'value': 1000, 'games_played': 0, 'algorithm': 'elo-v1', 'history': [],
        })
        self.assertFalse(PlayerRating.objects.exists())

    def test_equal_players_and_retry(self):
        table = self.table()
        result = self.record(table=table)
        again = self.record(table=table)
        self.assertEqual(result.pk, again.pk)
        self.assertEqual(RatingResult.objects.count(), 1)
        self.assertEqual(serialize_rating(self.first)['value'], 1016)
        self.assertEqual(serialize_rating(self.second)['value'], 984)
        self.assertEqual(serialize_rating(self.first)['games_played'], 1)

    def test_repeated_opponents_are_distinct_results(self):
        self.record()
        second = self.record()
        self.assertEqual(second.player1_before, 1016)
        self.assertEqual(second.player1_after, 1031)
        self.assertEqual(second.player2_after, 969)
        self.assertEqual(serialize_rating(self.first)['games_played'], 2)

    def test_upset_awards_more_and_remains_zero_sum(self):
        PlayerRating.objects.create(user=self.first, value=1400)
        PlayerRating.objects.create(user=self.second, value=1000)
        result = self.record(winner_id=self.second.pk)
        self.assertEqual(result.player1_after, 1371)
        self.assertEqual(result.player2_after, 1029)
        self.assertEqual(result.player1_after + result.player2_after, 2400)

    def test_invalid_players_leave_no_history(self):
        with self.assertRaises(ValidationError):
            self.record(player2_id=self.first.pk)
        with self.assertRaises(ValidationError):
            self.record(winner_id=99999)
        self.assertFalse(RatingResult.objects.exists())
        self.assertFalse(PlayerRating.objects.exists())

    def test_history_is_recent_bounded_and_explains_both_sides(self):
        for _ in range(21):
            self.record()
        own, opponent = serialize_rating(self.first), serialize_rating(self.second)
        self.assertEqual(len(own['history']), 20)
        self.assertEqual(own['games_played'], 21)
        latest = own['history'][0]
        self.assertEqual(latest['id'], RatingResult.objects.latest('pk').pk)
        self.assertEqual(latest['opponent'], self.second.username)
        self.assertEqual(latest['result'], 'win')
        self.assertEqual(opponent['history'][0]['result'], 'loss')
        self.assertEqual(latest['delta'], -opponent['history'][0]['delta'])
