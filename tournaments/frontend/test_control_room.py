from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from gamelink.models import GameLink
from tournaments.models import Participant, Participation, Tournament


DEFINITION = """
stages:
  - id: main
    name: Main bracket
    mode: knockout
podium:
  - main.placements[0]
  - main.placements[1]
"""


class TournamentControlRoomTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='control-room-organizer', is_staff=True)
        self.tournament = Tournament.load(
            DEFINITION,
            'Control room cup',
            creator=self.staff,
            published=True,
            min_players=8,
            max_players=8,
        )
        for index in range(8):
            user = User.objects.create_user(username=f'control-player-{index}')
            participant = Participant.get_or_create_for_user(user)
            Participation.objects.create(
                tournament=self.tournament,
                participant=participant,
                slot_id=index,
            )
        self.client.force_login(self.staff)
        self.post('api-admin-tournament-close-registration')
        self.post('api-admin-tournament-draw')
        self.post('api-admin-tournament-confirm-draw')
        started = self.post('api-admin-tournament-start')
        self.assertEqual(started.status_code, 200, started.content)

    def post(self, name):
        return self.client.post(
            reverse(name, kwargs={'pk': self.tournament.pk}),
            '{}',
            content_type='application/json',
        )

    def test_progress_exposes_operational_groups_round_progress_and_timing(self):
        fixtures = list(self.tournament.current_stage.fixtures.filter(
            level=self.tournament.current_stage.current_level,
        ).order_by('id'))
        fixtures[0].score = (5, 2)
        fixtures[0].save()
        stale_time = timezone.now() - timedelta(minutes=5)
        game_link = GameLink.objects.create(
            fixture=fixtures[1],
            status='playing',
            expires_at=timezone.now() + timedelta(hours=1),
            live_snapshot={
                'status': 'playing',
                'state': {'phase': 'moving', 'turn': 'white', 'dice': [4, 2], 'cube': 1},
                'match_score': {'white': 1, 'black': 0},
            },
            live_updated_at=stale_time,
        )
        GameLink.objects.filter(pk=game_link.pk).update(live_updated_at=stale_time)

        response = self.client.get(reverse(
            'api-admin-tournament-progress', kwargs={'pk': self.tournament.pk},
        ))

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        control_room = payload['control_room']
        self.assertEqual(control_room['current_stage'], 'Main bracket')
        self.assertEqual(control_room['round_total'], 4)
        self.assertEqual(control_room['round_completed'], 0)
        self.assertEqual(control_room['counts']['review'], 1)
        self.assertEqual(control_room['counts']['stalled'], 1)
        self.assertEqual(control_room['counts']['waiting'], 2)
        self.assertEqual(control_room['stale_after_seconds'], 120)

        serialized = [
            fixture
            for stage in payload['stages'].values()
            for level in stage['levels']
            for fixture in level['fixtures']
        ]
        stale_fixture = next(item for item in serialized if item['id'] == fixtures[1].id)
        self.assertEqual(stale_fixture['operational_status'], 'stalled')
        self.assertTrue(stale_fixture['stalled'])
        self.assertIsNotNone(stale_fixture['started_at'])
        self.assertIsNotNone(stale_fixture['last_activity_at'])
        self.assertGreaterEqual(stale_fixture['duration_seconds'], 0)
        self.assertIn('ready_at', stale_fixture)
