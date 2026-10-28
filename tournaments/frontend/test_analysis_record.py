import json
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

from django.test import RequestFactory, SimpleTestCase

from .analysis_results import analysis_record


class AnalysisRecordTests(SimpleTestCase):
    def setUp(self):
        self.room_id = "11111111-1111-1111-1111-111111111111"
        self.analysis_id = "44444444-4444-4444-4444-444444444444"
        self.url = f"/api/analyses/{self.analysis_id}/record"
        self.request = RequestFactory().get(self.url, {"room": self.room_id})
        self.request.user = SimpleNamespace(is_authenticated=True, is_staff=False)

    @patch("frontend.analysis_results.allowed_rooms", return_value={"11111111-1111-1111-1111-111111111111"})
    @patch("frontend.analysis_results.read_results")
    def test_authorized_room_is_forwarded_without_loading_analysis_detail(self, read, rooms):
        read.return_value = {"id": self.analysis_id, "room_id": self.room_id, "games": [{"events": []}]}
        response = analysis_record(self.request, self.analysis_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), read.return_value)
        read.assert_called_once_with(f"{self.analysis_id}/record/", [("room", self.room_id)])
        self.assertEqual(response["Cache-Control"], "private, no-store")

    @patch("frontend.analysis_results.allowed_rooms", return_value=set())
    @patch("frontend.analysis_results.read_results")
    def test_forbidden_room_is_rejected_before_loading_record(self, read, rooms):
        response = analysis_record(self.request, self.analysis_id)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        read.assert_not_called()

    @patch("frontend.analysis_results.allowed_rooms")
    @patch("frontend.analysis_results.read_results")
    def test_missing_room_and_anonymous_never_contact_provider(self, read, rooms):
        self.request.GET = {}
        self.assertEqual(analysis_record(self.request, self.analysis_id).status_code, 404)
        self.request.user.is_authenticated = False
        self.assertEqual(analysis_record(self.request, self.analysis_id).status_code, 401)
        self.request.user.is_authenticated = True
        self.request.GET = {"room": "invalid"}
        self.assertEqual(analysis_record(self.request, self.analysis_id).status_code, 404)
        read.assert_not_called()
        rooms.assert_not_called()

    @patch("frontend.analysis_results.allowed_rooms", return_value={"11111111-1111-1111-1111-111111111111"})
    @patch("frontend.analysis_results.read_results")
    def test_unrelated_provider_record_is_not_returned(self, read, rooms):
        for data in (
            {"id": self.analysis_id, "room_id": "other", "games": ["private"]},
            {"id": "other", "room_id": self.room_id, "games": ["private"]},
        ):
            read.return_value = data
            response = analysis_record(self.request, self.analysis_id)
            self.assertEqual(response.status_code, 404)
            self.assertNotIn("private", response.content.decode())

    @patch("frontend.analysis_results.allowed_rooms")
    @patch("frontend.analysis_results.read_results")
    def test_staff_may_read_without_room_and_browser_staff_query_is_ignored(self, read, rooms):
        self.request.user.is_staff = True
        self.request.GET = {}
        read.return_value = {"id": self.analysis_id, "room_id": None, "games": []}
        self.assertEqual(analysis_record(self.request, self.analysis_id).status_code, 200)
        read.assert_called_once_with(f"{self.analysis_id}/record/", [("staff", "1")])
        rooms.assert_not_called()
        read.reset_mock()
        self.request.user.is_staff = False
        self.request.GET = {"staff": "1"}
        self.assertEqual(analysis_record(self.request, self.analysis_id).status_code, 404)
        read.assert_not_called()

    @patch("frontend.analysis_results.allowed_rooms", return_value={"11111111-1111-1111-1111-111111111111"})
    @patch("frontend.analysis_results.read_results")
    def test_missing_or_unavailable_provider_does_not_return_partial_record(self, read, rooms):
        read.side_effect = HTTPError("http://analysis.invalid", 404, "missing", {}, None)
        self.assertEqual(analysis_record(self.request, self.analysis_id).status_code, 404)
        read.side_effect = TimeoutError()
        response = analysis_record(self.request, self.analysis_id)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Cache-Control"], "private, no-store")
