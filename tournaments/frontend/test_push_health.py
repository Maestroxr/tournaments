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

    def queue_delivery(self, model, user=None, **values):
        user = user or self.user
        device, _ = PushSubscription.objects.get_or_create(
            user=user, endpoint_hash=f'health-{user.pk}', defaults={
                'endpoint': f'https://fcm.googleapis.com/secret-endpoint-{user.pk}',
                'p256dh': 'secret-key', 'auth': 'secret-auth',
            },
        )
        params = {'subscription': device, 'next_attempt_at': timezone.now() - timedelta(minutes=3), **values}
        if model is PushDelivery:
            tournament = Tournament.objects.create(name='Player health test', podium_spec=[])
            mode = Knockout.objects.create(tournament=tournament)
            params['fixture'] = Fixture.objects.create(mode=mode, level=0)
        else:
            params['table'] = HeadToHeadTable.objects.create(
                code=f'I{HeadToHeadTable.objects.count():05d}', host=user, mode='match',
                amount='100.00', fee_percent='5.00', fee_per_player='5.00',
            )
            params['kind'] = TablePushDelivery.KIND_GUEST_JOINED
        return model.objects.create(**params)

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

    def test_player_config_reports_delivery_availability_without_private_keys(self):
        response = self.client.get('/api/push/config')
        self.assertTrue(response.json()['enabled'])
        self.assertFalse(response.json()['deliveryAvailable'])
        self.assertIsNone(response.json()['recentDeliveryIssue'])
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertNotContains(response, 'private-test')
        heartbeat()
        self.assertTrue(self.client.get('/api/push/config').json()['deliveryAvailable'])
        PushWorkerStatus.objects.update(expected_by=timezone.now() - timedelta(seconds=1))
        self.assertFalse(self.client.get('/api/push/config').json()['deliveryAvailable'])

    def test_player_config_reports_recent_issues_in_each_queue(self):
        heartbeat()
        for model in (PushDelivery, TablePushDelivery):
            delivery = self.queue_delivery(model)
            for attempts, issue in ((0, 'delayed'), (1, 'retrying'), (5, 'failed')):
                with self.subTest(queue=model.__name__, issue=issue):
                    delivery.attempts = attempts
                    delivery.last_failure_at = timezone.now() if attempts else None
                    delivery.save(update_fields=['attempts', 'last_failure_at'])
                    response = self.client.get('/api/push/config')
                    self.assertTrue(response.json()['deliveryAvailable'])
                    self.assertEqual(response.json()['recentDeliveryIssue'], issue)
                    for secret in ('secret-endpoint', 'secret-key', 'secret-auth', 'private-test'):
                        self.assertNotContains(response, secret)
            delivery.delete()

    def test_player_config_uses_issue_priority_across_both_queues(self):
        tournament_delivery = self.queue_delivery(PushDelivery)
        self.queue_delivery(TablePushDelivery, attempts=1, last_failure_at=timezone.now())
        self.assertEqual(self.client.get('/api/push/config').json()['recentDeliveryIssue'], 'retrying')
        tournament_delivery.attempts = 5
        tournament_delivery.last_failure_at = timezone.now()
        tournament_delivery.save(update_fields=['attempts', 'last_failure_at'])
        self.assertEqual(self.client.get('/api/push/config').json()['recentDeliveryIssue'], 'failed')

    def test_player_config_ignores_other_accounts_old_resolved_and_inflight_deliveries(self):
        now = timezone.now()
        other = User.objects.create_user(username='other-player')
        cases = [
            {'user': other, 'attempts': 5, 'last_failure_at': now},
            {'attempts': 5, 'last_failure_at': now - timedelta(hours=25)},
            {'attempts': 5, 'last_failure_at': now, 'delivered_at': now},
            {'attempts': 5, 'last_failure_at': now, 'discarded_at': now},
            {'attempts': 5, 'next_attempt_at': now + timedelta(seconds=60)},
            {'attempts': 1, 'next_attempt_at': now + timedelta(seconds=60)},
            {'attempts': 5},
            {'attempts': 0, 'next_attempt_at': now - timedelta(minutes=1)},
            {'attempts': 0, 'next_attempt_at': now - timedelta(hours=25)},
        ]
        for model in (PushDelivery, TablePushDelivery):
            for values in cases:
                self.queue_delivery(model, **values)
        self.assertIsNone(self.client.get('/api/push/config').json()['recentDeliveryIssue'])

    def test_final_inflight_attempt_with_earlier_failure_still_reports_retrying(self):
        now = timezone.now()
        for model in (PushDelivery, TablePushDelivery):
            with self.subTest(queue=model.__name__):
                delivery = self.queue_delivery(
                    model, attempts=5, last_failure_at=now - timedelta(seconds=70),
                    next_attempt_at=now + timedelta(seconds=50),
                )
                self.assertEqual(self.client.get('/api/push/config').json()['recentDeliveryIssue'], 'retrying')
                # The final provider response fails while its lease is still active.
                delivery.last_failure_at = timezone.now()
                delivery.save(update_fields=['last_failure_at'])
                self.assertEqual(self.client.get('/api/push/config').json()['recentDeliveryIssue'], 'failed')
                delivery.delivered_at = timezone.now()
                delivery.save(update_fields=['delivered_at'])
                self.assertIsNone(self.client.get('/api/push/config').json()['recentDeliveryIssue'])

    def test_expired_final_lease_with_earlier_failure_reports_exhaustion(self):
        now = timezone.now()
        for model in (PushDelivery, TablePushDelivery):
            with self.subTest(queue=model.__name__):
                delivery = self.queue_delivery(
                    model, attempts=5, last_failure_at=now - timedelta(seconds=70),
                    next_attempt_at=now - timedelta(seconds=1),
                )
                self.assertEqual(self.client.get('/api/push/config').json()['recentDeliveryIssue'], 'failed')
                delivery.delete()

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
