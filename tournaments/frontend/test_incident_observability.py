from types import SimpleNamespace
from unittest.mock import patch

from django.db import OperationalError
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from tournaments.observability import IncidentDiagnosticsMiddleware, QueryDiagnostics, request_context


class IncidentObservabilityTests(SimpleTestCase):
    def test_failed_request_logs_correlation_without_query_credentials(self):
        request = RequestFactory().get('/api/gamelink/enter/?ticket=DO-NOT-LOG')
        with patch('tournaments.observability.incident_event') as event:
            middleware = IncidentDiagnosticsMiddleware(lambda _: HttpResponse(status=500))
            response = middleware(request)
        self.assertEqual(response['X-Request-ID'], request.request_id)
        self.assertEqual(len(request.request_id), 32)
        self.assertEqual(event.call_args.args[0], 'request_failed')
        self.assertIsNone(request_context.get())
        self.assertNotIn('DO-NOT-LOG', str(event.call_args_list))

    def test_lock_error_records_operation_without_sql_or_parameters(self):
        diagnostics = QueryDiagnostics()

        def failed(*args):
            raise OperationalError('database is locked')

        with patch('tournaments.observability.incident_event') as event:
            with self.assertRaises(OperationalError):
                diagnostics(failed, 'UPDATE auth_user SET password=%s', ['DO-NOT-LOG'], False,
                            {'connection': SimpleNamespace(alias='default')})
        self.assertEqual(event.call_args.args[0], 'db_lock_failed')
        self.assertEqual(event.call_args.kwargs['operation'], 'UPDATE')
        self.assertNotIn('DO-NOT-LOG', str(event.call_args_list))
        self.assertNotIn('auth_user', str(event.call_args_list))

    def test_fast_successful_request_adds_id_without_failure_noise(self):
        with patch('tournaments.observability.incident_event') as event:
            middleware = IncidentDiagnosticsMiddleware(lambda _: HttpResponse(status=200))
            event.reset_mock()
            response = middleware(RequestFactory().get('/api/tournaments'))
        self.assertIn('X-Request-ID', response)
        event.assert_not_called()
