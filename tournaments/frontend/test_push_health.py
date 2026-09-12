from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from tournaments.models import Fixture, HeadToHeadTable, Knockout, Tournament
from .models import PushDelivery, PushSubscription, PushWorkerStatus, TablePushDelivery
from .push_health import heartbeat


@override_settings(WEB_PUSH_PUBLIC_KEY='public-test', WEB_PUSH_PRIVATE_KEY='private-test',
                   WEB_PUSH_SUBJECT='mailto:test@example.com')
class PushHealthTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='operator', is_staff=True)
        self.client.force_login(self.user)
        self.library = patch('frontend.push_health.find_spec', return_value=object())
        self.library.start()
        self.addCleanup(self.library.stop)

    def health(self):
        return self.client.get('/api/admin/push-health')

    def test_staff_only_and_read_only(self):
        self.client.logout()
        self.assertEqual(self.health().status_code, 401)
        self.user.is_staff = False
        self.user.save()
        self.client.force_login(self.user)
        self.assertEqual(self.health().status_code, 403)
        self.assertEqual(self.client.post('/api/admin/push-health').status_code, 405)

    @override_settings(WEB_PUSH_PRIVATE_KEY='')
    def test_missing_settings_and_library_without_exposing_keys(self):
        with patch('frontend.push_health.find_spec', return_value=None):
            response = self.health()
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response.json()['issues'], [
            {'code': 'configuration_missing', 'fields': ['WEB_PUSH_PRIVATE_KEY']},
            {'code': 'library_missing'},
        ])
        self.assertNotContains(response, 'public-test')
        self.assertNotContains(response, 'mailto:test@example.com')

    def test_missing_stale_and_recovered_worker(self):
        self.assertEqual(self.health().json()['issues'], [{'code': 'worker_stopped'}])
        heartbeat()
        self.assertEqual(self.health().json()['issues'], [])
        PushWorkerStatus.objects.update(expected_by=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.health().json()['issues'], [{'code': 'worker_stopped'}])
        heartbeat()
        self.assertEqual(self.health().json()['issues'], [])

    def test_worker_command_records_heartbeat_without_sending(self):
        with patch('frontend.management.commands.run_push_notifications.discover_ready_matches', return_value=0), \
                patch('frontend.management.commands.run_push_notifications.find_spec', return_value=object()):
            call_command('run_push_notifications', once=True, interval=60)
        worker = PushWorkerStatus.objects.get(pk=1)
        self.assertEqual(worker.expected_by - worker.last_seen_at, timedelta(seconds=180))

    def test_counts_both_queues_excluding_completed_discarded_and_inflight_final_attempt(self):
        heartbeat()
        now = timezone.now()
        device = PushSubscription.objects.create(user=self.user, endpoint_hash='test',
            endpoint='https://fcm.googleapis.com/secret-endpoint', p256dh='secret-key', auth='secret-auth')
        tournament = Tournament.objects.create(name='Health test', podium_spec=[])
        mode = Knockout.objects.create(tournament=tournament)
        cases = [
            {'attempts': 5},
            {'attempts': 1},
            {'attempts': 0},
            {'attempts': 5, 'delivered_at': now},
            {'attempts': 5, 'discarded_at': now},
            {'attempts': 5, 'next_attempt_at': now + timedelta(seconds=60)},
        ]
        for index, values in enumerate(cases):
            params = {'subscription': device, 'next_attempt_at': now - timedelta(minutes=3), **values}
            fixture = Fixture.objects.create(mode=mode, level=index)
            PushDelivery.objects.create(fixture=fixture, **params)
            table = HeadToHeadTable.objects.create(code=f'HLTH{index}', host=self.user,
                mode='match', amount='100.00', fee_percent='5.00', fee_per_player='5.00')
            TablePushDelivery.objects.create(table=table, kind='guest_joined', **params)
        response = self.health()
        self.assertEqual(response.json()['issues'], [
            {'code': 'failed', 'count': 2}, {'code': 'retrying', 'count': 2}, {'code': 'delayed', 'count': 4},
        ])
        for secret in ('secret-endpoint', 'secret-key', 'secret-auth', 'private-test'):
            self.assertNotContains(response, secret)
