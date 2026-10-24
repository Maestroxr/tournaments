import json
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from django.test import RequestFactory, SimpleTestCase, override_settings

from .analysis_results import analysis_results, scoped_results


@override_settings(SECRET_KEY="scope-bridge-tests")
class AnalysisScopeBridgeTests(SimpleTestCase):
    def request(self):
        request = RequestFactory().get("/api/analyses", {"limit": 5, "offset": 5})
        request.user = SimpleNamespace(is_authenticated=True, is_staff=False, pk=17)
        request.session = SimpleNamespace(session_key="session-one")
        return request

    def test_large_history_uses_bounded_chunks_finalization_and_single_filtered_page(self):
        rooms = {str(uuid.uuid4()) for _ in range(1100)}
        scope_id = str(uuid.uuid4())
        calls = []
        def service(path, params=None, **kwargs):
            calls.append((path, params, kwargs))
            if path == "scopes/":
                return {"id": scope_id}
            if not path:
                return {"matches": [{"id": "six", "room_id": next(iter(rooms))}], "count": 12, "next_offset": 10}
            return {}
        with patch("frontend.analysis_results.allowed_rooms", return_value=rooms), patch(
            "frontend.analysis_results.read_results", side_effect=service,
        ):
            response = analysis_results(self.request())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["count"], 12)
        self.assertEqual(json.loads(response.content)["next_offset"], 10)
        chunks = [kwargs["payload"] for _, _, kwargs in calls if "rooms" in kwargs.get("payload", {})]
        self.assertEqual(sum(len(chunk["rooms"]) for chunk in chunks), 1100)
        self.assertTrue(all(len(chunk["rooms"]) <= 128 for chunk in chunks))
        self.assertTrue(all(len(json.dumps(chunk).encode()) < 8192 for chunk in chunks))
        self.assertEqual([chunk["offset"] for chunk in chunks], list(range(0, 1100, 128)))
        self.assertEqual(calls[-3][2]["payload"], {"finalize": True})
        self.assertEqual(calls[-2][1], [("scope", scope_id), ("limit", 5), ("offset", 5)])
        self.assertEqual(calls[-1][2]["method"], "DELETE")
        self.assertEqual(len({kwargs["headers"]["X-Analysis-Scope-Binding"] for _, _, kwargs in calls}), 1)
        self.assertNotIn(scope_id, response.content.decode())

    def test_binding_changes_with_request_session_and_user(self):
        bindings = []
        def service(path, params=None, **kwargs):
            if path == "scopes/":
                bindings.append(kwargs["headers"]["X-Analysis-Scope-Binding"])
                return {"id": str(uuid.uuid4())}
            return {"matches": [], "count": 0, "next_offset": None} if not path else {}
        request = self.request()
        with patch("frontend.analysis_results.read_results", side_effect=service):
            scoped_results(request, {str(uuid.uuid4())}, limit=5, offset=0)
            scoped_results(request, {str(uuid.uuid4())}, limit=5, offset=0)
            request.session.session_key = "session-two"
            request.user.pk = 18
            scoped_results(request, {str(uuid.uuid4())}, limit=5, offset=0)
        self.assertEqual(len(set(bindings)), 3)

    def test_failed_upload_is_not_queried_and_cleanup_is_attempted(self):
        calls = []
        scope_id = str(uuid.uuid4())
        def service(path, params=None, **kwargs):
            calls.append((path, kwargs))
            if path == "scopes/":
                return {"id": scope_id}
            if "rooms" in kwargs.get("payload", {}):
                raise TimeoutError()
            return {}
        with patch("frontend.analysis_results.read_results", side_effect=service):
            with self.assertRaises(TimeoutError):
                scoped_results(self.request(), {str(uuid.uuid4())}, limit=5, offset=0)
        self.assertFalse(any(path == "" for path, _ in calls))
        self.assertEqual(calls[-1], (f"scopes/{scope_id}/", {
            "headers": calls[0][1]["headers"], "method": "DELETE",
        }))

    def test_new_request_rebuilds_scope_from_current_authorization(self):
        first_rooms = {str(uuid.uuid4()) for _ in range(40)}
        second_rooms = {str(uuid.uuid4()) for _ in range(40)}
        uploaded = []
        def service(path, params=None, **kwargs):
            if path == "scopes/":
                return {"id": str(uuid.uuid4())}
            if "rooms" in kwargs.get("payload", {}):
                uploaded.append(set(kwargs["payload"]["rooms"]))
            return {"matches": [], "count": 0, "next_offset": None} if not path else {}
        with patch("frontend.analysis_results.allowed_rooms", side_effect=[first_rooms, second_rooms]), patch(
            "frontend.analysis_results.read_results", side_effect=service,
        ):
            self.assertEqual(analysis_results(self.request()).status_code, 200)
            self.assertEqual(analysis_results(self.request()).status_code, 200)
        self.assertEqual(uploaded, [first_rooms, second_rooms])
