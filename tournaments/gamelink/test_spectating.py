import time
import uuid
from unittest.mock import PropertyMock, patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.models import User
from django.core import signing
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from tournaments.models import Fixture, Knockout, Participant, Tournament
from .models import GameLink, IssuedTicket, LinkedAccount
from .spectating import SPECTATOR_SALT


@override_settings(
    GAMELINK_ENABLED=True, GAMELINK_BACKGAMMON_URL='https://game.example/backgammon',
    GAMELINK_GAME_FRONTEND_URL='', GAMELINK_TICKET_SECRET='spectator-test-secret-0123456789',
    GAMELINK_ISSUER='tournaments', GAMELINK_AUDIENCE='backgammon',
)
class TournamentSpectatorAdmissionTests(TestCase):
    def setUp(self):
        self.viewer = User.objects.create_user('spectator')
        self.players = [User.objects.create_user(name) for name in ('white-player', 'black-player')]
        self.tournament = Tournament.objects.create(
            name='Watch tournament', definition='', podium_spec=[],
            starts_at=timezone.now(), published=True,
        )
        self.fixture = Fixture.objects.create(
            mode=Knockout.objects.create(tournament=self.tournament), level=0,
            player1=Participant.objects.create(user=self.players[0], name='White'),
            player2=Participant.objects.create(user=self.players[1], name='Black'),
        )
        self.room_id = str(uuid.uuid4())
        self.link = GameLink.objects.create(
            fixture=self.fixture, status='playing', external_room_id=self.room_id,
            expires_at=timezone.now(), live_snapshot={'status': 'playing', 'state': {}},
        )
        self.url = f'/api/gamelink/fixture/{self.fixture.pk}/watch/'
        self.client.force_login(self.viewer)

    def test_ticket_is_short_lived_read_only_and_binds_the_existing_room(self):
        with patch.object(Tournament, 'state', new_callable=PropertyMock, return_value='active'):
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        destination = urlsplit(response.json()['url'])
        self.assertEqual(destination.scheme, 'https')
        self.assertEqual(destination.netloc, 'game.example')
        self.assertEqual(destination.path, f'/6b/backgammon/watch/{self.room_id}/')
        self.assertEqual(parse_qs(destination.query), {'tournament': [str(self.tournament.pk)]})
        token = parse_qs(destination.fragment)['ticket'][0]
        payload = signing.loads(token, key='spectator-test-secret-0123456789', salt=SPECTATOR_SALT)
        self.assertEqual(payload['role'], 'spectator')
        self.assertEqual(payload['sub'], str(LinkedAccount.objects.get(user=self.viewer).external_id))
        self.assertEqual((payload['trn'], payload['fix'], payload['room']),
                         (self.tournament.pk, self.fixture.pk, self.room_id))
        self.assertEqual((payload['iss'], payload['aud']), ('tournaments', 'backgammon'))
        self.assertEqual(payload['exp'] - payload['iat'], 120)
        self.assertLessEqual(payload['iat'], int(time.time()))
        self.assertNotIn('seat', payload)
        self.assertEqual(GameLink.objects.count(), 1)
        self.assertFalse(IssuedTicket.objects.exists())
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        with self.assertRaises(signing.BadSignature):
            signing.loads(token, key='spectator-test-secret-0123456789', salt='gamelink.ticket.v1')

    def test_authentication_post_and_csrf_are_required(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(self.url).status_code, 401)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.viewer)
        self.assertEqual(csrf_client.post(self.url).status_code, 403)
        self.assertFalse(LinkedAccount.objects.filter(user=self.viewer).exists())

    def test_only_published_active_tournaments_can_be_watched(self):
        for state in ('draft', 'open', 'finished'):
            with self.subTest(state=state), patch.object(
                    Tournament, 'state', new_callable=PropertyMock, return_value=state):
                self.assertEqual(self.client.post(self.url).status_code, 404)
        self.tournament.published = False
        self.tournament.save(update_fields=['published'])
        with patch.object(Tournament, 'state', new_callable=PropertyMock, return_value='active'):
            self.assertEqual(self.client.post(self.url).status_code, 404)
        self.assertFalse(LinkedAccount.objects.filter(user=self.viewer).exists())

    def test_participants_cannot_use_their_own_spectator_admission(self):
        for player in self.players:
            self.client.force_login(player)
            with patch.object(Tournament, 'state', new_callable=PropertyMock, return_value='active'):
                self.assertEqual(self.client.post(self.url).status_code, 404)

    def test_non_running_invalid_or_adjudicated_rooms_are_unavailable(self):
        cases = [
            {'status': 'completed'}, {'status': 'cancelled'}, {'status': 'failed'},
            {'external_room_id': ''}, {'external_room_id': 'not-a-uuid'},
            {'live_snapshot': {'status': 'completed'}},
            {'live_snapshot': {'status': 'playing', 'state': {
                'presence': {'needsAdminAdjudication': True}}}},
        ]
        for change in cases:
            with self.subTest(change=change):
                GameLink.objects.filter(pk=self.link.pk).update(
                    status='playing', external_room_id=self.room_id,
                    live_snapshot={'status': 'playing', 'state': {}})
                GameLink.objects.filter(pk=self.link.pk).update(**change)
                with patch.object(Tournament, 'state', new_callable=PropertyMock, return_value='active'):
                    self.assertEqual(self.client.post(self.url).status_code, 404)

    def test_score_review_is_not_exposed_as_a_running_game(self):
        Fixture.objects.filter(pk=self.fixture.pk).update(score1=1, score2=0)
        with patch.object(Tournament, 'state', new_callable=PropertyMock, return_value='active'):
            self.assertEqual(self.client.post(self.url).status_code, 404)

    @override_settings(GAMELINK_GAME_FRONTEND_URL='http://backgammon.localhost:5173/6b/backgammon/')
    def test_separate_local_frontend_origin_is_supported(self):
        with patch.object(Tournament, 'state', new_callable=PropertyMock, return_value='active'):
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['url'].startswith(
            f'http://backgammon.localhost:5173/6b/backgammon/watch/{self.room_id}/'))
