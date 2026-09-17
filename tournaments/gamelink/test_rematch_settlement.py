from django.test import TestCase, RequestFactory, override_settings
from django.contrib.auth.models import User
from tournaments.models import HeadToHeadTable
from tournaments.gamelink.views import RematchCallbackView
from tournaments.gamelink.signing import sign_result_body
import json, time, uuid

def _signed_request(factory, body, secret="test-secret"):
    raw = json.dumps(body, separators=(',',':'), sort_keys=True).encode()
    ts = str(int(time.time()))
    nonce = uuid.uuid4().hex
    from django.conf import settings
    sig = sign_result_body(raw, ts, nonce)
    req = factory.post('/api/gamelink/rematch/', data=raw, content_type='application/json',
                       HTTP_X_GAMELINK_TIMESTAMP=ts, HTTP_X_GAMELINK_NONCE=nonce,
                       HTTP_X_GAMELINK_SIGNATURE=sig, HTTP_X_GAMELINK_ISSUER=settings.GAMELINK_ISSUER)
    return req

@override_settings(GAMELINK_ENABLED=True, GAMELINK_TOURNAMENTS_URL="http://test", GAMELINK_ISSUER="test", GAMELINK_MAX_BODY=100000, GAMELINK_CLOCK_SKEW=300)
class RematchSettlementTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.view = RematchCallbackView.as_view()
        self.host = User.objects.create_user(username="host", password="x")
        self.guest = User.objects.create_user(username="guest", password="x")

    def _make_table(self, status, room_id, guest=None):
        from decimal import Decimal
        t = HeadToHeadTable.objects.create(
            host=self.host, guest=guest, status=status,
            external_room_id=room_id, amount=Decimal("10"), game_format="money",
            rules_snapshot={}, code="T123"
        )
        return t

    def test_incomplete_source_returns_source_not_settled(self):
        table = self._make_table(HeadToHeadTable.STATUS_PLAYING, "room-1", guest=self.guest)
        body = {"v":1, "action":"request", "source_table_id": table.pk, "room_id":"room-1", "actor_seat":"p1"}
        req = _signed_request(self.factory, body)
        resp = self.view(req)
        data = json.loads(resp.content)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(data["code"], "source_not_settled")

    def test_completed_without_guest_returns_invalid_source(self):
        table = self._make_table(HeadToHeadTable.STATUS_COMPLETED, "room-2", guest=None)
        body = {"v":1, "action":"request", "source_table_id": table.pk, "room_id":"room-2", "actor_seat":"p1"}
        req = _signed_request(self.factory, body)
        resp = self.view(req)
        data = json.loads(resp.content)
        self.assertEqual(data["code"], "invalid_source")

    def test_room_mismatch_returns_source_room_mismatch(self):
        table = self._make_table(HeadToHeadTable.STATUS_COMPLETED, "room-real", guest=self.guest)
        body = {"v":1, "action":"request", "source_table_id": table.pk, "room_id":"room-other", "actor_seat":"p1"}
        req = _signed_request(self.factory, body)
        resp = self.view(req)
        data = json.loads(resp.content)
        self.assertEqual(data["code"], "source_room_mismatch")
