"""Read endpoints must stay bounded and must not contend as SQLite writers."""
import csv
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, User
from django.db import connection
from django.db.models import Q
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from frontend.tournament_reads import TournamentReadSnapshot
from tournaments.models import (
    DirectPlaySettings, Fixture, Knockout, Mode, Participant, Participation, Tournament,
    WalletTransaction,
)


@override_settings(GAMELINK_ENABLED=True, GAMELINK_BACKGAMMON_URL='https://game.example.invalid')
class IncidentReadTests(TransactionTestCase):
    def make_bracket(self, size=32):
        tournament = Tournament.objects.create(
            name=f'Read budget {size}', published=True,
            starts_at=timezone.now() - timedelta(hours=1), podium_spec=['main.placements[0]'],
        )
        stage = Knockout.objects.create(tournament=tournament, identifier='main')
        for index in range(size):
            user = User.objects.create(username=f'read-{tournament.pk}-{index}')
            participant = Participant.get_or_create_for_user(user)
            Participation.objects.create(tournament=tournament, participant=participant, slot_id=index)
        tournament.update_state()
        user = tournament.participating_users.first()
        self.client.force_login(user)
        return tournament, stage, user

    def assert_read_only(self, url, budget=30):
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        writes = [row['sql'] for row in captured if row['sql'].lstrip().upper().startswith(
            ('BEGIN', 'INSERT', 'UPDATE', 'DELETE', 'REPLACE'))]
        self.assertEqual(writes, [])
        self.assertLessEqual(len(captured), budget)
        return response.json(), len(captured)

    def assert_read_response_with_atomic_requests(self, url, *, status=200, budget=40):
        """Exercise real URL dispatch with and without Django's automatic wrapper."""
        for enabled in (False, True):
            with self.subTest(url=url, atomic_requests=enabled):
                with patch.dict(connection.settings_dict, {'ATOMIC_REQUESTS': enabled}):
                    with CaptureQueriesContext(connection) as captured:
                        response = self.client.get(url)
                self.assertEqual(response.status_code, status, response.content[:500])
                writes = [row['sql'] for row in captured if row['sql'].lstrip().upper().startswith(
                    ('BEGIN', 'SAVEPOINT', 'INSERT', 'UPDATE', 'DELETE', 'REPLACE'))]
                self.assertEqual(writes, [])
                self.assertLessEqual(len(captured), budget)
        return response

    def make_open_tournament(self):
        organizer = User.objects.create(username='read-only-organizer', is_staff=True)
        tournament = Tournament.objects.create(
            name='Overdue but not started', published=True, creator=organizer,
            starts_at=timezone.now() - timedelta(hours=1), podium_spec=['main.placements[0]'],
        )
        Knockout.objects.create(tournament=tournament, identifier='main')
        for index in range(4):
            user = User.objects.create(username=f'open-read-player-{index}')
            participant = Participant.get_or_create_for_user(user)
            Participation.objects.create(tournament=tournament, participant=participant, slot_id=index)
        self.client.force_login(organizer)
        self.assertEqual(tournament.state, 'open')
        return tournament

    def login_without_settings_singleton(self):
        user = User.objects.create(username='read-default-settings', is_staff=True)
        self.client.force_login(user)
        DirectPlaySettings.objects.all().delete()
        self.assertFalse(DirectPlaySettings.objects.exists())
        return user, DirectPlaySettings(pk=1)

    def test_attendees_json_get_does_not_start_a_write_transaction(self):
        tournament = self.make_open_tournament()
        response = self.assert_read_response_with_atomic_requests(
            reverse('api-admin-tournament-attendees', args=[tournament.pk]),
        )
        participant_ids = set(tournament.participations.values_list('participant_id', flat=True))
        self.assertEqual({row['id'] for row in response.json()['participants']}, participant_ids)
        self.assertFalse(Fixture.objects.filter(mode__tournament=tournament).exists())

    def test_attendees_csv_get_does_not_start_a_write_transaction(self):
        tournament = self.make_open_tournament()
        response = self.assert_read_response_with_atomic_requests(
            reverse('api-admin-tournament-attendees', args=[tournament.pk]) + '?format=csv',
        )
        self.assertIn('text/csv', response['Content-Type'])
        rows = list(csv.DictReader(StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual({row['Username'] for row in rows},
                         {f'open-read-player-{index}' for index in range(4)})

    def test_draw_get_does_not_generate_or_confirm_a_draw(self):
        tournament = self.make_open_tournament()
        response = self.assert_read_response_with_atomic_requests(
            reverse('api-admin-tournament-draw', args=[tournament.pk]),
        )
        payload = response.json()
        self.assertEqual(payload['participant_count'], 4)
        self.assertFalse(payload['has_draw'])
        self.assertIsNone(payload['generated_at'])
        self.assertIsNone(payload['confirmed_at'])
        tournament.refresh_from_db()
        self.assertFalse(tournament.draw_order)
        self.assertIsNone(tournament.draw_generated_at)
        self.assertIsNone(tournament.draw_confirmed_at)

    def test_recurring_bonus_get_uses_defaults_without_creating_settings_or_credit(self):
        user, defaults = self.login_without_settings_singleton()
        response = self.assert_read_response_with_atomic_requests(reverse('api-recurring-coin-bonus'))
        payload = response.json()
        self.assertEqual(payload['enabled'], defaults.coin_grant_enabled)
        self.assertEqual(Decimal(payload['amount']), defaults.coin_grant_amount)
        self.assertEqual(payload['interval_hours'], defaults.coin_grant_interval_hours)
        self.assertEqual(Decimal(payload['balance']), Decimal('0'))
        self.assertFalse(DirectPlaySettings.objects.exists())
        self.assertFalse(WalletTransaction.objects.filter(user=user).exists())

    def test_admin_settings_get_returns_unsaved_defaults_when_singleton_is_absent(self):
        _, defaults = self.login_without_settings_singleton()
        response = self.assert_read_response_with_atomic_requests(reverse('api-admin-direct-play-settings'))
        payload = response.json()
        self.assertEqual(payload['enabled'], defaults.enabled)
        self.assertEqual(Decimal(payload['ai_game_fee']), defaults.ai_game_fee)
        self.assertEqual(payload['format_profiles'], defaults.format_profiles)
        self.assertIsNone(payload['updated_at'])
        self.assertFalse(DirectPlaySettings.objects.exists())

    def test_practice_get_returns_unsaved_defaults_without_preparing_a_room(self):
        _, defaults = self.login_without_settings_singleton()
        with patch('gamelink.practice.prepare_room') as prepare:
            response = self.assert_read_response_with_atomic_requests(reverse('practice-api'))
        prepare.assert_not_called()
        self.assertEqual(Decimal(response.json()['fee']), defaults.ai_game_fee)
        self.assertEqual(Decimal(response.json()['balance']), Decimal('0'))
        self.assertIn('no-store', response['Cache-Control'])
        self.assertFalse(DirectPlaySettings.objects.exists())

    def test_legacy_progress_get_cannot_simulate_shuffle_or_start_an_open_tournament(self):
        tournament = self.make_open_tournament()
        original_slots = list(tournament.participations.order_by('pk').values_list('pk', 'slot_id'))
        with patch.object(Tournament, 'test') as simulate, \
                patch.object(Tournament, 'shuffle_participants') as shuffle, \
                patch.object(Tournament, 'update_state') as start:
            self.assert_read_response_with_atomic_requests(
                reverse('tournament-progress', args=[tournament.pk]), status=412,
            )
        simulate.assert_not_called()
        shuffle.assert_not_called()
        start.assert_not_called()
        tournament.refresh_from_db()
        self.assertEqual(tournament.state, 'open')
        self.assertFalse(Fixture.objects.filter(mode__tournament=tournament).exists())
        self.assertEqual(list(tournament.participations.order_by('pk').values_list('pk', 'slot_id')),
                         original_slots)

    def test_progress_query_count_is_bounded_for_32_and_128_players(self):
        counts = []
        for size in (32, 128):
            tournament, _, _ = self.make_bracket(size)
            payload, count = self.assert_read_only(f'/api/admin/tournaments/{tournament.pk}/progress')
            self.assertEqual(sum(len(level['fixtures']) for stage in payload['stages'].values()
                                 for level in stage['levels']), size - 1)
            counts.append(count)
        self.assertLessEqual(counts[1], counts[0] + 2)

    def test_current_match_contains_only_requesting_players_fixture(self):
        tournament, stage, user = self.make_bracket()
        payload, _ = self.assert_read_only(f'/api/tournaments/{tournament.pk}/current-match')
        fixture = stage.fixtures.get(
            Q(player1__user=user) | Q(player2__user=user), level=0,
        )
        self.assertEqual(payload['fixture']['id'], fixture.pk)
        self.assertEqual(payload['tournament']['current_fixture_id'], fixture.pk)
        self.assertTrue(payload['fixture']['can_play'])
        self.assertNotIn('stages', payload)
        for assigned_user in (fixture.player1.user, fixture.player2.user):
            with self.subTest(seat_user=assigned_user.pk):
                self.client.force_login(assigned_user)
                seat_payload, _ = self.assert_read_only(
                    f'/api/tournaments/{tournament.pk}/current-match',
                )
                self.assertEqual(seat_payload['fixture']['id'], fixture.pk)
                self.assertTrue(seat_payload['fixture']['can_play'])
        other = User.objects.create(username='outside-read')
        self.client.force_login(other)
        outside, _ = self.assert_read_only(f'/api/tournaments/{tournament.pk}/current-match')
        self.assertIsNone(outside['fixture'])

    def test_summary_does_not_offer_fixture_to_anonymous_offline_participant(self):
        tournament, stage, _ = self.make_bracket(4)
        participant = stage.fixtures.filter(level=0).first().player1
        participant.user = None
        participant.save(update_fields=['user'])
        snapshot = TournamentReadSnapshot(tournament, AnonymousUser())
        self.assertEqual(snapshot.current_user_fixtures(AnonymousUser()), [])

    def test_snapshot_confirmation_and_round_names_match_authoritative_model(self):
        tournament, stage, user = self.make_bracket(32)
        snapshot = TournamentReadSnapshot(tournament, user)
        self.assertEqual(snapshot.current_level, stage.current_level)
        for fixture in snapshot.fixtures:
            self.assertEqual(snapshot.is_confirmed(fixture), fixture.is_confirmed)
        for level in range(stage.levels):
            self.assertEqual(snapshot.round_names[(stage.pk, level)], stage.get_level_name(level))

    def test_empty_current_stage_has_no_round_name_in_progress_response(self):
        tournament = Tournament.objects.create(
            name='Empty next stage', published=True, podium_spec=[],
            starts_at=timezone.now() - timedelta(hours=1),
        )
        completed = Mode.objects.create(tournament=tournament, identifier='completed')
        Fixture.objects.create(mode=completed, level=0, admin_result='double_no_show')
        Mode.objects.create(tournament=tournament, identifier='empty')
        user = User.objects.create(username='empty-stage-viewer')
        self.client.force_login(user)
        payload, _ = self.assert_read_only(f'/api/admin/tournaments/{tournament.pk}/progress')
        self.assertEqual(payload['control_room']['current_stage'], 'empty')
        self.assertIsNone(payload['control_room']['current_round'])

    def test_early_pair_is_current_personal_match_and_accepts_score_submission(self):
        tournament, stage, _ = self.make_bracket(8)
        sources = list(stage.fixtures.filter(level=0))
        destination_id = sources[0].extras['propagate']['winner']['fixture_id']
        siblings = [item for item in sources
                    if item.extras['propagate']['winner']['fixture_id'] == destination_id]
        self.assertEqual(len(siblings), 2)
        stage.fixtures.filter(pk__in=[item.pk for item in siblings]).update(
            score1=5, score2=0, auto_confirmed=True,
        )
        tournament.update_state()
        destination = stage.fixtures.get(pk=destination_id)
        self.assertEqual(stage.current_level, 0)
        self.assertIsNotNone(destination.playable_at)
        self.client.force_login(destination.player1.user)
        payload, _ = self.assert_read_only(f'/api/tournaments/{tournament.pk}/current-match')
        self.assertEqual(payload['fixture']['id'], destination.pk)
        self.assertTrue(payload['fixture']['can_play'])
        self.assertFalse(payload['fixture']['is_current_round'])
        self.assertEqual(payload['fixture']['operational_status'], 'waiting')
        self.assertEqual(payload['tournament']['current_round'], destination.level)
        response = self.client.post(f'/api/admin/tournaments/{tournament.pk}/progress',
                                    {'fixture_id': destination.pk, 'score1': 5, 'score2': 0},
                                    content_type='application/json')
        self.assertEqual(response.status_code, 200)
        destination.refresh_from_db()
        self.assertEqual(destination.score, (5, 0))

    def test_score_submission_cannot_target_a_different_tournament(self):
        tournament, _, user = self.make_bracket(4)
        _, other_stage, _ = self.make_bracket(4)
        foreign = other_stage.fixtures.filter(level=0).first()
        self.client.force_login(user)
        response = self.client.post(f'/api/admin/tournaments/{tournament.pk}/progress',
                                    {'fixture_id': foreign.pk, 'score1': 5, 'score2': 0},
                                    content_type='application/json')
        self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        self.assertIsNone(foreign.score1)

    def test_head_to_head_get_performs_no_maintenance_or_write(self):
        user = User.objects.create(username='empty-lobby-read')
        self.client.force_login(user)
        with patch('frontend.entry_lifecycle.expire_unstarted_tables') as expire, \
                patch('frontend.entry_lifecycle.touch_open_searches') as touch, \
                patch('frontend.search_lifecycle.reconcile_searches_locked') as reconcile:
            self.assert_read_only('/api/head-to-head/tables', budget=12)
        expire.assert_not_called()
        touch.assert_not_called()
        reconcile.assert_not_called()

    def test_search_presence_requires_authenticated_post(self):
        url = '/api/head-to-head/search-presence'
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {}).status_code, 401)

    def test_progress_submission_still_enters_atomic_transaction(self):
        tournament, stage, _ = self.make_bracket(4)
        fixture = stage.fixtures.filter(level=0).order_by('pk').first()
        self.client.force_login(fixture.player1.user)
        with CaptureQueriesContext(connection) as captured:
            response = self.client.post(f'/api/admin/tournaments/{tournament.pk}/progress',
                                        {'fixture_id': fixture.pk, 'score1': 5, 'score2': 0},
                                        content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any('BEGIN IMMEDIATE' in row['sql'].upper() for row in captured))
        fixture.refresh_from_db()
        self.assertEqual(fixture.score, (5, 0))
