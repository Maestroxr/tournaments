"""A ready knockout branch does not wait for unrelated earlier matches."""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from tournaments.models import Fixture, Knockout, Participant, Participation, Tournament


class AsyncKnockoutProgressionTests(TestCase):
    def setUp(self):
        self.tournament = Tournament.objects.create(
            name='Independent branches', published=True,
            starts_at=timezone.now() - timedelta(hours=1), podium_spec=['main.placements[0]'],
        )
        self.stage = Knockout.objects.create(tournament=self.tournament, identifier='main')
        for index in range(8):
            participant = Participant.objects.create(name=f'branch-{index}')
            Participation.objects.create(
                tournament=self.tournament, participant=participant, slot_id=index,
            )
        self.tournament.update_state()
        self.destination = self.stage.fixtures.filter(level=1).order_by('pk').first()
        self.sources = [
            fixture for fixture in self.stage.fixtures.filter(level=0)
            if fixture.extras['propagate']['winner']['fixture_id'] == self.destination.pk
        ]
        self.assertEqual(len(self.sources), 2)

    def complete(self, fixture):
        Fixture.objects.filter(pk=fixture.pk).update(score1=5, score2=0, auto_confirmed=True)
        self.tournament.update_state()

    def test_one_winner_does_not_start_destination_clock(self):
        with patch('tournaments.models._notify_match_ready') as notify:
            self.complete(self.sources[0])
        self.destination.refresh_from_db()
        self.assertIsNone(self.destination.playable_at)
        self.assertEqual(sum(value is not None for value in (
            self.destination.player1_id, self.destination.player2_id,
        )), 1)
        notify.assert_not_called()

    def test_two_early_winners_start_clock_and_notify_once_before_round_ends(self):
        self.complete(self.sources[0])
        ready_at = timezone.now() + timedelta(minutes=1)
        with patch('tournaments.models.timezone.now', return_value=ready_at), \
                patch('tournaments.models._notify_match_ready') as notify:
            self.complete(self.sources[1])
            self.tournament.update_state()
        self.destination.refresh_from_db()
        self.assertEqual(self.stage.current_level, 0)
        self.assertEqual(self.destination.playable_at, ready_at)
        from gamelink.views import _entry_deadline_fields
        deadline, remaining = _entry_deadline_fields(self.destination, ready_at)
        self.assertEqual(deadline, ready_at + timedelta(minutes=10))
        self.assertEqual(remaining, 600)
        self.assertIsNotNone(self.destination.player1_id)
        self.assertIsNotNone(self.destination.player2_id)
        self.assertFalse(self.destination.is_confirmed)
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[0].pk, self.destination.pk)
        with patch('tournaments.models.timezone.now', return_value=ready_at + timedelta(minutes=5)), \
                patch('tournaments.models._notify_match_ready') as later_notify:
            self.tournament.update_state()
        self.destination.refresh_from_db()
        self.assertEqual(self.destination.playable_at, ready_at)
        later_notify.assert_not_called()

    def test_previously_assigned_later_pair_gets_clock_without_global_round_advance(self):
        for source in self.sources:
            self.complete(source)
        # A previous release assigned this pair but delayed its clock until
        # unrelated first-round matches finished.
        Fixture.objects.filter(pk=self.destination.pk).update(playable_at=None)
        ready_at = timezone.now()
        with patch('tournaments.models.timezone.now', return_value=ready_at), \
                patch('tournaments.models._notify_match_ready') as notify:
            self.stage.update_fixtures()
        self.destination.refresh_from_db()
        self.assertEqual(self.stage.current_level, 0)
        self.assertEqual(self.destination.playable_at, ready_at)
        notify.assert_called_once()

    def test_early_next_round_result_propagates_without_finishing_unrelated_branch(self):
        for source in self.sources:
            self.complete(source)
        self.destination.refresh_from_db()
        self.complete(self.destination)
        final = self.stage.fixtures.get(level=2)
        self.assertIn(self.destination.player1_id, (final.player1_id, final.player2_id))
        self.assertIsNone(final.playable_at)
        self.assertEqual(self.stage.current_level, 0)
        self.assertEqual(self.tournament.state, 'active')
        self.assertFalse(self.tournament.participations.filter(podium_position__isnull=False).exists())

    def test_result_in_initialized_later_stage_propagates_while_first_stage_is_open(self):
        later = Knockout.objects.create(tournament=self.tournament, identifier='independent')
        players = [Participant.objects.create(name=f'later-{index}') for index in range(4)]
        for index, participant in enumerate(players, start=8):
            Participation.objects.create(tournament=self.tournament, participant=participant, slot_id=index)
        later.create_fixtures(players)
        for fixture in later.fixtures.filter(level=0):
            Fixture.objects.filter(pk=fixture.pk).update(score1=5, score2=0, auto_confirmed=True)
        self.tournament.update_state()
        final = later.fixtures.get(level=1)
        self.assertIsNotNone(final.player1_id)
        self.assertIsNotNone(final.player2_id)
        self.assertIsNotNone(final.playable_at)
        self.assertEqual(self.tournament.current_stage.pk, self.stage.pk)
        self.assertFalse(self.tournament.participations.filter(podium_position__isnull=False).exists())
