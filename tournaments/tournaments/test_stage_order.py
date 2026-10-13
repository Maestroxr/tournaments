"""Dependent stages must not start before their predecessors."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from tournaments.models import Mode, Participant, Participation, Tournament
from tournaments.tests import test_tournament1_yml


class TournamentStageOrderTests(TestCase):
    def test_dependent_stage_waits_for_preliminaries_despite_reversed_query_order(self):
        tournament = Tournament.load(
            definition=test_tournament1_yml, name='Ordered stages',
            published=True, starts_at=timezone.now() - timedelta(minutes=1),
        )
        for slot in range(10):
            user = User.objects.create_user(username=f'stage-order-{slot}')
            participant = Participant.get_or_create_for_user(user)
            Participation.objects.create(
                tournament=tournament, participant=participant, slot_id=slot,
            )
        # Deliberately make the implicit database order hostile to stage dependencies.
        with patch.object(Mode._meta, 'ordering', ('-pk',)):
            self.assertEqual(tournament.stages.all().first().identifier, 'playoffs')
            self.assertEqual(tournament.current_stage.identifier, 'preliminaries')
            tournament.update_state()
            self.assertEqual(tournament.state, 'active')
            self.assertEqual(tournament.current_stage.identifier, 'preliminaries')
            self.assertTrue(tournament.stages.get(identifier='preliminaries').fixtures.exists())
            self.assertFalse(tournament.stages.get(identifier='main_round').fixtures.exists())
            self.assertFalse(tournament.stages.get(identifier='playoffs').fixtures.exists())
