import json
import uuid
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings

from frontend.performance import player_performance
from gamelink.models import LinkedAccount


@override_settings(GAMELINK_ENABLED=True, GAMELINK_BACKGAMMON_URL="https://game.example", GAMELINK_ISSUER="tournaments")
class ProfilePerformanceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="profile-pr")

    def request(self):
        request = RequestFactory().get("/performance", {"sub": str(uuid.uuid4())})
        request.user = self.user
        return request

    @patch("frontend.performance.urlopen")
    def test_unlinked_player_has_no_analyses_without_creating_identity(self, remote):
        response = player_performance(self.request())
        self.assertEqual(json.loads(response.content), {"pr": None, "matches": 0, "decisions": 0})
        self.assertFalse(LinkedAccount.objects.filter(user=self.user).exists())
        remote.assert_not_called()

    @patch("frontend.performance.sign_command_body", return_value="test-signature")
    @patch("frontend.performance.urlopen")
    def test_profile_uses_session_identity_and_sends_signed_read(self, remote, sign):
        identity = LinkedAccount.objects.create(user=self.user)
        stream = MagicMock()
        stream.read.return_value = b'{"pr":"3.25","matches":4,"decisions":100}'
        remote.return_value.__enter__.return_value = stream
        response = player_performance(self.request())
        self.assertEqual(response.status_code, 200)
        outbound = remote.call_args.args[0]
        self.assertEqual(json.loads(outbound.data)["sub"], str(identity.external_id))
        self.assertEqual(outbound.get_header("X-gamelink-signature"), "test-signature")
        self.assertEqual(json.loads(response.content)["pr"], "3.25")
