import base64
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from tournaments.models import Fixture, Knockout, Participant, Tournament, UserContact
from .models import PushDelivery, PushSubscription
from .push import deliver_pending, discover_ready_matches, send_notification


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


@override_settings(WEB_PUSH_PUBLIC_KEY='test-public', WEB_PUSH_PRIVATE_KEY='test-private', WEB_PUSH_SUBJECT='mailto:operator@example.com', GAMELINK_ENABLED=True)
class PushTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='push-player')
        self.other = User.objects.create_user(username='opponent')
        UserContact.objects.create(user=self.user, phone_number='0501234567')
        UserContact.objects.create(user=self.other, phone_number='0507654321')
        self.client.force_login(self.user)
        self.info = {'endpoint': 'https://fcm.googleapis.com/fcm/send/test-token',
                     'keys': {'p256dh': b64(b'\x04' + b'k' * 64), 'auth': b64(b'a' * 16)}}
        self.tournament = Tournament.objects.create(name='Push cup', published=True, podium_spec=[])
        self.mode = Knockout.objects.create(tournament=self.tournament)
        self.fixture = Fixture.objects.create(mode=self.mode, level=0,
            player1=Participant.create_for_user(self.user), player2=Participant.create_for_user(self.other))

    def subscribe(self):
        response = self.client.post('/api/push/subscription', self.info, content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        return PushSubscription.objects.get(user=self.user)

    def test_authentication_and_csrf_are_required(self):
        self.assertEqual(Client().get('/api/push/config').status_code, 401)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post('/api/push/subscription', self.info, content_type='application/json').status_code, 403)

    def test_subscribe_is_idempotent_and_delete_checks_owner(self):
        self.subscribe()
        self.subscribe()
        self.assertEqual(PushSubscription.objects.count(), 1)
        self.client.force_login(self.other)
        self.client.delete('/api/push/subscription', self.info, content_type='application/json')
        self.assertEqual(PushSubscription.objects.count(), 1)
        self.client.force_login(self.user)
        self.client.delete('/api/push/subscription', self.info, content_type='application/json')
        self.assertEqual(PushSubscription.objects.count(), 0)

    def test_rejects_untrusted_endpoints_and_invalid_keys(self):
        for endpoint in ('http://fcm.googleapis.com/test', 'https://127.0.0.1/push',
                         'https://fcm.googleapis.com.evil.test/push', 'https://user@fcm.googleapis.com/push'):
            self.info['endpoint'] = endpoint
            self.assertEqual(self.client.post('/api/push/subscription', self.info, content_type='application/json').status_code, 400)
        self.info['endpoint'] = 'https://fcm.googleapis.com/push'
        self.info['keys']['auth'] = 'invalid'
        self.assertEqual(self.client.post('/api/push/subscription', self.info, content_type='application/json').status_code, 400)
        self.assertFalse(PushSubscription.objects.exists())

    @override_settings(WEB_PUSH_PRIVATE_KEY='')
    def test_unconfigured_service_does_not_claim_to_enable_push(self):
        self.assertFalse(self.client.get('/api/push/config').json()['enabled'])
        self.assertEqual(self.client.post('/api/push/subscription', self.info, content_type='application/json').status_code, 503)

    @patch('frontend.push.send_notification')
    def test_worker_discovers_and_sends_once_without_browser_polling(self, send):
        self.subscribe()
        self.assertEqual(discover_ready_matches(), 1)
        self.assertEqual(discover_ready_matches(), 0)
        self.assertEqual(deliver_pending(), 1)
        self.assertEqual(deliver_pending(), 0)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[1]['tag'], f'match-ready:{self.fixture.pk}')

    @patch('frontend.push.send_notification')
    def test_transient_failure_retries_and_finished_fixture_is_discarded(self, send):
        self.subscribe()
        discover_ready_matches()
        send.side_effect = OSError('temporary')
        self.assertEqual(deliver_pending(), 0)
        delivery = PushDelivery.objects.get()
        self.assertEqual(delivery.attempts, 1)
        self.assertIsNone(delivery.delivered_at)
        send.side_effect = None
        PushDelivery.objects.update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        self.fixture.auto_confirmed = True
        self.fixture.score1, self.fixture.score2 = 5, 0
        self.fixture.save()
        self.assertEqual(deliver_pending(), 0)
        delivery.refresh_from_db()
        self.assertIsNotNone(delivery.discarded_at)

    def test_expired_provider_subscription_is_removed(self):
        self.subscribe()
        discover_ready_matches()
        class Expired(Exception):
            response = type('Response', (), {'status_code': 410})()
        with patch('frontend.push.send_notification', side_effect=Expired()):
            self.assertEqual(deliver_pending(), 0)
        self.assertFalse(PushSubscription.objects.exists())

    def test_provider_encrypts_without_following_redirects(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from requests import Response
        key = ec.generate_private_key(ec.SECP256R1())
        public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        private = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        self.info['keys']['p256dh'] = b64(public)
        device = self.subscribe()
        response = Response()
        response.status_code = 201
        with override_settings(WEB_PUSH_PRIVATE_KEY=b64(private)), patch('requests.Session.request', return_value=response) as request:
            send_notification(device, {'title': 'Test', 'body': 'Match ready'})
        self.assertFalse(request.call_args.kwargs['allow_redirects'])
        self.assertIsInstance(request.call_args.kwargs['data'], bytes)
        self.assertNotIn(b'Match ready', request.call_args.kwargs['data'])
