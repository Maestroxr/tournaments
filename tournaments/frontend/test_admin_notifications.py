from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tournaments.models import Fixture, Participant, Participation, Tournament


DEFINITION = """
stages:
  - id: main
    name: Main round
    mode: knockout
podium:
  - main.placements[0]
  - main.placements[1]
"""


class AdminNotificationsTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="organizer", is_staff=True)
        self.regular_user = User.objects.create_user(username="viewer")
        self.client.force_login(self.staff)

    def create_tournament(self, name, *, published=True, min_players=2, starts_at=None):
        return Tournament.load(
            DEFINITION,
            name,
            creator=self.staff,
            published=published,
            min_players=min_players,
            starts_at=starts_at,
        )

    def add_player(self, tournament, suffix):
        user = User.objects.create_user(username=f"player-{suffix}")
        participant = Participant.get_or_create_for_user(user)
        Participation.objects.create(
            tournament=tournament,
            participant=participant,
            slot_id=Participation.next_slot_id(tournament),
        )

    def start_tournament(self, tournament, suffix):
        self.add_player(tournament, f"{suffix}-one")
        self.add_player(tournament, f"{suffix}-two")
        response = self.client.post(
            reverse("api-admin-tournament-start", kwargs={"pk": tournament.pk}),
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)

    def test_endpoint_is_staff_only(self):
        self.client.logout()
        anonymous = self.client.get(reverse("api-admin-notifications"))
        self.assertEqual(anonymous.status_code, 401)

        self.client.force_login(self.regular_user)
        non_staff = self.client.get(reverse("api-admin-notifications"))
        self.assertEqual(non_staff.status_code, 403)

    def test_returns_every_notification_while_dashboard_remains_capped(self):
        for index in range(10):
            self.create_tournament(f"Open {index}")

        response = self.client.get(reverse("api-admin-notifications"))
        dashboard = self.client.get(reverse("api-admin-dashboard"))

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["total"], 10)
        self.assertEqual(len(payload["notifications"]), 10)
        self.assertEqual(payload["counts"], {
            "critical": 0,
            "warning": 10,
            "info": 0,
        })
        self.assertTrue(payload["updated_at"])
        self.assertEqual(len(dashboard.json()["attention"]), 8)

    def test_returns_all_drafts_while_dashboard_preserves_three_draft_limit(self):
        drafts = [
            self.create_tournament(f"Draft {index}", published=False)
            for index in range(5)
        ]

        response = self.client.get(reverse("api-admin-notifications"))
        dashboard = self.client.get(reverse("api-admin-dashboard"))

        notifications = response.json()["notifications"]
        draft_notifications = [item for item in notifications if item["kind"] == "draft"]
        dashboard_drafts = [
            item for item in dashboard.json()["attention"]
            if item["kind"] == "draft"
        ]
        self.assertCountEqual(
            [item["id"] for item in draft_notifications],
            [tournament.id for tournament in drafts],
        )
        self.assertEqual(len(draft_notifications), 5)
        self.assertEqual(len(dashboard_drafts), 3)

    def test_orders_notifications_and_gives_each_one_a_stable_id(self):
        overdue = self.create_tournament(
            "Overdue",
            starts_at=timezone.now() - timedelta(hours=1),
        )
        waiting_one = self.create_tournament("Waiting one")
        waiting_two = self.create_tournament("Waiting two")
        ready = self.create_tournament("Ready", min_players=1)
        self.add_player(ready, "ready")
        draft = self.create_tournament("Draft", published=False)

        response = self.client.get(reverse("api-admin-notifications"))

        self.assertEqual(response.status_code, 200, response.content)
        notifications = response.json()["notifications"]
        self.assertEqual(
            [item["severity"] for item in notifications],
            ["critical", "warning", "warning", "info", "info"],
        )
        warning_ids = [
            item["id"] for item in notifications
            if item["severity"] == "warning"
        ]
        self.assertEqual(warning_ids, sorted([waiting_one.id, waiting_two.id]))
        expected_kinds = {
            overdue.id: "overdue",
            waiting_one.id: "waiting_players",
            waiting_two.id: "waiting_players",
            ready.id: "ready_to_start",
            draft.id: "draft",
        }
        for item in notifications:
            self.assertEqual(item["kind"], expected_kinds[item["id"]])
            self.assertEqual(
                item["notification_id"],
                f"{item['kind']}:{item['id']}",
            )

    def test_includes_pending_active_tournaments_and_excludes_finished_ones(self):
        active = self.create_tournament("Active")
        self.start_tournament(active, "active")
        finished = self.create_tournament("Finished")
        self.start_tournament(finished, "finished")
        fixture = Fixture.objects.get(mode__tournament=finished)
        fixture.score = (1, 0)
        fixture.auto_confirmed = True
        fixture.save()
        finished.update_state()
        self.assertEqual(finished.state, "finished")

        response = self.client.get(reverse("api-admin-notifications"))

        self.assertEqual(response.status_code, 200, response.content)
        notifications = response.json()["notifications"]
        active_notification = next(
            item for item in notifications if item["id"] == active.id
        )
        self.assertEqual(active_notification["kind"], "pending_matches")
        self.assertEqual(active_notification["pending_matches"], 1)
        self.assertFalse(any(item["id"] == finished.id for item in notifications))
