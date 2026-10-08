"""List summaries preserve card semantics without loading full bracket history."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, User
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from frontend.api import _serialize_tournament
from frontend.tournament_list_reads import _confirmed_filter, _fixture_reads, tournament_list_snapshots
from frontend.tournament_reads import TournamentReadSnapshot
from tournaments.models import (
    Fixture,
    FixtureAudit,
    Mode,
    Participant,
    Participation,
    Tournament,
    TournamentRegistration,
    WalletTransaction,
)


@override_settings(GAMELINK_ENABLED=True, GAMELINK_BACKGAMMON_URL='https://game.example.invalid')
class TournamentListReadTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.player = User.objects.create(username='list-player')
        self.opponent = User.objects.create(username='list-opponent')
        self.staff = User.objects.create(username='list-staff', is_staff=True)
        self.people = [Participant.objects.create(user=user, name=user.username)
                       for user in (self.player, self.opponent)]

    def make_tournament(self, *, active=True, published=True):
        tournament = Tournament.objects.create(
            name=f'List read {Tournament.objects.count()}', creator=self.staff, published=published,
            podium_spec=[], starts_at=self.now - timedelta(hours=1), entry_fee=Decimal('10.00'),
        )
        stage = Mode.objects.create(tournament=tournament, identifier='main')
        for slot, participant in enumerate(self.people):
            Participation.objects.create(tournament=tournament, participant=participant, slot_id=slot)
            TournamentRegistration.objects.create(tournament=tournament, participant=participant)
        fixture = None
        if active:
            fixture = Fixture.objects.create(
                mode=stage, level=0, player1=self.people[0], player2=self.people[1],
                playable_at=self.now - timedelta(seconds=30),
            )
        return tournament, stage, fixture

    def assert_payload_matches_detail(self, tournament, user):
        request = RequestFactory().get('/api/tournaments')
        request.user = user
        # Freeze countdowns so both read strategies describe the same instant.
        with patch('frontend.api.timezone.now', return_value=self.now):
            expected = _serialize_tournament(
                tournament, request, read_snapshot=TournamentReadSnapshot(tournament, user),
            )
            snapshots = tournament_list_snapshots([tournament], user)
            with CaptureQueriesContext(connection) as captured:
                actual = _serialize_tournament(tournament, request, read_snapshot=snapshots[0])
        self.assertEqual(actual, expected)
        self.assertEqual(len(captured), 0, 'Serialization must not issue per-tournament reads')
        return snapshots[0], actual

    def test_personal_staff_and_anonymous_cards_match_detail(self):
        tournament, _, _ = self.make_tournament()
        for user in (self.player, self.opponent, self.staff, AnonymousUser()):
            with self.subTest(user=user.pk):
                self.assert_payload_matches_detail(tournament, user)

    def test_open_finished_and_empty_next_stage_match_detail(self):
        tournament, _, fixture = self.make_tournament()
        self.assert_payload_matches_detail(tournament, self.player)
        fixture.admin_result = 'double_no_show'
        fixture.save(update_fields=['admin_result'])
        _, payload = self.assert_payload_matches_detail(tournament, self.player)
        self.assertEqual(payload['state'], 'finished')
        self.assertTrue(payload['is_eliminated'])
        Mode.objects.create(tournament=tournament, identifier='next')
        _, payload = self.assert_payload_matches_detail(tournament, self.player)
        self.assertEqual(payload['state'], 'active')
        self.assertEqual(payload['current_round'], 0)
        opened, _, _ = self.make_tournament(active=False)
        self.assert_payload_matches_detail(opened, self.player)

    def test_early_personal_round_matches_detail(self):
        tournament, stage, fixture = self.make_tournament()
        fixture.level = 1
        fixture.save(update_fields=['level'])
        Fixture.objects.create(mode=stage, level=0)
        _, payload = self.assert_payload_matches_detail(tournament, self.player)
        self.assertTrue(payload['can_play'])
        self.assertEqual(payload['current_round'], 1)

    def test_opponents_missing_player_and_ambiguous_pairings_block_entry(self):
        for ambiguous in (False, True):
            with self.subTest(ambiguous=ambiguous):
                tournament, stage, fixture = self.make_tournament()
                if not ambiguous:
                    fixture.level = 1
                    fixture.save(update_fields=['level'])
                Fixture.objects.create(mode=stage, level=0, player1=self.people[1])
                _, payload = self.assert_payload_matches_detail(tournament, self.player)
                self.assertFalse(payload['can_play'])

    def test_missing_players_and_offline_opponents_match_detail(self):
        tournament, _, fixture = self.make_tournament()
        fixture.player2 = None
        fixture.save(update_fields=['player2'])
        self.assert_payload_matches_detail(tournament, self.player)
        fixture.player2 = self.people[1]
        fixture.save(update_fields=['player2'])
        self.people[1].user = None
        self.people[1].save(update_fields=['user'])
        _, payload = self.assert_payload_matches_detail(tournament, self.player)
        self.assertFalse(payload['can_play'])

    def test_confirmed_losses_podium_and_fees_match_detail(self):
        tournament, _, fixture = self.make_tournament()
        fixture.score1, fixture.score2 = 0, 5
        fixture.auto_confirmed = True
        fixture.save(update_fields=['score1', 'score2', 'auto_confirmed'])
        for slot, participant in enumerate(self.people):
            Participation.objects.filter(tournament=tournament, participant=participant).update(
                podium_position=2 - slot,
            )
        for kind, amount in ((WalletTransaction.KIND_TOURNAMENT_ENTRY, '-20.00'),
                             (WalletTransaction.KIND_TOURNAMENT_REFUND, '10.00'),
                             (WalletTransaction.KIND_TOURNAMENT_PRIZE, '9.00')):
            WalletTransaction.objects.create(
                user=self.player, tournament=tournament, kind=kind, amount=amount, balance_after=0,
            )
        for user in (self.player, self.opponent, self.staff, AnonymousUser()):
            self.assert_payload_matches_detail(tournament, user)
        _, payload = self.assert_payload_matches_detail(tournament, self.player)
        self.assertTrue(payload['is_eliminated'])
        self.assertEqual(Decimal(payload['collected_entry_fees']), Decimal('10.00'))
        self.assertEqual(payload['prize_money'], '9.00')
        tournament.prize_money = Decimal('80.00')
        tournament.save(update_fields=['prize_money'])
        self.assert_payload_matches_detail(tournament, self.player)
        WalletTransaction.objects.create(
            user=self.player, tournament=tournament, kind=WalletTransaction.KIND_TOURNAMENT_REFUND,
            amount='10.00', balance_after=0,
        )
        self.assert_payload_matches_detail(tournament, self.player)

    def test_staff_registration_summary_matches_detail(self):
        tournament, _, _ = self.make_tournament(active=False)
        registration = tournament.registrations.get(participant=self.people[0])
        registration.payment_status = TournamentRegistration.PAYMENT_UNPAID
        registration.save(update_fields=['payment_status'])
        tournament.registrations.filter(participant=self.people[1]).update(checked_in_at=self.now)
        waiting = Participant.objects.create(name='list-waitlisted')
        TournamentRegistration.objects.create(
            tournament=tournament, participant=waiting, status=TournamentRegistration.STATUS_WAITLISTED,
        )
        snapshot, payload = self.assert_payload_matches_detail(tournament, self.staff)
        self.assertEqual(snapshot.participant_count, 2)
        self.assertEqual(payload['registration_summary']['waitlisted'], 1)
        self.assertEqual(payload['registration_summary']['unpaid'], 1)
        self.assert_payload_matches_detail(tournament, self.player)

    def test_summary_confirmation_filter_matches_model_rules(self):
        tournament, stage, _ = self.make_tournament(active=False)
        cases = [
            {}, {'auto_confirmed': True}, {'admin_result': 'score'},
            {'admin_result': 'double_no_show'}, {'admin_result': 'advance'},
            {'admin_result': 'advance', 'admin_winner': self.people[0]},
            {'admin_result': 'disqualify', 'admin_winner': self.people[0]},
            {'admin_result': 'no_show_bye', 'admin_winner': self.people[0]},
            {'score1': 5, 'score2': 0},
            {'score1': 5, 'score2': 0, 'auto_confirmed': True},
            {'score1': 5, 'score2': 0, 'admin_result': 'score'},
            {'score1': 5, 'score2': 0, 'admin_result': 'finish'},
        ]
        fixtures = [Fixture.objects.create(mode=stage, level=index, **fields)
                    for index, fields in enumerate(cases)]
        fixtures[8].confirmations.add(self.player)
        for confirmations in (1, 2):
            if confirmations == 2:
                fixtures[8].confirmations.add(self.opponent)
            confirmed_ids = set(_fixture_reads([tournament.pk]).filter(_confirmed_filter()).values_list('pk', flat=True))
            for fixture in fixtures:
                with self.subTest(fixture=fixture.pk, confirmations=confirmations):
                    self.assertEqual(fixture.pk in confirmed_ids, fixture.is_confirmed)

    def test_history_is_aggregated_and_only_personal_pending_models_are_loaded(self):
        tournament, stage, current = self.make_tournament()
        for level in range(1, 30):
            fixture = Fixture.objects.create(
                mode=stage, level=level, score1=5, score2=0, auto_confirmed=True,
                extras={'large_history': 'x' * 1000},
            )
            FixtureAudit.objects.create(fixture=fixture, action='live_started')
        with CaptureQueriesContext(connection) as captured:
            snapshots = tournament_list_snapshots([tournament], self.player)
        self.assertEqual([fixture.pk for fixture in snapshots[0].fixtures], [current.pk])
        self.assertIn('extras', snapshots[0].fixtures[0].get_deferred_fields())
        self.assertFalse(any('fixtureaudit' in query['sql'].lower() for query in captured))
        self.assertEqual(snapshots[0].participant_count, 2)
        self.assertEqual(len(snapshots[0].participations), 1)

    def test_confirmation_threshold_counts_online_roster_only(self):
        tournament, stage, _ = self.make_tournament(active=False)
        offline = Participant.objects.create(name='list-offline')
        Participation.objects.create(tournament=tournament, participant=offline, slot_id=2)
        fixture = Fixture.objects.create(
            mode=stage, level=0, player1=self.people[0], player2=self.people[1], score1=0, score2=5,
        )
        fixture.confirmations.add(self.player, self.opponent)
        snapshot, payload = self.assert_payload_matches_detail(tournament, self.player)
        self.assertEqual(snapshot.required_confirmations, 2)
        self.assertTrue(payload['is_eliminated'])
        for slot in (3, 4):
            user = User.objects.create(username=f'list-extra-online-{slot}')
            participant = Participant.objects.create(user=user, name=user.username)
            Participation.objects.create(tournament=tournament, participant=participant, slot_id=slot)
        snapshot, payload = self.assert_payload_matches_detail(tournament, self.player)
        self.assertEqual(snapshot.required_confirmations, 3)
        self.assertEqual(payload['state'], 'active')
        self.assertFalse(payload['is_eliminated'])

    def test_tournament_count_does_not_multiply_endpoint_queries(self):
        self.client.force_login(self.player)
        counts = []
        for additional in (1, 11):
            for _ in range(additional):
                self.make_tournament()
            with CaptureQueriesContext(connection) as captured:
                response = self.client.get('/api/tournaments')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()), Tournament.objects.count())
            self.assertIn('X-Club-Revision', response)
            self.assertIn('no-store', response['Cache-Control'])
            writes = [query['sql'] for query in captured if query['sql'].lstrip().upper().startswith(
                ('BEGIN', 'INSERT', 'UPDATE', 'DELETE', 'REPLACE'),
            )]
            self.assertEqual(writes, [])
            counts.append(len(captured))
        self.assertLessEqual(counts[1], counts[0])
        self.assertLessEqual(counts[1], 16)

    def test_search_state_and_publication_filters_preserve_list_contract(self):
        active, _, _ = self.make_tournament()
        opened, _, _ = self.make_tournament(active=False)
        self.make_tournament(published=False)
        response = self.client.get('/api/tournaments', {'state': 'open', 'q': opened.name})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['id'] for row in response.json()], [opened.pk])
        self.assertEqual(self.client.get('/api/tournaments', {'state': 'draft'}).json(), [])
        self.assertEqual(self.client.get('/api/tournaments', {'q': 'absent-list-name'}).json(), [])
        response = self.client.get('/api/tournaments', {'state': 'active'})
        self.assertEqual([row['id'] for row in response.json()], [active.pk])

    def test_personal_candidates_do_not_cross_tournament_boundaries(self):
        first, _, first_fixture = self.make_tournament()
        second, stage, second_fixture = self.make_tournament()
        second_fixture.level = 1
        second_fixture.save(update_fields=['level'])
        Fixture.objects.create(mode=stage, level=0, player1=self.people[1])
        request = RequestFactory().get('/api/tournaments')
        request.user = self.player
        snapshots = tournament_list_snapshots([first, second], self.player)
        payloads = [_serialize_tournament(snapshot.tournament, request, read_snapshot=snapshot)
                    for snapshot in snapshots]
        self.assertEqual(payloads[0]['current_fixture_id'], first_fixture.pk)
        self.assertTrue(payloads[0]['can_play'])
        self.assertEqual(payloads[1]['current_fixture_id'], second_fixture.pk)
        self.assertFalse(payloads[1]['can_play'])
