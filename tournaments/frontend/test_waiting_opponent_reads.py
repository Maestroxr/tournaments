"""Personal waiting context follows the bracket without offering another seat."""
import uuid
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from gamelink.models import GameLink
from tournaments.models import Fixture, Knockout, Participant, Participation, Tournament

from .progress_reads import serialize_waiting_opponent
from .tournament_reads import TournamentReadSnapshot


@override_settings(GAMELINK_ENABLED=True, GAMELINK_BACKGAMMON_URL='https://game.example.invalid')
class WaitingOpponentReadTests(TestCase):
    def setUp(self):
        self.tournament = Tournament.objects.create(
            name='Waiting for the other semifinal', published=True,
            starts_at=timezone.now() - timedelta(hours=1), podium_spec=['main.placements[0]'],
        )
        self.stage = Knockout.objects.create(tournament=self.tournament, identifier='main')
        for index in range(4):
            user = User.objects.create_user(username=f'waiting-player-{index}')
            participant = Participant.get_or_create_for_user(user)
            Participation.objects.create(tournament=self.tournament, participant=participant, slot_id=index)
        self.tournament.update_state()
        completed, self.source = list(self.stage.fixtures.filter(level=0).order_by('pk'))
        self.viewer = completed.player1.user
        completed.score1, completed.score2, completed.auto_confirmed = 5, 0, True
        completed.save(update_fields=['score1', 'score2', 'auto_confirmed'])
        self.tournament.update_state()
        self.destination = self.stage.fixtures.get(pk=completed.extras['propagate']['winner']['fixture_id'])
        self.client.force_login(self.viewer)
        self.url = f'/api/tournaments/{self.tournament.pk}/current-match'

    def link_source(self, **kwargs):
        defaults = {
            'status': 'playing', 'external_room_id': str(uuid.uuid4()),
            'expires_at': timezone.now() + timedelta(minutes=5),
            'live_snapshot': {'status': 'playing', 'state': {}},
        }
        defaults.update(kwargs)
        return GameLink.objects.create(fixture=self.source, **defaults)

    def read(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(any(query['sql'].lstrip().upper().startswith(
            ('INSERT', 'UPDATE', 'DELETE', 'REPLACE'),
        ) for query in queries))
        return response.json()

    def test_early_semifinal_winner_gets_exact_deciding_game_and_compact_payload(self):
        link = self.link_source(
            raw_result={'private_result': 'not part of waiting context'},
            live_snapshot={'status': 'playing', 'state': {'private_board': 'not exposed'}},
        )
        payload = self.read()
        self.assertEqual(self.stage.current_level, 0)
        self.assertEqual(payload['fixture']['id'], self.destination.pk)
        self.assertEqual(payload['fixture']['operational_status'], 'waiting_opponent')
        self.assertFalse(payload['fixture']['can_play'])
        self.assertTrue(payload['tournament']['waiting_for_opponent'])
        waiting = payload['waiting_for_opponent']
        self.assertEqual(waiting['fixture_id'], self.destination.pk)
        self.assertEqual(waiting['round_name'], payload['fixture']['round_name'])
        source = waiting['deciding_fixture']
        self.assertEqual(set(source), {
            'id', 'player1', 'player2', 'is_confirmed', 'can_watch',
            'external_room_id', 'operational_status',
        })
        self.assertEqual(source['id'], self.source.pk)
        self.assertEqual(source['external_room_id'], link.external_room_id)
        self.assertEqual(source['player1']['id'], self.source.player1_id)
        self.assertEqual(source['player2']['id'], self.source.player2_id)
        self.assertTrue(source['can_watch'])
        self.assertEqual(source['operational_status'], 'playing')

    def test_waiting_source_has_names_but_no_spectator_action(self):
        source = self.read()['waiting_for_opponent']['deciding_fixture']
        self.assertEqual(source['id'], self.source.pk)
        self.assertEqual(source['operational_status'], 'waiting')
        self.assertFalse(source['can_watch'])
        self.assertIsNone(source['external_room_id'])

    def test_stalled_or_terminal_room_cannot_be_watched(self):
        link = self.link_source(live_snapshot={
            'status': 'playing', 'state': {'presence': {'needsAdminAdjudication': True}},
        })
        source = self.read()['waiting_for_opponent']['deciding_fixture']
        self.assertEqual(source['operational_status'], 'stalled')
        self.assertFalse(source['can_watch'])
        link.live_snapshot = {'status': 'completed', 'state': {}}
        link.save(update_fields=['live_snapshot'])
        self.assertFalse(self.read()['waiting_for_opponent']['deciding_fixture']['can_watch'])

    def test_confirmed_or_bye_source_is_not_presented_as_a_deciding_game(self):
        for changes in (
            {'score1': 5, 'score2': 0, 'auto_confirmed': True, 'admin_result': ''},
            {'score1': None, 'score2': None, 'auto_confirmed': False, 'admin_result': 'double_no_show'},
        ):
            with self.subTest(changes=changes):
                Fixture.objects.filter(pk=self.source.pk).update(**changes)
                self.assertIsNone(self.read()['waiting_for_opponent']['deciding_fixture'])

    def test_missing_source_player_does_not_claim_a_deciding_game(self):
        Fixture.objects.filter(pk=self.source.pk).update(player2=None)
        self.assertIsNone(self.read()['waiting_for_opponent']['deciding_fixture'])

    def test_duplicate_feeders_fail_closed_instead_of_picking_a_match(self):
        Fixture.objects.create(
            mode=self.stage, level=0, player1=self.source.player1,
            player2=self.source.player2, extras=self.source.extras,
        )
        self.assertIsNone(self.read()['waiting_for_opponent']['deciding_fixture'])

    def test_wrong_destination_slot_does_not_offer_an_unrelated_match(self):
        extras = dict(self.source.extras)
        extras['propagate'] = {'winner': {
            'fixture_id': self.destination.pk,
            'player_slot': 1 if self.destination.player1_id else 2,
        }}
        Fixture.objects.filter(pk=self.source.pk).update(extras=extras)
        self.assertIsNone(self.read()['waiting_for_opponent']['deciding_fixture'])

    def test_double_elimination_keeps_generic_waiting_without_guessing(self):
        self.stage.double_elimination = True
        self.stage.save(update_fields=['double_elimination'])
        self.assertIsNone(self.read()['waiting_for_opponent']['deciding_fixture'])

    def test_paired_destination_removes_waiting_and_exposes_existing_play_action(self):
        self.source.score1, self.source.score2, self.source.auto_confirmed = 5, 0, True
        self.source.save(update_fields=['score1', 'score2', 'auto_confirmed'])
        self.tournament.update_state()
        payload = self.read()
        self.assertIsNone(payload['waiting_for_opponent'])
        self.assertFalse(payload['tournament']['waiting_for_opponent'])
        self.assertEqual(payload['fixture']['id'], self.destination.pk)
        self.assertTrue(payload['fixture']['can_play'])

    def test_outsider_and_source_players_do_not_inherit_another_players_waiting(self):
        outsider = User.objects.create_user(username='waiting-outsider')
        for user in (outsider, self.source.player1.user, self.source.player2.user):
            with self.subTest(user=user.pk):
                self.client.force_login(user)
                self.assertIsNone(self.read()['waiting_for_opponent'])
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_waiting_serializer_uses_only_the_loaded_snapshot(self):
        self.link_source()
        snapshot = TournamentReadSnapshot(self.tournament, self.viewer, include_live=True)
        fixture = snapshot.current_user_fixtures(self.viewer)[0]
        with self.assertNumQueries(0):
            waiting = serialize_waiting_opponent(fixture, snapshot, self.viewer, timezone.now())
        self.assertEqual(waiting['deciding_fixture']['id'], self.source.pk)
