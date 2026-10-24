import io
import json
import uuid
from unittest.mock import patch, PropertyMock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from tournaments.models import Fixture, Knockout, Tournament
from .models import GameLink
from .replay import REPLAY_MAX_BYTES
from .signing import sign_command_body
from .views import _validate_result


@override_settings(GAMELINK_ENABLED=True, GAMELINK_COMMAND_SECRET='isolated-replay-command-secret-0123456789',
                   GAMELINK_BACKGAMMON_URL='https://game.example', GAMELINK_ISSUER='tournaments')
class FixtureReplayBridgeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ReplayReader')
        tournament = Tournament.objects.create(name='Replay', definition='', podium_spec=[],
                                               starts_at=timezone.now(), published=True)
        self.fixture = Fixture.objects.create(mode=Knockout.objects.create(tournament=tournament), level=0)
        self.match_id, self.room_id = str(uuid.uuid4()), str(uuid.uuid4())
        self.link = GameLink.objects.create(fixture=self.fixture, external_room_id=self.room_id,
                                            expires_at=timezone.now(), status='completed', raw_result={
            'room_id': self.room_id, 'match_id': self.match_id,
            'replay': {'v': 1, 'match_id': self.match_id, 'game_count': 1, 'sha256': 'digest'}})
        self.url = f'/api/gamelink/fixture/{self.fixture.pk}/replay/'
        self.page = {'match_id': self.match_id, 'game_count': 1, 'game_index': 0, 'turn_offset': 0,
                     'turn_count': 1, 'next_offset': None,
                     'game': {'winner': 'white', 'transcript': [{'turn': 'white', 'roll': [6, 4]}]}}

    def get(self, payload=None, *, state='active', query=''):
        with patch.object(Tournament, 'state', new_callable=PropertyMock, return_value=state), patch(
                'gamelink.replay.urlopen', return_value=io.BytesIO(json.dumps(
                    self.page if payload is None else payload).encode())) as upstream:
            response = self.client.get(self.url + query)
        return response, upstream

    def test_authentication_and_existing_progress_visibility_gate_the_peer_read(self):
        response, upstream = self.get()
        self.assertEqual(response.status_code, 401)
        upstream.assert_not_called()
        self.client.force_login(self.user)
        for state in ('draft', 'open'):
            response, upstream = self.get(state=state)
            self.assertEqual(response.status_code, 404)
            upstream.assert_not_called()
        for state in ('active', 'finished'):
            self.assertEqual(self.get(state=state)[0].status_code, 200)

    def test_signed_peer_request_binds_fixture_room_match_issuer_and_position(self):
        self.client.force_login(self.user)
        response, upstream = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        request = upstream.call_args.args[0]
        self.assertEqual(request.full_url, 'https://game.example/api/link/replay/')
        self.assertEqual(json.loads(request.data), {'v': 1, 'action': 'read_replay', 'issuer': 'tournaments',
            'fixture_id': self.fixture.pk, 'room_id': self.room_id, 'match_id': self.match_id,
            'game_index': 0, 'turn_offset': 0, 'limit': 50})
        timestamp = request.get_header('X-gamelink-timestamp')
        self.assertEqual(request.get_header('X-gamelink-signature'), sign_command_body(request.data, timestamp))

    def test_invalid_or_mismatched_upstream_data_is_a_controlled_failure(self):
        self.client.force_login(self.user)
        for payload in ([], 'invalid', 1, {**self.page, 'match_id': str(uuid.uuid4())},
                        {**self.page, 'game': []}, {**self.page, 'turn_count': '1'},
                        {**self.page, 'turn_offset': 1}, {**self.page, 'extra': 'x' * REPLAY_MAX_BYTES}):
            with self.subTest(payload_type=type(payload).__name__):
                self.assertEqual(self.get(payload)[0].status_code, 503)
        with patch.object(Tournament, 'state', new_callable=PropertyMock, return_value='active'), patch(
                'gamelink.replay.urlopen', return_value=io.BytesIO(b'invalid json')):
            self.assertEqual(self.client.get(self.url).status_code, 503)

    def test_invalid_positions_and_stored_bindings_never_call_the_peer(self):
        self.client.force_login(self.user)
        response, upstream = self.get(query='?turn_offset=-1')
        self.assertEqual(response.status_code, 400)
        upstream.assert_not_called()
        self.link.raw_result['replay']['match_id'] = str(uuid.uuid4())
        self.link.save(update_fields=['raw_result'])
        response, upstream = self.get()
        self.assertEqual(response.status_code, 400)
        upstream.assert_not_called()

    def test_dynamic_money_scores_keep_the_tournament_integer_limit_separate(self):
        body = {'v': 1, 'room_id': self.room_id, 'tournament_id': 0, 'fixture_id': -1,
                'status': 'completed', 'score': {'p1': 3 * (1 << 20), 'p2': 0},
                'financial_result': {'format': 'money', 'cube': 1 << 20, 'win_type': 'backgammon'}}
        self.assertIsNone(_validate_result(body))
        self.assertIsNotNone(_validate_result({**body, 'tournament_id': 1, 'fixture_id': 1}))
        self.assertIsNotNone(_validate_result({**body, 'score': {'p1': 3 * (1 << 20) + 1, 'p2': 0}}))
        self.assertIsNotNone(_validate_result({**body, 'financial_result': {'format': 'match'}}))
