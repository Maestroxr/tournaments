from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from tournaments.models import Tournament, Participant, Participation


class BracketMetadataTests(TestCase):
    def test_six_player_bracket_exposes_existing_winner_links_without_changing_them(self):
        staff = User.objects.create_user(username='organizer', is_staff=True)
        self.client.force_login(staff)
        response = self.client.post(reverse('api-admin-tournaments'), {
            'name': 'Six players', 'template': 'knockout', 'min_players': 6,
            'max_players': 8, 'open_registration': True,
        }, content_type='application/json')
        self.assertEqual(response.status_code, 201, response.content)
        tournament = Tournament.objects.get(pk=response.json()['id'])
        for index in range(6):
            participant = Participant.objects.create(name=f'Player {index}')
            Participation.objects.create(tournament=tournament, participant=participant, slot_id=index)
        self.client.post(reverse('api-admin-tournament-close-registration', kwargs={'pk': tournament.pk}))
        self.client.post(reverse('api-admin-tournament-draw', kwargs={'pk': tournament.pk}), {}, content_type='application/json')
        self.client.post(reverse('api-admin-tournament-confirm-draw', kwargs={'pk': tournament.pk}))
        response = self.client.post(reverse('api-admin-tournament-start', kwargs={'pk': tournament.pk}))
        self.assertEqual(response.status_code, 200, response.content)
        stage = tournament.stages.first()
        before = list(stage.fixtures.order_by('id').values('id', 'player1_id', 'player2_id', 'extras'))
        response = self.client.get(reverse('api-admin-tournament-progress', kwargs={'pk': tournament.pk}))
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()['stages'][str(stage.id)]
        self.assertEqual(payload['bracket_kind'], 'single_elimination')
        fixtures = [f for level in payload['levels'] for f in level['fixtures']]
        self.assertEqual(len(fixtures), 5)
        by_position = {f['bracket']['position']: f for f in fixtures}
        self.assertIsNone(by_position[1]['bracket']['winner_to'])
        for position in range(2, 6):
            self.assertEqual(by_position[position]['bracket']['winner_to'], {
                'fixture_id': by_position[position // 2]['id'], 'player_slot': 1 + position % 2,
            })
        self.assertEqual(before, list(stage.fixtures.order_by('id').values('id', 'player1_id', 'player2_id', 'extras')))
