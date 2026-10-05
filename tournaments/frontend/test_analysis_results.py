import json
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase, RequestFactory, TestCase
from .analysis_results import analysis_results


class AnalysisAvailabilityTests(SimpleTestCase):
    def test_missing_configuration_stops_automatic_polling(self):
        from .analysis_results import AnalysisUnavailable
        request = RequestFactory().get('/api/analyses', {'room': 'mine'})
        request.user = SimpleNamespace(is_authenticated=True, is_staff=False)
        with patch('frontend.analysis_results.allowed_rooms', return_value={'mine'}), patch(
                'frontend.analysis_results.read_results', side_effect=AnalysisUnavailable('analysis_not_configured', retryable=False)):
            response = analysis_results(request)
        self.assertEqual(response.status_code, 503)
        self.assertFalse(json.loads(response.content)['retryable'])
        self.assertEqual(response['Retry-After'], '30')

    def test_provider_failure_opens_short_circuit_without_caching_private_data(self):
        from urllib.error import URLError
        from django.test import override_settings
        from .analysis_results import AnalysisUnavailable, read_results, _unavailable_until
        _unavailable_until.clear()
        try:
            with override_settings(ANALYSIS_API_TOKEN='isolated-token', ANALYSIS_SERVICE_URL='http://analysis.invalid'), patch(
                    'frontend.analysis_results.urlopen', side_effect=URLError('offline')) as remote:
                with self.assertRaises(URLError):
                    read_results('', [('room', 'one')])
                with self.assertRaises(AnalysisUnavailable):
                    read_results('', [('room', 'two')])
                self.assertEqual(remote.call_count, 1)
        finally:
            _unavailable_until.clear()


class PracticeAnalysisOwnershipTests(TestCase):
    def test_only_own_prepared_ai_rooms_are_visible(self):
        import uuid
        from django.contrib.auth import get_user_model
        from gamelink.models import PracticePurchase
        from .analysis_results import allowed_rooms
        owner = get_user_model().objects.create_user(username='ai-analysis-owner')
        other = get_user_model().objects.create_user(username='ai-analysis-other')
        room_id = uuid.uuid4()
        PracticePurchase.objects.create(user=owner, room_id=room_id, options={}, fee=50, paid=True)
        PracticePurchase.objects.create(user=owner, options={}, fee=50)
        self.assertIn(str(room_id), allowed_rooms(owner))
        self.assertNotIn(str(room_id), allowed_rooms(other))
        self.assertNotIn('None', allowed_rooms(owner))


class AnalysisResultsTests(SimpleTestCase):
    @patch('frontend.analysis_results.allowed_rooms', return_value={'mine'})
    @patch('frontend.analysis_results.read_results')
    def test_reanalysis_checks_ownership_before_posting(self, read, rooms):
        request = RequestFactory().post('/api/analyses/id', {'eval_level': '2ply'}, content_type='application/json')
        request.user = SimpleNamespace(is_authenticated=True, is_staff=False)
        read.return_value = {'room_id': 'other'}
        self.assertEqual(analysis_results(request, 'id').status_code, 404)
        read.assert_called_once_with('id/')

    @patch('frontend.analysis_results.allowed_rooms', return_value={'mine'})
    @patch('frontend.analysis_results.read_results')
    def test_reanalysis_forwards_validated_depth(self, read, rooms):
        request = RequestFactory().post('/api/analyses/id', {'eval_level': '2ply'}, content_type='application/json')
        request.user = SimpleNamespace(is_authenticated=True, is_staff=False)
        read.side_effect = [{'room_id': 'mine'}, {'status': 'pending', 'eval_level': '2ply'}]
        self.assertEqual(analysis_results(request, 'id').status_code, 202)
        read.assert_called_with('id/', payload={'eval_level': '2ply'})

    def setUp(self):
        self.request = RequestFactory().get('/api/analyses')
        self.request.user = SimpleNamespace(is_authenticated=True, is_staff=False)

    def test_anonymous_rejected(self):
        self.request.user.is_authenticated = False
        self.assertEqual(analysis_results(self.request).status_code, 401)

    @patch('frontend.analysis_results.allowed_rooms', return_value={'mine'})
    @patch('frontend.analysis_results.read_results')
    def test_unrelated_match_cannot_be_read(self, read, rooms):
        read.return_value = {'room_id': 'someone-else', 'games': ['private']}
        response = analysis_results(self.request, 'analysis-id')
        self.assertEqual(response.status_code, 404)
        self.assertNotIn('private', response.content.decode())

    @patch('frontend.analysis_results.allowed_rooms', return_value={'mine'})
    @patch('frontend.analysis_results.read_results')
    def test_list_is_filtered_and_uncached(self, read, rooms):
        read.return_value = {'matches': [{'id': 'a', 'room_id': 'mine'}, {'id': 'b', 'room_id': 'other'}]}
        response = analysis_results(self.request)
        self.assertEqual(json.loads(response.content)['matches'], [{'id': 'a', 'room_id': 'mine'}])
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        read.assert_called_once_with('', [('room', 'mine')])

    @patch('frontend.analysis_results.allowed_rooms', return_value={'mine'})
    @patch('frontend.analysis_results.read_results', side_effect=TimeoutError)
    def test_service_failure_is_recoverable(self, read, rooms):
        self.assertEqual(analysis_results(self.request).status_code, 503)

    @patch('frontend.analysis_results.allowed_rooms', return_value=set())
    @patch('frontend.analysis_results.read_results')
    def test_no_rooms_does_not_request_all_matches(self, read, rooms):
        self.assertEqual(json.loads(analysis_results(self.request).content), {'matches': []})
        read.assert_not_called()

    @patch('frontend.analysis_results.allowed_rooms', return_value={'mine', 'another'})
    @patch('frontend.analysis_results.read_results')
    def test_room_link_filters_before_results_limit(self, read, rooms):
        self.request.GET = {'room': 'mine'}
        read.return_value = {'matches': [{'id': 'a', 'room_id': 'mine'}, {'id': 'b', 'room_id': 'another'}]}
        response = analysis_results(self.request)
        read.assert_called_once_with('', [('room', 'mine')])
        self.assertEqual(json.loads(response.content)['matches'], [{'id': 'a', 'room_id': 'mine'}])

    @patch('frontend.analysis_results.allowed_rooms', return_value={'mine'})
    @patch('frontend.analysis_results.read_results')
    def test_unrelated_room_link_is_rejected(self, read, rooms):
        self.request.GET = {'room': 'other'}
        self.assertEqual(analysis_results(self.request).status_code, 404)
        read.assert_not_called()
