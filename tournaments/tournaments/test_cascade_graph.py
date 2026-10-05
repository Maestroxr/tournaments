"""Bounded per-call graph loading without caching state across writes."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import OperationalError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from gamelink.models import GameLink
from tournaments.models import Fixture, FixtureAudit, Knockout, Participant, Participation, Tournament


class CascadeGraphTests(TestCase):
    def bracket(self, size=4, *, users=False):
        tournament = Tournament.objects.create(
            name='Cascade graph', published=True, starts_at=timezone.now() - timedelta(hours=1),
            podium_spec=['main.placements[0]'],
        )
        stage = Knockout.objects.create(tournament=tournament, identifier='main')
        for index in range(size):
            name = f'graph-{tournament.pk}-{index}'
            user = User.objects.create(username=name) if users else None
            participant = Participant.objects.create(name=name, user=user)
            Participation.objects.create(tournament=tournament, participant=participant, slot_id=index)
        tournament.update_state()
        return tournament, stage

    def test_noop_query_budget_is_constant_for_32_and_128_players(self):
        for size in (32, 128):
            with self.subTest(players=size):
                _, stage = self.bracket(size)
                with CaptureQueriesContext(connection) as queries:
                    self.assertFalse(stage._resolve_empty_destinations())
                # One fixture graph + one confirmation prefetch. Allow one
                # threshold read if the fixture policy evolves to need it.
                self.assertLessEqual(len(queries), 3)
                self.assertFalse(any('UPDATE ' in item['sql'].upper() for item in queries))

    def test_manual_confirmations_are_fresh_on_each_call(self):
        tournament, stage = self.bracket(users=True)
        first, second = list(stage.fixtures.filter(level=0).order_by('pk'))
        final = stage.fixtures.get(level=1)
        Fixture.objects.filter(pk=first.pk).update(score1=5, score2=0)
        Fixture.objects.filter(pk=second.pk).update(admin_result='double_no_show')
        self.assertFalse(stage._resolve_empty_destinations())
        first.confirmations.add(*User.objects.filter(participant__participations__tournament=tournament)[:3])
        self.assertTrue(stage._resolve_empty_destinations())
        final.refresh_from_db()
        self.assertEqual(final.admin_result, 'no_show_bye')
        self.assertEqual(final.admin_winner_id, first.player1_id)
        self.assertFalse(stage._resolve_empty_destinations())
        self.assertEqual(FixtureAudit.objects.filter(fixture=final, action='no_show_bye').count(), 1)

    def test_loser_edge_uses_loser_instead_of_winner(self):
        _, stage = self.bracket()
        first, second = list(stage.fixtures.filter(level=0).order_by('pk'))
        final = stage.fixtures.get(level=1)
        first.extras = {'propagate': {'loser': {'fixture_id': final.pk, 'player_slot': 'player1'}}}
        first.admin_result = 'advance'
        first.admin_winner_id = first.player1_id
        first.save(update_fields=['extras', 'admin_result', 'admin_winner'])
        Fixture.objects.filter(pk=second.pk).update(admin_result='double_no_show')
        self.assertTrue(stage._resolve_empty_destinations())
        final.refresh_from_db()
        self.assertEqual(final.admin_winner_id, first.player2_id)
        self.assertEqual(final.admin_result, 'no_show_bye')

    def test_two_terminal_winners_do_not_auto_resolve_destination(self):
        _, stage = self.bracket()
        for source in stage.fixtures.filter(level=0):
            source.admin_result = 'advance'
            source.admin_winner_id = source.player1_id
            source.save(update_fields=['admin_result', 'admin_winner'])
        self.assertFalse(stage._resolve_empty_destinations())
        final = stage.fixtures.get(level=1)
        self.assertEqual(final.admin_result, '')
        self.assertFalse(FixtureAudit.objects.filter(fixture=final).exists())

    def test_nested_empty_branches_finish_without_duplicate_audits(self):
        tournament, stage = self.bracket(8)
        stage.fixtures.filter(level=0).update(admin_result='double_no_show')
        tournament.update_state()
        self.assertIsNone(tournament.current_stage)
        self.assertEqual(stage.fixtures.filter(admin_result='double_no_show').count(), 7)
        self.assertEqual(FixtureAudit.objects.filter(fixture__mode=stage, action='double_no_show').count(), 3)
        self.assertFalse(stage._resolve_empty_destinations())
        self.assertEqual(FixtureAudit.objects.filter(fixture__mode=stage, action='double_no_show').count(), 3)

    def test_pending_link_cancellation_failure_rolls_back_resolution_and_audit(self):
        _, stage = self.bracket()
        stage.fixtures.filter(level=0).update(admin_result='double_no_show')
        final = stage.fixtures.get(level=1)
        link = GameLink.objects.create(fixture=final, expires_at=timezone.now())
        with patch('gamelink.models.GameLink.objects.filter') as links:
            links.return_value.update.side_effect = OperationalError('injected database lock')
            with self.assertRaises(OperationalError), transaction.atomic():
                stage._resolve_empty_destinations()
        final.refresh_from_db()
        link.refresh_from_db()
        self.assertEqual(final.admin_result, '')
        self.assertEqual(link.status, 'pending')
        self.assertFalse(FixtureAudit.objects.filter(fixture=final).exists())
