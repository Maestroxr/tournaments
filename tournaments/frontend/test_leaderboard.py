from django.contrib.auth.models import User
from django.test import TestCase

from tournaments.models import PlayerRating


class LeaderboardTests(TestCase):
    def setUp(self):
        self.players = []
        for index, value in enumerate((1500, 1400, 1300, 1200, 1100, 1100, 1000)):
            user = User.objects.create_user(username=f'leader-{index}')
            PlayerRating.objects.create(user=user, value=value, games_played=index + 1)
            self.players.append(user)
        self.unranked = User.objects.create_user(username='unranked')
        self.inactive = User.objects.create_user(username='inactive', is_active=False)
        PlayerRating.objects.create(user=self.inactive, value=9000, games_played=10)
        self.zero_games = User.objects.create_user(username='zero-games')
        PlayerRating.objects.create(user=self.zero_games, value=8000, games_played=0)
        self.client.force_login(self.players[-1])

    def test_ties_cross_pages_and_self_rank_is_available_outside_first_page(self):
        first = self.client.get('/api/leaderboard', {'limit': 5}).json()
        second = self.client.get('/api/leaderboard', {'limit': 5, 'offset': 5}).json()
        self.assertEqual(first['count'], 7)
        self.assertEqual(first['next_offset'], 5)
        self.assertIsNone(second['next_offset'])
        self.assertEqual([row['user_id'] for row in first['results']],
                         [user.pk for user in self.players[:5]])
        self.assertEqual([row['position'] for row in first['results']], [1, 2, 3, 4, 5])
        self.assertEqual([row['user_id'] for row in second['results']],
                         [user.pk for user in self.players[5:]])
        self.assertEqual([row['position'] for row in second['results']], [5, 7])
        self.assertEqual(first['me']['user_id'], self.players[-1].pk)
        self.assertEqual(first['me']['position'], 7)
        self.assertEqual(first['me']['rating'], 1000)
        for row in first['results'] + second['results']:
            self.assertEqual(set(row), {
                'user_id', 'username', 'rating', 'games_played', 'position',
            })

    def test_unranked_reader_does_not_create_a_rating(self):
        self.client.force_login(self.unranked)
        before = list(PlayerRating.objects.order_by('pk').values())
        payload = self.client.get('/api/leaderboard').json()
        self.assertIsNone(payload['me']['position'])
        self.assertIsNone(payload['me']['rating'])
        self.assertEqual(payload['me']['games_played'], 0)
        self.assertEqual(list(PlayerRating.objects.order_by('pk').values()), before)
        self.assertFalse(PlayerRating.objects.filter(user=self.unranked).exists())

    def test_negative_rating_is_still_ranked_after_a_rated_game(self):
        PlayerRating.objects.filter(user=self.players[-1]).update(value=-10)
        payload = self.client.get('/api/leaderboard', {'offset': 5}).json()
        self.assertEqual(payload['results'][-1]['rating'], -10)
        self.assertEqual(payload['me']['position'], 7)

    def test_authentication_method_and_page_limits(self):
        for query in ({'limit': 10}, {'offset': -1}, {'offset': 'bad'}):
            with self.subTest(query=query):
                self.assertEqual(self.client.get('/api/leaderboard', query).status_code, 400)
        self.assertEqual(self.client.post('/api/leaderboard').status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.get('/api/leaderboard').status_code, 401)
