"""A scheduled group pairing gets its clock only when both players reach it."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from frontend.task_runner import expire_tournament_entry_deadlines
from tournaments.models import Fixture, Groups, Participant, Participation, Tournament


class GroupActivationTests(TestCase):
    def setUp(self):
        self.tournament = Tournament.objects.create(
            name='Group readiness', published=True, starts_at=timezone.now(),
            podium_spec=['groups.placements[0]'],
        )
        self.stage = Groups.objects.create(
            tournament=self.tournament, identifier='groups', min_group_size=4, max_group_size=4,
        )
        for index in range(8):
            user = User.objects.create(username=f'group-next-{index}')
            participant = Participant.get_or_create_for_user(user)
            Participation.objects.create(tournament=self.tournament, participant=participant, slot_id=index)
        self.tournament.update_state()

    def test_only_personally_next_pairs_have_initial_deadlines(self):
        self.assertEqual(self.stage.fixtures.filter(level=0, playable_at__isnull=False).count(), 4)
        self.assertFalse(self.stage.fixtures.filter(level__gt=0, playable_at__isnull=False).exists())

    def test_finished_group_advances_while_other_group_still_has_first_round(self):
        self.stage.refresh_from_db()
        participants = self.stage.groups_info[0]
        first_round = self.stage.fixtures.filter(level=0, player1_id__in=participants)
        first_round.update(score1=5, score2=0, auto_confirmed=True)
        now = timezone.now() + timedelta(minutes=20)
        with patch('tournaments.models.timezone.now', return_value=now), \
                patch('tournaments.models._notify_match_ready') as notify:
            self.tournament.update_state()
        next_round = list(self.stage.fixtures.filter(level=1, player1_id__in=participants))
        self.assertEqual(len(next_round), 2)
        self.assertTrue(all(fixture.playable_at == now for fixture in next_round))
        self.assertEqual(self.stage.current_level, 0)
        self.assertEqual(notify.call_count, 2)
        with patch('tournaments.models.timezone.now', return_value=now + timedelta(minutes=5)), \
                patch('tournaments.models._notify_match_ready') as repeat:
            self.tournament.update_state()
        self.assertEqual(set(self.stage.fixtures.filter(
            pk__in=[fixture.pk for fixture in next_round],
        ).values_list('playable_at', flat=True)), {now})
        repeat.assert_not_called()

    def test_legacy_future_deadlines_cannot_starve_or_expire_before_personal_turn(self):
        self.stage.fixtures.filter(level__gt=0).update(playable_at=timezone.now() - timedelta(hours=1))
        eligible = self.stage.fixtures.filter(level=0).order_by('pk').first()
        Fixture.objects.filter(pk=eligible.pk).update(playable_at=timezone.now() - timedelta(minutes=20))
        with patch('frontend.task_runner.ENTRY_EXPIRY_BATCH_SIZE', 1), \
                patch('gamelink.views._resolve_double_no_show_locked', return_value=True) as resolve:
            self.assertEqual(expire_tournament_entry_deadlines(heartbeat=lambda: True), 1)
        resolve.assert_called_once()
        self.assertEqual(resolve.call_args.args[0].pk, eligible.pk)
        self.assertFalse(self.stage.fixtures.filter(level__gt=0).exclude(admin_result='').exists())
