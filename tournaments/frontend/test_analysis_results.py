import json
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase, RequestFactory
from .analysis_results import analysis_results


class AnalysisResultsTests(SimpleTestCase):
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
