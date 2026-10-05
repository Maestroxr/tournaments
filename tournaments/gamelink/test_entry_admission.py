"""Regression coverage for room reservation, paired admission and ticket retention.

Signed callback payloads model the documented game-server contract. This is a
tournaments-side integration reproduction, not two running servers or a browser.
"""
import datetime
import json
import time
import uuid
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.core.management import call_command, CommandError
from django.db import DatabaseError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from gamelink.housekeeping import purge_expired
from gamelink.models import GameLink, IssuedTicket
from gamelink.signing import sign_result_body
from gamelink.views import _check_playability, _entry_deadline_fields, _try_resolve_no_show
from tournaments.models import Fixture, Knockout, Participant, Participation, Tournament, _notify_match_ready


@override_settings(
    GAMELINK_ENABLED=True,
    GAMELINK_BACKGAMMON_URL="https://game.example.invalid",
    GAMELINK_TICKET_SECRET="incident-test-ticket-not-production-0123456789",
    GAMELINK_RESULT_SECRETS=["incident-test-result-not-production-0123456789"],
    GAMELINK_COMMAND_SECRET="incident-test-command-not-production-0123456789",
)
class AdmissionIncidentTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.users = [User.objects.create_user(username=f"incident-player-{n}") for n in (1, 2)]
        self.tournament = Tournament.objects.create(
            name="Isolated incident reproduction", starts_at=self.now,
            published=True, podium_spec=[], target_points=5,
        )
        stage = Knockout.objects.create(tournament=self.tournament)
        participants = [Participant.create_for_user(user) for user in self.users]
        for slot, participant in enumerate(participants):
            Participation.objects.create(tournament=self.tournament, participant=participant, slot_id=slot)
        self.fixture = Fixture.objects.create(
            mode=stage, level=0, player1=participants[0], player2=participants[1],
            extras={}, playable_at=self.now,
        )
        self.link = GameLink.objects.create(
            fixture=self.fixture, target_points=5,
            expires_at=self.now + datetime.timedelta(hours=2),
            p1_ready_at=self.now, p2_ready_at=self.now,
        )

    def start(self, user):
        self.client.force_login(user)
        return self.client.post(reverse("gamelink-tournament-start", args=[self.tournament.pk]))

    def snapshot(self, status, sequence=0):
        payload = {
            "v": 1, "tournament_id": self.tournament.pk,
            "fixture_id": self.fixture.pk,
            "room_id": "64db8810-175c-4a74-bddd-b3f23f29286f",
            "sequence": sequence, "status": status,
            "state": {"phase": "opening_roll", "turn": None, "dice": []},
            "match_score": {"white": 0, "black": 0},
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        return self.client.post(
            reverse("gamelink-live"), data=raw, content_type="application/json",
            HTTP_X_GAMELINK_TIMESTAMP=timestamp,
            HTTP_X_GAMELINK_NONCE=nonce,
            HTTP_X_GAMELINK_SIGNATURE=sign_result_body(raw, timestamp, nonce),
        )

    def test_control_both_can_get_tickets_before_first_snapshot(self):
        self.assertEqual(self.start(self.users[0]).status_code, 302)
        self.assertEqual(self.start(self.users[1]).status_code, 302)
        self.assertEqual(set(IssuedTicket.objects.values_list("seat", flat=True)), {"p1", "p2"})

    def test_json_entry_returns_only_configured_url_with_private_headers(self):
        self.client.force_login(self.users[0])
        with self.assertLogs('gamelink.views', level='INFO') as logs:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    reverse('gamelink-tournament-start', args=[self.tournament.pk]),
                    {'enter_url': 'https://untrusted.example.invalid/'}, HTTP_ACCEPT='application/json',
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {'enter_url'})
        parsed = urlparse(response.json()['enter_url'])
        self.assertEqual((parsed.scheme, parsed.netloc, parsed.path),
                         ('https', 'game.example.invalid', '/api/link/enter/'))
        ticket = parse_qs(parsed.query)['ticket'][0]
        self.assertTrue(ticket)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        self.assertNotIn(ticket, '\n'.join(logs.output))

    def test_api_play_alias_accepts_json_post_and_preserves_legacy_route(self):
        self.client.force_login(self.users[0])
        api_path = f'/api/gamelink/tournament/{self.tournament.pk}/play/'
        self.assertEqual(reverse('gamelink-tournament-start-api', args=[self.tournament.pk]), api_path)
        response = self.client.post(api_path, HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('enter_url', response.json())
        legacy_path = reverse('gamelink-tournament-start', args=[self.tournament.pk])
        self.assertEqual(legacy_path, f'/t/tournament/{self.tournament.pk}/play')
        self.assertEqual(self.client.post(legacy_path).status_code, 302)

    def test_json_entry_without_session_returns_401_for_all_routes(self):
        for route, pk in [('gamelink-start', self.fixture.pk),
                          ('gamelink-tournament-start', self.tournament.pk),
                          ('gamelink-tournament-start-api', self.tournament.pk)]:
            with self.subTest(route=route):
                response = self.client.post(reverse(route, args=[pk]), HTTP_ACCEPT='application/json')
                self.assertEqual(response.status_code, 401)
                self.assertNotIn('enter_url', response.json())
        self.assertFalse(IssuedTicket.objects.exists())

    def test_readiness_without_session_is_json_401_while_legacy_play_redirects(self):
        response = self.client.post(reverse('gamelink-tournament-ready', args=[self.tournament.pk]))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {'detail': 'Authentication required'})
        self.assertEqual(response['Cache-Control'], 'no-store')
        legacy = self.client.post(reverse('gamelink-tournament-start', args=[self.tournament.pk]))
        self.assertEqual(legacy.status_code, 302)
        self.assertIn('Location', legacy)
        self.assertFalse(IssuedTicket.objects.exists())

    def test_json_entry_still_requires_csrf_protection(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.users[0])
        for route in ('gamelink-tournament-start', 'gamelink-tournament-start-api',
                      'gamelink-tournament-ready'):
            with self.subTest(route=route):
                response = client.post(
                    reverse(route, args=[self.tournament.pk]), HTTP_ACCEPT='application/json',
                )
                self.assertEqual(response.status_code, 403)
        self.assertFalse(IssuedTicket.objects.exists())

    def test_both_ready_persists_admission_before_a_delayed_first_ticket(self):
        self.client.force_login(self.users[0])
        ready = self.client.post(reverse('gamelink-tournament-ready', args=[self.tournament.pk]))
        self.assertEqual(ready.status_code, 200)
        self.assertTrue(ready.json()['both_ready'])
        self.assertFalse(IssuedTicket.objects.exists())
        self.link.refresh_from_db()
        granted_at = self.link.entry_authorized_at
        self.assertIsNotNone(granted_at)
        with patch('gamelink.views.timezone.now',
                   return_value=granted_at + datetime.timedelta(seconds=20)):
            self.assertEqual(self.start(self.users[0]).status_code, 302)
            self.assertEqual(self.start(self.users[1]).status_code, 302)
        self.link.refresh_from_db()
        self.assertEqual(self.link.entry_authorized_at, granted_at)

    def test_second_first_entry_survives_first_players_waiting_snapshot(self):
        self.assertEqual(self.start(self.users[0]).status_code, 302)
        self.assertEqual(self.snapshot("waiting").status_code, 200)
        self.link.refresh_from_db()
        self.assertEqual(self.link.status, 'pending')
        # The first player has already left the lobby. Admission cannot require
        # another overlapping heartbeat after the pair passed the gate once.
        GameLink.objects.filter(pk=self.link.pk).update(
            p1_ready_at=self.now - datetime.timedelta(minutes=3),
        )
        self.client.force_login(self.users[1])
        ready = self.client.post(reverse("gamelink-tournament-ready", args=[self.tournament.pk]))
        self.assertEqual(ready.status_code, 200)
        self.assertTrue(ready.json()["both_ready"])
        response = self.start(self.users[1])
        self.assertEqual(response.status_code, 302,
                         "A reserved waiting room must admit its assigned second player")

    def test_active_reentry_survives_expired_ticket_cleanup(self):
        for user in self.users:
            self.assertEqual(self.start(user).status_code, 302)
        self.assertEqual(self.snapshot("playing").status_code, 200)
        IssuedTicket.objects.update(expires_at=self.now - datetime.timedelta(seconds=1))
        counts = purge_expired(now=self.now)
        self.assertEqual(counts["tickets"], 2)
        self.link.refresh_from_db()
        self.assertEqual(self.link.status, "playing")
        response = self.start(self.users[0])
        self.assertEqual(response.status_code, 302,
                         "Expiring credential audit rows must not revoke active room reentry")

    def test_control_outsider_and_terminal_link_are_not_admitted(self):
        outsider = User.objects.create_user(username="incident-outsider")
        self.assertNotEqual(self.start(outsider).status_code, 302)
        self.assertEqual(self.start(self.users[0]).status_code, 302)
        self.link.status = "completed"
        self.link.save(update_fields=["status"])
        self.assertNotEqual(self.start(self.users[0]).status_code, 302)

    def test_first_ticket_still_requires_both_fresh_ready_seats(self):
        self.link.p2_ready_at = self.now - datetime.timedelta(minutes=1)
        self.link.save(update_fields=['p2_ready_at'])
        self.assertEqual(self.start(self.users[0]).status_code, 412)
        self.link.refresh_from_db()
        self.assertIsNone(self.link.entry_authorized_at)
        self.assertFalse(IssuedTicket.objects.exists())

    def test_changed_pair_cannot_reuse_an_old_grant(self):
        self.assertEqual(self.start(self.users[0]).status_code, 302)
        replacement = User.objects.create_user(username='replacement')
        self.fixture.player2 = Participant.create_for_user(replacement)
        self.fixture.save(update_fields=['player2'])
        self.assertEqual(self.start(self.users[0]).status_code, 412)

    def test_cleanup_preserves_authorized_pending_room_after_expiry(self):
        self.assertEqual(self.start(self.users[0]).status_code, 302)
        self.assertEqual(self.snapshot('waiting').status_code, 200)
        GameLink.objects.filter(pk=self.link.pk).update(
            expires_at=self.now - datetime.timedelta(seconds=1),
        )
        self.assertEqual(purge_expired(now=self.now)['links'], 0)
        self.link.refresh_from_db()
        self.assertEqual(self.link.status, 'pending')
        self.assertEqual(self.start(self.users[1]).status_code, 302)

    def test_paused_tournament_has_no_deadline_and_cleanup_preserves_link(self):
        Tournament.objects.filter(pk=self.tournament.pk).update(entry_deadline_paused=True)
        GameLink.objects.filter(pk=self.link.pk).update(
            expires_at=self.now - datetime.timedelta(seconds=1),
        )
        fixture = Fixture.objects.select_related('mode__tournament').get(pk=self.fixture.pk)
        self.assertEqual(_entry_deadline_fields(fixture, self.now), (None, None))
        self.assertEqual(purge_expired(now=self.now)['links'], 0)

    def test_no_show_does_not_cancel_an_authorized_waiting_room(self):
        self.assertEqual(self.start(self.users[0]).status_code, 302)
        self.link.refresh_from_db()
        later = self.now + datetime.timedelta(minutes=11)
        self.assertIsNone(_try_resolve_no_show(self.fixture, self.link, later))
        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.admin_result, '')

    def test_waiting_snapshot_cannot_regress_a_started_game(self):
        self.assertEqual(self.start(self.users[0]).status_code, 302)
        self.assertEqual(self.snapshot('playing', sequence=2).status_code, 200)
        self.assertEqual(self.snapshot('waiting', sequence=3).status_code, 200)
        self.link.refresh_from_db()
        self.assertEqual(self.link.status, 'playing')
        self.assertEqual(self.link.live_snapshot['sequence'], 2)

    def test_late_snapshot_cannot_replace_terminal_game_state(self):
        self.assertEqual(self.start(self.users[0]).status_code, 302)
        self.assertEqual(self.snapshot('playing', sequence=2).status_code, 200)
        GameLink.objects.filter(pk=self.link.pk).update(status='completed')
        self.assertEqual(self.snapshot('playing', sequence=3).status_code, 200)
        self.link.refresh_from_db()
        self.assertEqual(self.link.status, 'completed')
        self.assertEqual(self.link.live_snapshot['sequence'], 2)

    def test_snapshot_alone_does_not_grant_admission(self):
        self.assertEqual(self.snapshot('playing').status_code, 200)
        self.assertEqual(self.start(self.users[0]).status_code, 412)
        self.link.refresh_from_db()
        self.assertIsNone(self.link.entry_authorized_at)

    def test_terminal_room_snapshot_blocks_tickets_until_canonical_result(self):
        self.assertEqual(self.start(self.users[0]).status_code, 302)
        self.assertEqual(self.snapshot('completed', sequence=2).status_code, 200)
        self.assertEqual(self.snapshot('playing', sequence=3).status_code, 200)
        self.link.refresh_from_db()
        self.assertEqual(self.link.live_snapshot['status'], 'completed')
        self.assertEqual(self.start(self.users[1]).status_code, 412)
        self.fixture.refresh_from_db()
        self.assertIsNone(self.fixture.score1)
        self.assertFalse(self.fixture.auto_confirmed)

    def test_explicit_room_reset_revokes_the_pair_grant(self):
        self.assertEqual(self.start(self.users[0]).status_code, 302)
        call_command('reset_active_game_links', tournament_id=self.tournament.pk,
                     fixture_ids=[self.fixture.pk], execute=True, stdout=StringIO())
        self.link.refresh_from_db()
        self.assertIsNone(self.link.entry_authorized_at)
        self.assertIsNone(self.link.entry_player1_id)
        self.assertIsNone(self.link.entry_player2_id)
        self.assertEqual(self.start(self.users[0]).status_code, 412)

    def test_failed_opponent_enqueue_rolls_back_heartbeat(self):
        self.link.p1_ready_at = None
        self.link.p2_ready_at = None
        self.link.save(update_fields=['p1_ready_at', 'p2_ready_at'])
        self.client.force_login(self.users[0])
        with patch('frontend.push.notify_tournament_opponent_waiting',
                   side_effect=DatabaseError('test queue unavailable')):
            with self.assertRaises(DatabaseError):
                self.client.post(reverse('gamelink-tournament-ready', args=[self.tournament.pk]))
        self.link.refresh_from_db()
        self.assertIsNone(self.link.p1_ready_at)

    def test_failed_match_ready_enqueue_rolls_back_playable_transition(self):
        self.fixture.playable_at = None
        self.fixture.save(update_fields=['playable_at'])
        with patch('frontend.push.notify_tournament_match_ready',
                   side_effect=DatabaseError('test queue unavailable')):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    self.fixture.playable_at = self.now
                    self.fixture.save(update_fields=['playable_at'])
                    _notify_match_ready(self.fixture)
        self.fixture.refresh_from_db()
        self.assertIsNone(self.fixture.playable_at)

    def test_read_snapshot_rejects_a_later_personal_fixture(self):
        snapshot = SimpleNamespace(
            state='active',
            is_confirmed=lambda fixture: False,
            current_user_fixtures=lambda user: [SimpleNamespace(pk=self.fixture.pk + 1000)],
        )
        self.assertEqual(
            _check_playability(self.users[0], self.fixture, read_snapshot=snapshot),
            (None, 412, 'fixture_not_personal_current'),
        )

    def _advance_pair_while_unrelated_game_waits(self, *, next_stage=False):
        stage = self.fixture.mode
        others = []
        for index in range(4):
            user = User.objects.create_user(username=f'unrelated-{index}')
            participant = Participant.create_for_user(user)
            Participation.objects.create(
                tournament=self.tournament, participant=participant, slot_id=index + 2,
            )
            others.append(participant)
        for player, opponent in zip((self.fixture.player1, self.fixture.player2), others[:2]):
            Fixture.objects.create(
                mode=stage, level=0, player1=player, player2=opponent,
                score1=5, score2=0, auto_confirmed=True, extras={}, playable_at=self.now,
            )
        Fixture.objects.create(
            mode=stage, level=0, player1=others[2], player2=others[3],
            extras={}, playable_at=self.now,
        )
        if next_stage:
            self.fixture.mode = Knockout.objects.create(tournament=self.tournament)
            self.fixture.level = 0
        else:
            self.fixture.level = 1
        self.fixture.save(update_fields=['mode', 'level'])
        return stage

    def test_ready_pair_can_play_next_round_while_an_unrelated_game_is_pending(self):
        earlier_stage = self._advance_pair_while_unrelated_game_waits()
        self.assertEqual(earlier_stage.current_level, 0)
        self.assertEqual(self.fixture.level, 1)
        for user in self.users:
            self.client.force_login(user)
            ready = self.client.post(reverse('gamelink-tournament-ready', args=[self.tournament.pk]))
            self.assertEqual(ready.status_code, 200)
            self.assertEqual(ready.json()['fixture_id'], self.fixture.pk)
            self.assertTrue(ready.json()['both_ready'])
            entry = self.client.post(
                f'/api/gamelink/tournament/{self.tournament.pk}/play/', HTTP_ACCEPT='application/json',
            )
            self.assertEqual(entry.status_code, 200)
            self.assertIn('enter_url', entry.json())

    def test_personal_next_stage_pair_is_available_in_snapshot_and_entry(self):
        from frontend.tournament_reads import TournamentReadSnapshot
        earlier_stage = self._advance_pair_while_unrelated_game_waits(next_stage=True)
        snapshot = TournamentReadSnapshot(self.tournament, self.users[0])
        self.assertEqual(snapshot.current_stage.pk, earlier_stage.pk)
        self.assertEqual([item.pk for item in snapshot.current_user_fixtures(self.users[0])],
                         [self.fixture.pk])
        for user in self.users:
            self.assertEqual(self.start(user).status_code, 302)

    def test_unactivated_assigned_pair_cannot_start_early(self):
        self.fixture.playable_at = None
        self.fixture.save(update_fields=['playable_at'])
        self.assertEqual(self.start(self.users[0]).status_code, 412)
        self.assertFalse(IssuedTicket.objects.exists())

    def test_ambiguous_current_assignments_block_both_seats_and_ready(self):
        Fixture.objects.create(
            mode=self.fixture.mode, level=0, player1=self.fixture.player1,
            player2=self.fixture.player2, extras={}, playable_at=self.now,
        )
        for user in self.users:
            self.assertEqual(self.start(user).status_code, 412)
            ready = self.client.post(reverse('gamelink-tournament-ready', args=[self.tournament.pk]))
            self.assertEqual(ready.status_code, 412)
        self.assertFalse(IssuedTicket.objects.exists())

    def test_opponents_earlier_unpaired_fixture_blocks_later_pair(self):
        self.fixture.level = 1
        self.fixture.save(update_fields=['level'])
        Fixture.objects.create(
            mode=self.fixture.mode, level=0, player1=self.fixture.player2,
            player2=None, extras={}, playable_at=None,
        )
        self.assertEqual(_check_playability(self.users[0], self.fixture),
                         (None, 412, 'opponent_not_personal_current'))
        self.assertEqual(self.start(self.users[0]).status_code, 412)

    def test_legacy_overdue_later_fixture_cannot_be_forfeited_while_personally_blocked(self):
        self.fixture.level = 1
        self.fixture.playable_at = self.now - datetime.timedelta(minutes=11)
        self.fixture.save(update_fields=['level', 'playable_at'])
        Fixture.objects.create(
            mode=self.fixture.mode, level=0, player1=self.fixture.player2,
            player2=None, extras={}, playable_at=None,
        )
        for first_ready in (self.now, None):
            with self.subTest(first_player_present=first_ready is not None):
                self.link.p1_ready_at = first_ready
                self.link.p2_ready_at = None
                self.link.save(update_fields=['p1_ready_at', 'p2_ready_at'])
                self.assertIsNone(_try_resolve_no_show(self.fixture, self.link, self.now))
                self.fixture.refresh_from_db()
                self.assertEqual(self.fixture.admin_result, '')

    def test_next_round_entry_still_rejects_outsider_and_terminal_room(self):
        self._advance_pair_while_unrelated_game_waits()
        outsider = User.objects.create_user(username='next-round-outsider')
        self.client.force_login(outsider)
        response = self.client.post(reverse('gamelink-start', args=[self.fixture.pk]),
                                    HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.start(self.users[0]).status_code, 302)
        GameLink.objects.filter(pk=self.link.pk).update(status='completed')
        self.assertEqual(self.start(self.users[1]).status_code, 412)

    def test_legacy_repair_is_dry_run_and_requires_verified_seats(self):
        self.assertEqual(self.snapshot('playing').status_code, 200)
        options = dict(
            tournament_id=self.tournament.pk, fixture_id=self.fixture.pk,
            p1_user_id=self.users[0].pk, p2_user_id=self.users[1].pk,
            room_id='64db8810-175c-4a74-bddd-b3f23f29286f',
            reason='Test operator checked both verifier identities', stdout=StringIO(),
        )
        call_command('restore_game_entry_authorization', **options)
        self.link.refresh_from_db()
        self.assertIsNone(self.link.entry_authorized_at)
        with self.assertRaises(CommandError):
            call_command('restore_game_entry_authorization', execute=True, **options)
        call_command('restore_game_entry_authorization', execute=True,
                     verified_game_server_seats=True, **options)
        self.assertEqual(self.start(self.users[1]).status_code, 302)
