"""Signed technical outcomes keep played points and an unambiguous official winner."""
from decimal import Decimal
from unittest.mock import patch

from tournaments.models import (
    Fixture, FixtureAudit, Participant, Participation, PlayerRating, RatingResult,
    Tournament, User, WalletTransaction,
)

from . import tests as callback_tests


@callback_tests.gamelink_settings
class TechnicalTournamentResultTests(callback_tests.ResultCallbackTestBase):
    def setUp(self):
        super().setUp()
        self.tournament.target_points = 5
        self.tournament.save(update_fields=['target_points'])
        self.game_link.target_points = 5
        self.game_link.save(update_fields=['target_points'])

    def technical_body(self, *, reason='time', winner='p2', played=None, **changes):
        played = {'p1': 1, 'p2': 1} if played is None else dict(played)
        official = dict(played)
        official[winner] = 5
        body = self.result_body(
            target_points=5, score=official, winner_seat=winner, end_reason=reason,
            rating_policy='server-v1',
            technical_result={'reason': reason, 'played_score': played},
        )
        body.update(changes)
        return body

    def assert_rejected_without_result_writes(self, body):
        response = self.deliver(body)
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()['code'], 'invalid_score')
        self.assertNothingRecorded()
        self.assertFalse(FixtureAudit.objects.filter(fixture=self.fixture).exists())
        self.assertFalse(RatingResult.objects.exists())
        self.assertFalse(PlayerRating.objects.exists())
        self.assertFalse(WalletTransaction.objects.exists())

    def test_timeout_official_score_advances_the_declared_winner_and_keeps_played_audit(self):
        other_players = [
            Participant.create_for_user(User.objects.create_user(username=f'other-player-{index}'))
            for index in range(2)
        ]
        for slot_id, participant in enumerate(other_players, start=2):
            Participation.objects.create(
                tournament=self.tournament, participant=participant, slot_id=slot_id,
            )
        final = Fixture.objects.create(
            mode=self.knockout, level=1, extras={'tree': 1, 'position': 1},
        )
        Fixture.objects.create(
            mode=self.knockout, level=0, player1=other_players[0], player2=other_players[1],
            score1=5, score2=0, auto_confirmed=True,
            extras={
                'tree': 1, 'position': 3,
                'propagate': {'winner': {'fixture_id': final.pk, 'player_slot': 2}},
            },
        )
        self.fixture.extras = {
            'tree': 1, 'position': 2,
            'propagate': {'winner': {'fixture_id': final.pk, 'player_slot': 1}},
        }
        self.fixture.save(update_fields=['extras'])
        body = self.technical_body(match_details={
            'white_score': 1, 'black_score': 1, 'winner': 'black', 'end_reason': 'time',
        })

        response = self.deliver(body)

        self.assertEqual(response.status_code, 200, response.content)
        self.fixture.refresh_from_db()
        final.refresh_from_db()
        self.game_link.refresh_from_db()
        self.assertEqual(self.fixture.score, (1, 5))
        self.assertEqual(self.fixture.winner.pk, self.fixture.player2_id)
        self.assertTrue(self.fixture.auto_confirmed)
        self.assertEqual(final.player1_id, self.fixture.player2_id)
        self.assertEqual(final.player2_id, other_players[0].pk)
        self.assertEqual(final.admin_result, '')
        self.assertFalse(final.is_confirmed)
        self.assertIsNotNone(final.playable_at)
        self.assertEqual(self.game_link.raw_result, body)
        self.assertEqual(self.game_link.raw_result['technical_result']['played_score'], {'p1': 1, 'p2': 1})
        self.assertEqual(self.game_link.raw_result['match_details']['white_score'], 1)
        audit = FixtureAudit.objects.get(fixture=self.fixture, action='game_result')
        self.assertEqual(audit.after['score'], [1, 5])
        self.assertEqual(audit.after['technical_result'], body['technical_result'])
        self.assertEqual(RatingResult.objects.get(fixture=self.fixture).winner_id, self.user2.pk)

    def test_a_trailing_player_who_wins_on_time_is_the_official_winner(self):
        response = self.deliver(self.technical_body(played={'p1': 4, 'p2': 1}))
        self.assertEqual(response.status_code, 200, response.content)
        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.score, (4, 5))
        self.assertEqual(self.fixture.winner.pk, self.fixture.player2_id)

    def test_leave_can_end_a_series_without_changing_the_played_loser_score(self):
        response = self.deliver(self.technical_body(reason='leave', winner='p1', played={'p1': 0, 'p2': 4}))
        self.assertEqual(response.status_code, 200, response.content)
        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.score, (5, 4))

    def test_disconnect_uses_the_same_official_result_contract(self):
        response = self.deliver(self.technical_body(reason='disconnect'))
        self.assertEqual(response.status_code, 200, response.content)
        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.score, (1, 5))

    def test_inactivity_timeout_uses_the_same_official_result_contract(self):
        response = self.deliver(self.technical_body(reason='inactivity_timeout'))
        self.assertEqual(response.status_code, 200, response.content)
        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.score, (1, 5))

    def test_duplicate_callback_advances_awards_and_rates_only_once(self):
        self.knockout.identifier = 'main_round'
        self.knockout.save(update_fields=['identifier'])
        self.tournament.podium_spec = ['main_round.placements[0]']
        self.tournament.prize_money = Decimal('50.00')
        self.tournament.save(update_fields=['podium_spec', 'prize_money'])
        body = self.technical_body()
        update_state = Tournament.update_state

        with patch.object(Tournament, 'update_state', autospec=True, side_effect=update_state) as advance:
            first = self.deliver(body)
            second = self.deliver(body)
            # Terminal idempotency still wins over later contradictory metadata.
            changed = self.deliver(self.technical_body(winner_seat='p1', technical_result=None))

        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.json()['status'], 'already_recorded')
        self.assertEqual(changed.json()['status'], 'already_recorded')
        self.assertEqual(advance.call_count, 1)
        self.assertEqual(FixtureAudit.objects.filter(fixture=self.fixture, action='game_result').count(), 1)
        self.assertEqual(RatingResult.objects.filter(fixture=self.fixture).count(), 1)
        prize = WalletTransaction.objects.get(
            tournament=self.tournament, kind=WalletTransaction.KIND_TOURNAMENT_PRIZE,
        )
        self.assertEqual(prize.user_id, self.user2.pk)
        self.assertEqual(prize.amount, Decimal('50.00'))
        self.assertEqual(PlayerRating.objects.get(user=self.user2).games_played, 1)
        self.game_link.refresh_from_db()
        self.assertEqual(self.game_link.raw_result, body)

    def test_supplied_winner_must_agree_with_the_official_score_even_without_metadata(self):
        for winner in ('p1', 'p3', False, ['p2']):
            with self.subTest(winner=winner):
                self.assert_rejected_without_result_writes(self.result_body(
                    target_points=5, score={'p1': 1, 'p2': 5}, winner_seat=winner,
                ))

    def test_legacy_missing_winner_keeps_score_derived_completion(self):
        body = self.result_body(target_points=5, score={'p1': 1, 'p2': 0})
        body.pop('winner_seat')
        self.assertEqual(self.deliver(body).status_code, 200)
        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.winner.pk, self.fixture.player1_id)

    def test_legacy_null_winner_keeps_score_derived_completion(self):
        body = self.result_body(target_points=5, score={'p1': 1, 'p2': 0}, winner_seat=None)
        self.assertEqual(self.deliver(body).status_code, 200)
        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.winner.pk, self.fixture.player1_id)

    def test_legacy_knockout_draw_is_still_rejected(self):
        self.assert_rejected_without_result_writes(self.result_body(
            score={'p1': 1, 'p2': 1}, winner_seat=None,
        ))

    def test_technical_result_requires_an_explicit_winner(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                body = self.technical_body(winner_seat=None)
                if missing:
                    body.pop('winner_seat')
                self.assert_rejected_without_result_writes(body)

    def test_malformed_technical_metadata_cannot_change_result_or_rating(self):
        cases = [
            None,
            [],
            {'reason': 'give_up', 'played_score': {'p1': 1, 'p2': 1}},
            {'reason': 'disconnect', 'played_score': {'p1': 1, 'p2': 1}},
            {'reason': [], 'played_score': {'p1': 1, 'p2': 1}},
            {'reason': 'time', 'played_score': None},
            {'reason': 'time', 'played_score': {'p1': 1}},
            {'reason': 'time', 'played_score': {'p1': True, 'p2': 1}},
            {'reason': 'time', 'played_score': {'p1': -1, 'p2': 1}},
            {'reason': 'time', 'played_score': {'p1': 1, 'p2': 32768}},
            {'reason': 'time', 'played_score': {'p1': 5, 'p2': 1}},
        ]
        for technical in cases:
            with self.subTest(technical=technical):
                self.assert_rejected_without_result_writes(self.technical_body(technical_result=technical))

    def test_official_target_loser_and_non_money_contract_are_checked(self):
        cases = [
            {'score': {'p1': 1, 'p2': 4}},
            {'score': {'p1': 2, 'p2': 5}},
            {'target_points': 7},
            {'target_points': True},
            {'financial_result': {'format': 'money'}},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                self.assert_rejected_without_result_writes(self.technical_body(**changes))

    def test_technical_target_uses_the_issued_link_not_later_tournament_settings(self):
        self.tournament.target_points = 9
        self.tournament.save(update_fields=['target_points'])
        response = self.deliver(self.technical_body())
        self.assertEqual(response.status_code, 200, response.content)
        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.score, (1, 5))
