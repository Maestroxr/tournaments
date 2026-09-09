from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from tournaments.models import WalletTransaction
from tournaments.models import UserContact


class AdminUserCreationTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="organizer", is_staff=True)
        self.client.force_login(self.staff)
        self.url = reverse("api-admin-users")

    def test_creates_user_with_opening_balance(self):
        response = self.client.post(
            self.url,
            {
                "username": "newplayer",
                "phone_number": "050-123-4567",
                "password1": "Strong!Pass42",
                "password2": "Strong!Pass42",
                "initial_balance": "75.50",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        player = User.objects.get(username="newplayer")
        self.assertEqual(WalletTransaction.balance_for_user(player), Decimal("75.50"))
        transaction = player.wallet_transactions.get()
        self.assertEqual(transaction.kind, WalletTransaction.KIND_DEPOSIT)
        self.assertEqual(transaction.actor, self.staff)
        self.assertEqual(Decimal(response.json()["balance"]), Decimal("75.50"))
        self.assertEqual(response.json()["phone_number"], "050-123-4567")

    def test_rejects_negative_opening_balance_without_creating_user(self):
        response = self.client.post(
            self.url,
            {
                "username": "new-player",
                "password1": "Strong!Pass42",
                "password2": "Strong!Pass42",
                "initial_balance": "-1",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("initial_balance", response.json()["errors"])
        self.assertFalse(User.objects.filter(username="new-player").exists())

    def test_rejects_username_with_non_alphanumeric_characters(self):
        response = self.client.post(
            self.url,
            {
                "username": "new_player",
                "password1": "Strong!Pass42",
                "password2": "Strong!Pass42",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("username", response.json()["errors"])
        self.assertFalse(User.objects.filter(username="new_player").exists())

    def test_rejects_invalid_phone_number(self):
        response = self.client.post(
            self.url,
            {
                "username": "newplayer",
                "phone_number": "not-a-phone",
                "password1": "Strong!Pass42",
                "password2": "Strong!Pass42",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("phone_number", response.json()["errors"])
        self.assertFalse(User.objects.filter(username="newplayer").exists())

    def test_updates_username_and_phone_with_the_same_validation(self):
        player = User.objects.create_user(username="player1")
        response = self.client.put(
            reverse("api-admin-user-detail", kwargs={"pk": player.pk}),
            {
                "username": "player2",
                "phone_number": "+972 50-123-4567",
                "is_staff": False,
                "is_active": True,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        player.refresh_from_db()
        self.assertEqual(player.username, "player2")
        self.assertEqual(player.contact.phone_number, "+972 50-123-4567")

    def test_rejects_weak_password_when_editing_user(self):
        player = User.objects.create_user(username="maayan")
        UserContact.objects.create(user=player, phone_number="050-123-4567")
        response = self.client.put(
            reverse("api-admin-user-detail", kwargs={"pk": player.pk}),
            {
                "username": "maayan",
                "new_password": "maayan12345",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("new_password", response.json()["errors"])
