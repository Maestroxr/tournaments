import base64
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from tournaments.models import Fixture, HeadToHeadTable, Knockout, Participant, Tournament, UserContact
from .models import PushDelivery, PushSubscription, TablePushDelivery
from .push import deliver_pending, discover_ready_matches, queue_guest_joined_push, queue_host_entered_push, send_notification


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

    def test_switching_account_clears_both_notification_queues(self):
        device = self.subscribe()
        table = self.ready_table()
        PushDelivery.objects.create(subscription=device, fixture=self.fixture, next_attempt_at=timezone.now())
        TablePushDelivery.objects.create(subscription=device, table=table, kind='guest_joined', next_attempt_at=timezone.now())
        self.client.force_login(self.other)
        response = self.client.post('/api/push/subscription', self.info, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PushDelivery.objects.filter(subscription=device).exists())
        self.assertFalse(TablePushDelivery.objects.filter(subscription=device).exists())

    def ready_table(self):
        return HeadToHeadTable.objects.create(
            code='PUSH01',
            mode=HeadToHeadTable.MODE_MATCH,
            host=self.user,
            guest=self.other,
            amount='100.00',
            fee_percent='5.00',
            fee_per_player='5.00',
            target_points=5,
            time_control='normal',
            status=HeadToHeadTable.STATUS_READY,
        )

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

    def test_accepts_apple_push_service_subdomains(self):
        for host in ('web.push.apple.com', 'region.push.apple.com'):
            with self.subTest(host=host):
                self.info['endpoint'] = f'https://{host}/test-token'
                response = self.client.post('/api/push/subscription', self.info, content_type='application/json')
                self.assertEqual(response.status_code, 200, response.content)
                self.assertTrue(PushSubscription.objects.filter(user=self.user, endpoint=self.info['endpoint']).exists())

    def test_apple_endpoint_allowlist_preserves_domain_and_transport_checks(self):
        for endpoint in (
            'https://web.push.apple.com.evil.test/push',
            'https://evilpush.apple.com/push',
            'https://not-apple.example/push',
            'http://web.push.apple.com/push',
            'https://user@web.push.apple.com/push',
            'https://web.push.apple.com:444/push',
            'https://web.push.apple.com/push#fragment',
        ):
            with self.subTest(endpoint=endpoint):
                self.info['endpoint'] = endpoint
                response = self.client.post('/api/push/subscription', self.info, content_type='application/json')
                self.assertEqual(response.status_code, 400, response.content)
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

    @patch('frontend.push.send_notification', side_effect=OSError('provider unavailable'))
    def test_provider_failure_is_reported_even_when_worker_is_alive(self, send):
        from .push_health import heartbeat
        self.subscribe()
        discover_ready_matches()
        queue_guest_joined_push(self.ready_table())
        heartbeat()
        for attempt in range(1, 6):
            for model in (PushDelivery, TablePushDelivery):
                model.objects.update(next_attempt_at=timezone.now() - timedelta(seconds=1))
            self.assertEqual(deliver_pending(), 0)
            for model in (PushDelivery, TablePushDelivery):
                delivery = model.objects.get()
                self.assertEqual(delivery.attempts, attempt)
                self.assertIsNotNone(delivery.last_failure_at)
                self.assertGreater(delivery.next_attempt_at, timezone.now())
            config = self.client.get('/api/push/config').json()
            self.assertTrue(config['deliveryAvailable'])
            self.assertEqual(config['recentDeliveryIssue'], 'failed' if attempt == 5 else 'retrying')
        self.assertEqual(send.call_count, 10)

    def test_expired_provider_subscription_is_removed(self):
        self.subscribe()
        discover_ready_matches()
        class Expired(Exception):
            response = type('Response', (), {'status_code': 410})()
        with patch('frontend.push.send_notification', side_effect=Expired()):
            self.assertEqual(deliver_pending(), 0)
        self.assertFalse(PushSubscription.objects.exists())

    @patch('frontend.push.send_notification')
    def test_guest_joined_push_is_queued_once_for_the_host_and_opens_my_games(self, send):
        table = self.ready_table()
        self.subscribe()
        self.assertEqual(queue_guest_joined_push(table), 1)
        self.assertEqual(queue_guest_joined_push(table), 0)
        self.assertEqual(deliver_pending(), 1)
        self.assertEqual(deliver_pending(), 0)
        payload = send.call_args.args[1]
        self.assertEqual(payload['tag'], f'table-guest-joined:{table.pk}')
        self.assertEqual(payload['url'], f'/tournaments/my-games?table={table.code}')

    @patch('frontend.push.send_notification')
    def test_host_entered_push_is_queued_once_for_the_guest(self, send):
        table = self.ready_table()
        self.client.force_login(self.other)
        guest_info = {**self.info, 'endpoint': 'https://fcm.googleapis.com/fcm/send/guest-token'}
        response = self.client.post('/api/push/subscription', guest_info, content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(queue_host_entered_push(table), 1)
        self.assertEqual(queue_host_entered_push(table), 0)
        self.assertEqual(deliver_pending(), 1)
        payload = send.call_args.args[1]
        self.assertEqual(payload['tag'], f'table-host-entered:{table.pk}')
        self.assertEqual(payload['url'], f'/tournaments/my-games?table={table.code}')

    def test_table_push_is_discarded_when_the_table_is_cancelled_before_delivery(self):
        table = self.ready_table()
        self.subscribe()
        queue_guest_joined_push(table)
        table.status = HeadToHeadTable.STATUS_CANCELLED
        table.save(update_fields=['status'])
        self.assertEqual(deliver_pending(), 0)
        self.assertIsNotNone(TablePushDelivery.objects.get().discarded_at)

    @override_settings(GAMELINK_BACKGAMMON_URL='https://game.example.com')
    @patch('gamelink.views.issue_direct_play_ticket', return_value=('test-ticket', None))
    @patch('frontend.push.send_notification')
    def test_guest_opening_game_notifies_host_once(self, send, ticket):
        table = self.ready_table()
        device = self.subscribe()
        self.client.force_login(self.other)
        for _ in range(2):
            response = self.client.post(f'/t/head-to-head/{table.code}/play')
            self.assertEqual(response.status_code, 302)
        delivery = TablePushDelivery.objects.get()
        self.assertEqual(delivery.subscription_id, device.pk)
        self.assertEqual(delivery.kind, TablePushDelivery.KIND_GUEST_ENTERED)
        self.assertEqual(deliver_pending(), 1)
        self.assertEqual(deliver_pending(), 0)
        self.assertEqual(send.call_args.args[1]['tag'], f'table-guest-entered:{table.pk}')

    @override_settings(GAMELINK_BACKGAMMON_URL='https://game.example.com')
    @patch('gamelink.views.issue_direct_play_ticket', return_value=('test-ticket', None))
    def test_host_opening_game_notifies_guest_and_strangers_cannot_queue(self, ticket):
        table = self.ready_table()
        self.client.force_login(self.other)
        self.client.post('/api/push/subscription', self.info, content_type='application/json')
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(f'/t/head-to-head/{table.code}/play').status_code, 302)
        delivery = TablePushDelivery.objects.get()
        self.assertEqual(delivery.subscription.user_id, self.other.pk)
        self.assertEqual(delivery.kind, TablePushDelivery.KIND_HOST_ENTERED)
        stranger = User.objects.create_user(username='stranger')
        self.client.force_login(stranger)
        self.assertEqual(self.client.post(f'/t/head-to-head/{table.code}/play').status_code, 403)
        self.assertEqual(TablePushDelivery.objects.count(), 1)

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
