from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from tournaments.models import (
    Participant, Tournament, TournamentRegistration, WalletTransaction,
)


class AdminFinanceTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="finance-admin", is_staff=True)
        self.player = User.objects.create_user(username="player")
        self.tournament = Tournament.objects.create(
            name="Finance Cup",
            podium_spec=[],
            entry_fee=Decimal("50.00"),
        )
        self.participant = Participant.get_or_create_for_user(self.player)
        TournamentRegistration.objects.create(
            tournament=self.tournament,
            participant=self.participant,
            payment_status=TournamentRegistration.PAYMENT_UNPAID,
        )
        WalletTransaction.create_entry(
            user=self.player,
            amount=Decimal("200.00"),
            kind=WalletTransaction.KIND_DEPOSIT,
            actor=self.staff,
        )
        WalletTransaction.create_entry(
            user=self.player,
            amount=Decimal("-100.00"),
            kind=WalletTransaction.KIND_TOURNAMENT_ENTRY,
            tournament=self.tournament,
            actor=self.staff,
        )
        WalletTransaction.create_entry(
            user=self.player,
            amount=Decimal("20.00"),
            kind=WalletTransaction.KIND_TOURNAMENT_REFUND,
            tournament=self.tournament,
            actor=self.staff,
        )
        WalletTransaction.create_entry(
            user=self.player,
            amount=Decimal("30.00"),
            kind=WalletTransaction.KIND_TOURNAMENT_PRIZE,
            tournament=self.tournament,
            actor=self.staff,
        )
        self.client.force_login(self.staff)

    def test_finance_summary_excludes_wallet_cash_flow(self):
        response = self.client.get(reverse("api-admin-finance"), {"days": 0})

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["summary"], {
            "revenue": "100.00",
            "refunds": "20.00",
            "prizes": "30.00",
            "expenses": "50.00",
            "net": "50.00",
            "outstanding": "50.00",
            "outstanding_count": 1,
        })
        self.assertEqual(payload["tournaments"][0]["name"], "Finance Cup")
        self.assertEqual(payload["tournaments"][0]["net"], "50.00")
        self.assertEqual(payload["trend"][0]["net"], "50.00")

    def test_dashboard_exposes_the_thirty_day_finance_summary(self):
        response = self.client.get(reverse("api-admin-dashboard"))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["finance"], {
            "revenue": "100.00",
            "refunds": "20.00",
            "prizes": "30.00",
            "expenses": "50.00",
            "net": "50.00",
            "outstanding": "50.00",
            "outstanding_count": 1,
        })

    def test_finance_ignores_tournament_entries_with_an_invalid_sign(self):
        WalletTransaction.create_entry(
            user=self.player,
            amount=Decimal("5.00"),
            kind=WalletTransaction.KIND_TOURNAMENT_ENTRY,
            tournament=self.tournament,
            actor=self.staff,
        )

        payload = self.client.get(
            reverse("api-admin-finance"), {"days": 0},
        ).json()

        self.assertEqual(payload["summary"]["revenue"], "100.00")
        self.assertEqual(payload["ignored_transactions"], 1)

    def test_finance_rejects_an_invalid_range(self):
        response = self.client.get(reverse("api-admin-finance"), {"days": 8})
        self.assertEqual(response.status_code, 400)

    def test_finance_requires_staff(self):
        self.client.force_login(self.player)
        response = self.client.get(reverse("api-admin-finance"))
        self.assertEqual(response.status_code, 403)
