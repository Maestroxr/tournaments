import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tournaments.models import (
    Fixture, Participant, Participation, Tournament, TournamentRegistration,
    WalletTransaction,
)


DEFINITION = """
stages:
  - id: main
    name: Main round
    mode: knockout
podium:
  - main.placements[0]
  - main.placements[1]
"""


class TournamentLifecycleTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="organizer", is_staff=True)
        self.players = [
            User.objects.create_user(username=f"player{index}", password="pass")
            for index in range(1, 4)
        ]
        self.tournament = Tournament.load(
            DEFINITION,
            "Lifecycle cup",
            creator=self.staff,
            published=True,
            min_players=2,
            max_players=2,
        )
        self.client.force_login(self.staff)

    def add_player(self, user):
        participant = Participant.get_or_create_for_user(user)
        Participation.objects.create(
            tournament=self.tournament,
            participant=participant,
            slot_id=Participation.next_slot_id(self.tournament),
        )
        return participant

    def post(self, name, data=None):
        return self.client.post(
            reverse(name, kwargs={"pk": self.tournament.pk}),
            data=json.dumps(data or {}),
            content_type="application/json",
        )

    def test_draw_must_be_confirmed_before_start_and_order_is_preserved(self):
        participants = [self.add_player(user) for user in self.players[:2]]
        self.assertEqual(self.tournament.lifecycle_state, "registration_open")

        premature = self.post("api-admin-tournament-start")
        self.assertEqual(premature.status_code, 412)

        closed = self.post("api-admin-tournament-close-registration")
        self.assertEqual(closed.status_code, 200)
        self.assertEqual(closed.json()["lifecycle_state"], "registration_closed")

        generated = self.post("api-admin-tournament-draw")
        self.assertEqual(generated.status_code, 200, generated.content)
        self.assertEqual(generated.json()["lifecycle_state"], "draw_ready")
        self.assertCountEqual(
            [participant["id"] for participant in generated.json()["participants"]],
            [participant.id for participant in participants],
        )

        requested_order = [participants[1].id, participants[0].id]
        reordered = self.post("api-admin-tournament-draw", {"participant_ids": requested_order})
        self.assertEqual(
            [participant["id"] for participant in reordered.json()["participants"]],
            requested_order,
        )

        confirmed = self.post("api-admin-tournament-confirm-draw")
        self.assertEqual(confirmed.status_code, 200, confirmed.content)
        self.assertEqual(confirmed.json()["lifecycle_state"], "ready_to_start")

        started = self.post("api-admin-tournament-start")
        self.assertEqual(started.status_code, 200, started.content)
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.state, "active")
        self.assertEqual(list(self.tournament.participants.values_list("id", flat=True)), requested_order)
        self.assertTrue(Fixture.objects.filter(mode__tournament=self.tournament).exists())

    def test_dashboard_exposes_current_round_progress_and_next_match(self):
        participants = [self.add_player(user) for user in self.players[:2]]
        self.post("api-admin-tournament-close-registration")
        self.post("api-admin-tournament-draw", {
            "participant_ids": [participant.id for participant in participants],
        })
        self.post("api-admin-tournament-confirm-draw")
        self.post("api-admin-tournament-start")

        response = self.client.get(reverse("api-admin-dashboard"))

        self.assertEqual(response.status_code, 200, response.content)
        active = response.json()["active_tournaments"][0]
        self.assertEqual(active["round_completed_matches"], 0)
        self.assertEqual(active["round_total_matches"], 1)
        self.assertEqual(active["round_progress_percent"], 0)
        self.assertEqual(
            {active["next_match"]["player1"], active["next_match"]["player2"]},
            {participant.name for participant in participants},
        )

    def test_dashboard_exposes_upcoming_registration_readiness(self):
        participant = self.add_player(self.players[0])
        TournamentRegistration.objects.create(
            tournament=self.tournament,
            participant=participant,
            payment_status=TournamentRegistration.PAYMENT_UNPAID,
        )
        self.tournament.starts_at = timezone.now() + timedelta(days=1)
        self.tournament.entry_fee = 50
        self.tournament.save(update_fields=["starts_at", "entry_fee"])

        response = self.client.get(reverse("api-admin-dashboard"))

        self.assertEqual(response.status_code, 200, response.content)
        upcoming = response.json()["upcoming_tournaments"][0]
        self.assertEqual(upcoming["entry_fee"], "50.00")
        self.assertEqual(upcoming["registration_summary"], {
            "registered": 1,
            "checked_in": 0,
            "unpaid": 1,
            "waitlisted": 0,
            "attention": 1,
            "ready": 0,
        })

    def test_dashboard_exposes_recent_operational_activity(self):
        WalletTransaction.create_entry(
            user=self.players[0],
            amount=25,
            kind=WalletTransaction.KIND_DEPOSIT,
            actor=self.staff,
        )

        response = self.client.get(reverse("api-admin-dashboard"))

        self.assertEqual(response.status_code, 200, response.content)
        activity = response.json()["recent_activity"]
        self.assertEqual(activity[0]["kind"], "wallet")
        self.assertEqual(activity[0]["action"], "deposit")
        self.assertEqual(activity[0]["actor"], self.staff.username)
        self.assertEqual(activity[0]["subject"], self.players[0].username)
        self.assertNotIn("recent_users", response.json())
        self.assertNotIn("new_users", response.json()["kpis"])

    def test_reopening_registration_clears_an_unconfirmed_draw(self):
        for user in self.players[:2]:
            self.add_player(user)
        self.post("api-admin-tournament-close-registration")
        self.post("api-admin-tournament-draw")

        reopened = self.post("api-admin-tournament-reopen-registration")
        self.assertEqual(reopened.status_code, 200)
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.lifecycle_state, "registration_open")
        self.assertEqual(self.tournament.draw_order, [])
        self.assertIsNone(self.tournament.draw_generated_at)

    def test_registration_mutations_are_blocked_after_closing(self):
        for user in self.players[:2]:
            self.add_player(user)
        self.post("api-admin-tournament-close-registration")

        self.client.force_login(self.players[2])
        response = self.client.post(reverse("api-join", kwargs={"pk": self.tournament.pk}))
        self.assertEqual(response.status_code, 412)
        self.assertEqual(response.json()["detail"], "Registration is closed")

    def test_filling_capacity_closes_registration_without_starting(self):
        self.add_player(self.players[0])
        self.client.force_login(self.players[1])

        response = self.client.post(reverse("api-join", kwargs={"pk": self.tournament.pk}))

        self.assertEqual(response.status_code, 200, response.content)
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.lifecycle_state, "registration_closed")
        self.assertEqual(self.tournament.state, "open")
        self.assertFalse(Fixture.objects.filter(mode__tournament=self.tournament).exists())

    def test_draw_rejects_missing_players_and_changes_after_confirmation(self):
        participants = [self.add_player(user) for user in self.players[:2]]
        self.post("api-admin-tournament-close-registration")

        invalid = self.post("api-admin-tournament-draw", {"participant_ids": [participants[0].id]})
        self.assertEqual(invalid.status_code, 400)

        self.post("api-admin-tournament-draw")
        self.post("api-admin-tournament-confirm-draw")
        locked = self.post("api-admin-tournament-draw")
        self.assertEqual(locked.status_code, 412)

    def test_only_finished_results_can_be_confirmed(self):
        for user in self.players[:2]:
            self.add_player(user)
        response = self.post("api-admin-tournament-confirm-results")
        self.assertEqual(response.status_code, 412)

    def test_finished_results_receive_explicit_organizer_approval(self):
        for user in self.players[:2]:
            self.add_player(user)
        self.post("api-admin-tournament-close-registration")
        self.post("api-admin-tournament-draw")
        self.post("api-admin-tournament-confirm-draw")
        self.post("api-admin-tournament-start")
        fixture = Fixture.objects.get(mode__tournament=self.tournament)
        fixture.score = (1, 0)
        fixture.save()
        fixture.confirmations.add(*self.players[:2])
        self.tournament.update_state()
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.state, "finished")

        response = self.post("api-admin-tournament-confirm-results")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["lifecycle_state"], "results_confirmed")
        self.tournament.refresh_from_db()
        self.assertIsNotNone(self.tournament.results_confirmed_at)
