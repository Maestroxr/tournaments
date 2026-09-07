from decimal import Decimal
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from gamelink.models import GameLink
from tournaments.models import Tournament, Participant, Participation, Fixture, FixtureAudit, WalletTransaction


class MatchAdministrationTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='organizer', is_staff=True)
        self.client.force_login(self.staff)
        response = self.client.post(reverse('api-admin-tournaments'), {
            'name': 'Admin cup', 'template': 'knockout', 'min_players': 4,
            'max_players': 4, 'open_registration': True, 'entry_fee': '50',
        }, content_type='application/json')
        self.tournament = Tournament.objects.get(pk=response.json()['id'])
        for i in range(4):
            user = User.objects.create_user(username=f'player{i}')
            participant = Participant.get_or_create_for_user(user)
            Participation.objects.create(tournament=self.tournament, participant=participant, slot_id=i)
            WalletTransaction.create_entry(user=user, amount=Decimal('50'), kind='deposit')
            WalletTransaction.create_entry(user=user, amount=Decimal('-50'), kind='tournament_entry', tournament=self.tournament)
        self.client.post(reverse('api-admin-tournament-close-registration', kwargs={'pk': self.tournament.pk}))
        self.client.post(reverse('api-admin-tournament-draw', kwargs={'pk': self.tournament.pk}), {}, content_type='application/json')
        self.client.post(reverse('api-admin-tournament-confirm-draw', kwargs={'pk': self.tournament.pk}))
        self.client.post(reverse('api-admin-tournament-start', kwargs={'pk': self.tournament.pk}))
        self.fixture = Fixture.objects.filter(mode__tournament=self.tournament, level=0).first()
        self.url = reverse('api-admin-match', kwargs={'pk': self.tournament.pk, 'fixture_id': self.fixture.pk})

    def post(self, **data):
        data.setdefault('version', self.client.get(self.url).json()['version'])
        data.setdefault('reason', 'Organizer decision')
        data.setdefault('confirm', True)
        return self.client.post(self.url, data, content_type='application/json')

    def test_staff_only_and_tournament_scope(self):
        self.client.force_login(self.fixture.player1.user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {'action': 'note'}, content_type='application/json').status_code, 403)
        self.client.force_login(self.staff)
        wrong = reverse('api-admin-match', kwargs={'pk': self.tournament.pk + 100, 'fixture_id': self.fixture.pk})
        self.assertEqual(self.client.get(wrong).status_code, 404)

    def test_private_notes_and_optimistic_conflicts(self):
        version = self.client.get(self.url).json()['version']
        response = self.post(action='note', note='Private investigation', version=version)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['note'], 'Private investigation')
        self.assertEqual(self.post(action='note', note='stale', version=version).status_code, 409)
        self.assertEqual(FixtureAudit.objects.filter(fixture=self.fixture).count(), 1)
        self.client.force_login(self.fixture.player1.user)
        public = self.client.get(reverse('api-admin-tournament-progress', kwargs={'pk': self.tournament.pk}))
        self.assertNotIn(b'Private investigation', public.content)

    def test_manual_score_confirms_and_propagates_once(self):
        response = self.post(action='score', score1=5, score2=2)
        self.assertEqual(response.status_code, 200, response.content)
        self.fixture.refresh_from_db()
        self.assertTrue(self.fixture.is_confirmed)
        self.assertEqual(self.fixture.winner, self.fixture.player1)
        final = self.tournament.stages.first().fixtures.get(level=1)
        self.assertIn(self.fixture.player1_id, [final.player1_id, final.player2_id])
        self.assertEqual(self.post(action='score', score1=2, score2=5).status_code, 409)

    def test_disqualification_is_tournament_wide_without_fabricated_score_or_automatic_refund(self):
        response = self.post(action='disqualify', participant_id=self.fixture.player1_id)
        self.assertEqual(response.status_code, 200, response.content)
        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.score, (None, None))
        self.assertTrue(self.fixture.is_confirmed)
        self.assertEqual(self.fixture.winner, self.fixture.player2)
        self.assertTrue(self.tournament.participations.get(participant=self.fixture.player1).disqualified_at)
        self.assertEqual(WalletTransaction.balance_for_user(self.fixture.player1.user), Decimal('0'))
        self.assertFalse(Fixture.objects.filter(mode__tournament=self.tournament, level=1, player1=self.fixture.player1).exists())

    def test_opt_in_refund_is_actual_fee_and_cannot_be_repeated(self):
        self.assertEqual(self.post(action='disqualify', participant_id=self.fixture.player1_id, refund=True).status_code, 200)
        self.assertEqual(WalletTransaction.balance_for_user(self.fixture.player1.user), Decimal('50'))
        self.assertEqual(self.post(action='refund', participant_id=self.fixture.player1_id).status_code, 400)
        self.assertEqual(WalletTransaction.objects.filter(kind='tournament_refund').count(), 1)

    def test_refund_can_be_requested_later_and_respects_prior_partial_refund(self):
        WalletTransaction.create_entry(user=self.fixture.player1.user, tournament=self.tournament,
            amount=Decimal('15'), kind='tournament_refund')
        self.post(action='disqualify', participant_id=self.fixture.player1_id)
        response = self.post(action='refund', participant_id=self.fixture.player1_id)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['history'][0]['after']['refund']['amount'], '35.00')
        self.assertEqual(WalletTransaction.balance_for_user(self.fixture.player1.user), Decimal('50'))

    def test_refund_failure_rolls_back_disqualification(self):
        WalletTransaction.create_entry(user=self.fixture.player1.user, tournament=self.tournament,
            amount=Decimal('50'), kind='tournament_refund')
        response = self.post(action='disqualify', participant_id=self.fixture.player1_id, refund=True)
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self.tournament.participations.get(participant=self.fixture.player1).disqualified_at)
        self.fixture.refresh_from_db()
        self.assertFalse(self.fixture.is_confirmed)

    def test_advancement_is_distinct_from_disqualification(self):
        response = self.post(action='advance', participant_id=self.fixture.player1_id)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(self.tournament.participations.filter(disqualified_at__isnull=False).exists())

    def test_advancement_marks_the_other_player_eliminated_in_player_api(self):
        winner = self.fixture.player1
        loser = self.fixture.player2
        response = self.post(action='advance', participant_id=winner.id)
        self.assertEqual(response.status_code, 200, response.content)

        self.client.force_login(loser.user)
        tournaments = self.client.get(reverse('api-tournaments')).json()
        serialized = next(item for item in tournaments if item['id'] == self.tournament.id)
        self.assertTrue(serialized['is_eliminated'])

        self.client.force_login(winner.user)
        tournaments = self.client.get(reverse('api-tournaments')).json()
        serialized = next(item for item in tournaments if item['id'] == self.tournament.id)
        self.assertFalse(serialized['is_eliminated'])

    def test_requires_reason_confirmation_and_valid_score(self):
        for data in [dict(action='score', score1=5, score2=5), dict(action='score', score1=-1, score2=5),
                     dict(action='advance', participant_id=self.fixture.player1_id, reason=''),
                     dict(action='advance', participant_id=self.fixture.player1_id, confirm=False)]:
            self.assertEqual(self.post(**data).status_code, 400)
        self.fixture.refresh_from_db()
        self.assertFalse(self.fixture.is_confirmed)

    def test_late_game_callback_cannot_overwrite_admin_result(self):
        from gamelink.views import ResultCallbackView
        from django.test import RequestFactory
        GameLink.objects.create(fixture=self.fixture, expires_at=timezone.now() + timedelta(hours=1))
        self.post(action='advance', participant_id=self.fixture.player1_id)
        # Exercise the validated callback's transactional result handler directly.
        view = ResultCallbackView()
        response = view.record(RequestFactory().post('/'), {'fixture_id': self.fixture.pk})
        self.assertEqual(response.status_code, 409)
        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.winner, self.fixture.player1)

    def test_final_disqualification_finishes_tournament_without_ranking_disqualified_player(self):
        for fixture in Fixture.objects.filter(mode__tournament=self.tournament, level=0):
            self.url = reverse('api-admin-match', kwargs={'pk': self.tournament.pk, 'fixture_id': fixture.pk})
            response = self.post(action='advance', participant_id=fixture.player1_id)
            self.assertEqual(response.status_code, 200, response.content)
        final = Fixture.objects.get(mode__tournament=self.tournament, level=1)
        self.url = reverse('api-admin-match', kwargs={'pk': self.tournament.pk, 'fixture_id': final.pk})
        response = self.post(action='disqualify', participant_id=final.player1_id, refund=True)
        self.assertEqual(response.status_code, 200, response.content)
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.state, 'finished')
        self.assertIn(final.player2, self.tournament.podium)
        self.assertNotIn(final.player1, self.tournament.podium)
        self.assertIsNone(self.tournament.participations.get(participant=final.player1).podium_position)

    def test_ruling_serializes_winner_and_roster_disqualification_but_not_private_reason(self):
        self.post(action='disqualify', participant_id=self.fixture.player1_id, reason='Private disciplinary reason')
        response = self.client.get(reverse('api-admin-tournament-progress', kwargs={'pk': self.tournament.pk}))
        fixtures = [f for stage in response.json()['stages'].values() for level in stage['levels'] for f in level['fixtures']]
        fixture = next(f for f in fixtures if f['id'] == self.fixture.pk)
        self.assertEqual(fixture['admin_resolution'], 'disqualify')
        self.assertEqual(fixture['winner_id'], self.fixture.player2_id)
        self.assertFalse(fixture['can_play'])
        self.assertNotIn(b'Private disciplinary reason', response.content)
        roster = self.client.get(reverse('api-admin-tournament-attendees', kwargs={'pk': self.tournament.pk})).json()
        self.assertTrue(next(p for p in roster['participants'] if p['id'] == self.fixture.player1_id)['disqualified'])

    def test_future_round_and_foreign_player_rulings_are_rejected(self):
        self.assertEqual(self.post(action='disqualify', participant_id=999999).status_code, 400)
        final = Fixture.objects.get(mode__tournament=self.tournament, level=1)
        self.url = reverse('api-admin-match', kwargs={'pk': self.tournament.pk, 'fixture_id': final.pk})
        self.assertFalse(self.client.get(self.url).json()['can_rule'])
        self.assertEqual(self.post(action='score', score1=5, score2=1).status_code, 409)

    def test_legacy_player_submission_cannot_change_ruling(self):
        self.post(action='advance', participant_id=self.fixture.player1_id)
        self.client.force_login(self.fixture.player2.user)
        response = self.client.post(reverse('tournament-progress', kwargs={'pk': self.tournament.pk}),
            {'fixture_id': self.fixture.pk, 'score1': 0, 'score2': 5})
        self.assertEqual(response.status_code, 403)
        player = self.fixture.player2.user
        player.is_staff = True
        player.save(update_fields=['is_staff'])
        response = self.client.post(reverse('tournament-progress', kwargs={'pk': self.tournament.pk}),
            {'fixture_id': self.fixture.pk, 'score1': 0, 'score2': 5})
        self.assertEqual(response.status_code, 409)
        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.winner.pk, self.fixture.player1_id)
