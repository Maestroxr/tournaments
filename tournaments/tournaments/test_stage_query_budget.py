"""Run on a disposable database; preserve confirmation rules while bounding queries."""
from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tournaments.models import Fixture, Mode, Participant, Participation, Tournament


class StageQueryBudgetTests(TestCase):
    def setUp(self):
        self.tournament = Tournament.objects.create(
            name='Query budget', starts_at=timezone.now(), podium_spec=[], published=True,
        )
        self.stage = Mode.objects.create(tournament=self.tournament, identifier='main')
        self.users = [User.objects.create(username=f'query-player-{i}') for i in range(4)]
        self.players = []
        for i, user in enumerate(self.users):
            player = Participant.objects.create(user=user, name=user.username)
            self.players.append(player)
            Participation.objects.create(tournament=self.tournament, participant=player, slot_id=i)

    def expected_level(self):
        for level in range(self.stage.levels):
            if not all(f.is_confirmed for f in self.stage.fixtures.filter(level=level)):
                return level
        return self.stage.levels

    def test_empty_and_sparse_rounds(self):
        self.assertEqual(self.stage.current_level, 0)
        self.assertFalse(self.stage.is_finished)
        fixture = Fixture.objects.create(mode=self.stage, level=3)
        self.assertEqual(self.stage.current_level, 3)
        fixture.admin_result = 'double_no_show'
        fixture.save()
        self.assertEqual(self.stage.current_level, 4)
        self.assertTrue(self.stage.is_finished)

    def test_confirmation_rules_and_freshness(self):
        fixture = Fixture.objects.create(mode=self.stage, level=0)
        cases = [
            ('', None, None, None, False),
            ('advance', self.players[0].pk, None, None, False),
            ('advance', None, None, None, False),
            ('disqualify', self.players[0].pk, None, None, False),
            ('no_show_bye', self.players[0].pk, None, None, False),
            ('double_no_show', None, None, None, False),
            ('score', None, 5, 2, False),
            ('finish', None, 5, 2, False),
            ('', None, 5, 2, True),
            ('', None, 5, 2, False),
        ]
        for result, winner, score1, score2, auto in cases:
            Fixture.objects.filter(pk=fixture.pk).update(
                admin_result=result, admin_winner_id=winner,
                score1=score1, score2=score2, auto_confirmed=auto,
            )
            with self.subTest(result=result, winner=winner, auto=auto):
                self.assertEqual(self.stage.current_level, self.expected_level())
        fixture.confirmations.add(*self.users[:2])
        self.assertEqual(self.stage.current_level, 0)
        fixture.confirmations.add(self.users[2])
        self.assertEqual(self.stage.current_level, 1)
        fixture.confirmations.clear()
        self.assertEqual(self.stage.current_level, 0)

    def test_query_count_does_not_grow_with_fixture_count(self):
        Fixture.objects.bulk_create([
            Fixture(mode=self.stage, level=i, score1=5, score2=2)
            for i in range(32)
        ])
        for fixture in self.stage.fixtures.all():
            fixture.confirmations.add(*self.users[:3])
        expected = self.expected_level()
        with CaptureQueriesContext(connection) as queries:
            actual = self.stage.current_level
        self.assertEqual(actual, expected)
        self.assertEqual(actual, 32)
        self.assertLessEqual(len(queries), 2)
