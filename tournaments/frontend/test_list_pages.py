"""Paging stays bounded, scoped to the viewer, and independent of lobby history."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from tournaments.models import HeadToHeadTable


class GameListPageTests(TestCase):
    def setUp(self):
        self.viewer = User.objects.create_user(username='viewer')
        self.other = User.objects.create_user(username='other')
        self.client.force_login(self.viewer)

    def table(self, host=None, **fields):
        return HeadToHeadTable.objects.create(
            code=f'P{HeadToHeadTable.objects.count():05d}',
            host=host or self.viewer, mode='match', amount=100,
            fee_percent=5, fee_per_player=5, **{'game_format': 'match', **fields},
        )

    def test_lobby_only_sends_first_live_pages_and_history_is_explicit(self):
        public = [self.table(host=self.other) for _ in range(7)]
        own = [self.table() for _ in range(7)]
        history = [self.table(status='completed') for _ in range(7)]
        foreign = self.table(host=self.other, status='completed')
        # Force ties to exercise stable ID ordering on both pages.
        HeadToHeadTable.objects.all().update(created_at=timezone.now(), updated_at=timezone.now())
        lobby = self.client.get('/api/head-to-head/tables').json()
        self.assertEqual([row['id'] for row in lobby['tables']], [row.pk for row in public[::-1][:5]])
        self.assertEqual([row['id'] for row in lobby['my_tables']], [row.pk for row in own[::-1][:5]])
        self.assertEqual(lobby['my_history'], [])
        self.assertEqual(lobby['updates'], [])
        self.assertEqual(lobby['pages']['public'], {'count': 7, 'next_offset': 5})
        self.assertEqual(lobby['pages']['ongoing'], {'count': 7, 'next_offset': 5})
        first = self.client.get('/api/head-to-head/tables', {'scope': 'history', 'limit': 5}).json()
        second = self.client.get('/api/head-to-head/tables', {'scope': 'history', 'limit': 5, 'offset': 5}).json()
        ids = [row['id'] for row in first['results'] + second['results']]
        self.assertEqual(ids, [row.pk for row in history[::-1]])
        self.assertNotIn(foreign.pk, ids)
        self.assertEqual(first['count'], 7)
        self.assertEqual(first['next_offset'], 5)
        self.assertIsNone(second['next_offset'])

    def test_priority_and_format_filters_apply_before_slicing(self):
        playing = self.table(status='playing')
        ready = self.table(host=self.other, guest=self.viewer, status='ready')
        for _ in range(7):
            self.table()
        self.table(status='cancelled')
        ongoing = self.client.get('/api/head-to-head/tables', {'scope': 'ongoing'}).json()
        self.assertEqual([row['id'] for row in ongoing['results'][:2]], [playing.pk, ready.pk])
        self.assertEqual(len(ongoing['results']), 5)
        self.assertEqual(ongoing['count'], 9)
        money = [self.table(host=self.other, game_format='money') for _ in range(7)]
        for _ in range(7):
            self.table(host=self.other)
        filtered = self.client.get('/api/head-to-head/tables', {'scope': 'public', 'format': 'money'}).json()
        self.assertEqual([row['id'] for row in filtered['results']], [row.pk for row in money[::-1][:5]])
        self.assertEqual(filtered['count'], 7)
        self.assertEqual(filtered['next_offset'], 5)

    def test_tracking_retains_known_entry_targets_without_fetching_all_history(self):
        old_open = self.table()
        for _ in range(6):
            self.table(status='playing')
        closed = self.table(status='cancelled')
        untracked = self.table(status='completed')
        foreign = self.table(host=self.other, status='completed')
        visible = self.client.get('/api/head-to-head/tables').json()['my_tables'][0]['id']
        lobby = self.client.get('/api/head-to-head/tables', {
            'watch': f'{old_open.pk},{closed.pk},{foreign.pk},{visible}',
        }).json()
        self.assertEqual({row['id'] for row in lobby['updates']}, {old_open.pk, closed.pk})
        self.assertNotIn(untracked.pk, {row['id'] for row in lobby['updates']})
        self.assertEqual(lobby['my_history'], [])
        self.assertEqual(len(lobby['my_tables']), 5)
        self.assertTrue(lobby['has_own_search'])

    def test_invalid_pages_and_scopes_fail_instead_of_returning_unbounded_lists(self):
        for query in (
            {'limit': 100}, {'scope': 'history', 'offset': -1},
            {'scope': 'everyone'}, {'scope': 'public', 'format': 'unknown'},
            {'offset': 5}, {'watch': 'nope'}, {'watch': '-1'},
            {'watch': ','.join(str(number) for number in range(1, 102))},
        ):
            with self.subTest(query=query):
                self.assertEqual(self.client.get('/api/head-to-head/tables', query).status_code, 400)
        self.client.logout()
        self.assertEqual(self.client.get('/api/head-to-head/tables', {'scope': 'history'}).status_code, 401)
