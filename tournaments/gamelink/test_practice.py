from urllib.parse import urlparse, parse_qs

from django.contrib.auth.models import User, AnonymousUser
from django.core import signing
from django.test import TestCase, RequestFactory, override_settings

from gamelink.practice import StartPracticeView


class PracticeEntryTests(TestCase):
    @override_settings(GAMELINK_ENABLED=True, GAMELINK_BACKGAMMON_URL='https://game.example',
        GAMELINK_TICKET_SECRET='practice-test-secret', GAMELINK_ISSUER='club', GAMELINK_AUDIENCE='game')
    def test_issue_scoped_ticket_and_reject_unknown_difficulty(self):
        user = User.objects.create_user('practice-test-user')
        request = RequestFactory().post('/t/practice/play', {'difficulty': 'medium'})
        request.user = user
        response = StartPracticeView.as_view()(request)
        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response['Location'])
        self.assertEqual(parsed.path, '/api/link/practice/')
        ticket = parse_qs(parsed.query)['ticket'][0]
        data = signing.loads(ticket, key='practice-test-secret', salt='gamelink.practice.v1')
        self.assertEqual(data['difficulty'], 'medium')
        self.assertEqual(data['aud'], 'game')
        self.assertNotIn('fix', data)
        request.POST = {'difficulty': 'invalid'}
        self.assertEqual(StartPracticeView.as_view()(request).status_code, 400)

    def test_login_required(self):
        request = RequestFactory().post('/t/practice/play')
        request.user = AnonymousUser()
        self.assertEqual(StartPracticeView.as_view()(request).status_code, 302)
