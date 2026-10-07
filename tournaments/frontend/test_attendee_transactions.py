import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import connection
from django.test import RequestFactory, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from tournaments.models import Participant, Participation, Tournament, TournamentRegistration, WalletTransaction

from . import api
from .test_attendee_operations import DEFINITION


class AttendeeTransactionTests(TransactionTestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='attendee-admin', is_staff=True)
        self.players = [User.objects.create_user(username=f'attendee-{i}') for i in range(2)]
        self.tournament = Tournament.load(
            DEFINITION, 'Transaction cup', creator=self.staff, published=True,
            starts_at=timezone.now() + timedelta(hours=1),
            min_players=2, max_players=2, entry_fee=Decimal('10'),
        )
        for user in self.players:
            WalletTransaction.create_entry(user=user, amount=100, kind=WalletTransaction.KIND_DEPOSIT)
        self.factory = RequestFactory()
        self.url = f'/api/admin/tournaments/{self.tournament.pk}/attendees'

    def request(self, method, data=None, user=None, raw=None):
        if method == 'GET':
            request = self.factory.get(self.url)
        else:
            request = getattr(self.factory, method.lower())(
                self.url, data=raw if raw is not None else json.dumps(data or {}),
                content_type='application/json',
            )
        request.user = self.staff if user is None else user

        def outside_atomic(function):
            def wrapped(*args, **kwargs):
                self.assertFalse(connection.in_atomic_block)
                return function(*args, **kwargs)
            return wrapped

        with (
            patch.object(api, '_require_staff', side_effect=outside_atomic(api._require_staff)),
            patch.object(api, '_attendee_rows', side_effect=outside_atomic(api._attendee_rows)),
            patch.object(api, '_registration_summary', side_effect=outside_atomic(api._registration_summary)),
        ):
            return api.api_admin_tournament_attendees(request, self.tournament.pk)

    def withdrawn_registrations(self):
        return [
            TournamentRegistration.objects.create(
                tournament=self.tournament, participant=Participant.get_or_create_for_user(user),
                status=TournamentRegistration.STATUS_WITHDRAWN,
                payment_status=TournamentRegistration.PAYMENT_REFUNDED,
            )
            for user in self.players
        ]

    def assert_unchanged(self, registrations):
        for registration in registrations:
            registration.refresh_from_db()
            self.assertEqual(registration.status, TournamentRegistration.STATUS_WITHDRAWN)
            self.assertEqual(registration.payment_status, TournamentRegistration.PAYMENT_REFUNDED)
        self.assertFalse(self.tournament.wallet_transactions.exists())

    def test_invalid_json_and_action_are_rejected_without_starting_transaction(self):
        for method, raw in (
            ('POST', '{'), ('POST', '[]'),
            ('PATCH', '{"participant_ids":[1],"action":"unknown"}'),
            ('PATCH', '{"participant_ids":"1","action":"restore"}'),
        ):
            with self.subTest(raw=raw), CaptureQueriesContext(connection) as captured:
                self.assertEqual(self.request(method, raw=raw).status_code, 400)
            self.assertEqual(len(captured), 0)

    def test_nonstaff_is_rejected_without_starting_transaction(self):
        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(self.request('POST', user=self.players[0]).status_code, 403)
        self.assertEqual(len(captured), 0)

    def test_get_and_csv_do_not_start_a_transaction(self):
        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(self.request('GET').status_code, 200)
            request = self.factory.get(self.url, {'format': 'csv'})
            request.user = self.staff
            self.assertEqual(api.api_admin_tournament_attendees(request, self.tournament.pk).status_code, 200)
        self.assertFalse(any(query['sql'].startswith('BEGIN') for query in captured.captured_queries))

    def test_insufficient_funds_rolls_back_new_registration_and_identity(self):
        WalletTransaction.create_entry(
            user=self.players[0], amount=-95, kind=WalletTransaction.KIND_WITHDRAWAL,
        )
        response = self.request('POST', {'user_id': self.players[0].pk})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)['code'], 'insufficient_funds')
        self.assertFalse(self.tournament.registrations.exists())
        self.assertFalse(self.tournament.participations.exists())
        self.assertFalse(Participant.objects.filter(user=self.players[0]).exists())
        self.assertEqual(WalletTransaction.balance_for_user(self.players[0]), Decimal('5'))

    def test_second_restore_exceeding_capacity_rolls_back_first_restore_and_fee(self):
        registrations = self.withdrawn_registrations()
        Participation.objects.create(
            tournament=self.tournament, participant=Participant.objects.create(name='existing'), slot_id=0,
        )
        response = self.request('PATCH', {
            'action': 'restore', 'participant_ids': [r.participant_id for r in registrations],
        })
        self.assertEqual(response.status_code, 412)
        self.assertEqual(self.tournament.participations.count(), 1)
        self.assert_unchanged(registrations)
        self.assertEqual(WalletTransaction.balance_for_user(self.players[0]), Decimal('100'))

    def test_second_restore_with_insufficient_funds_rolls_back_entire_batch(self):
        registrations = self.withdrawn_registrations()
        WalletTransaction.create_entry(user=self.players[1], amount=-95, kind=WalletTransaction.KIND_WITHDRAWAL)
        response = self.request('PATCH', {
            'action': 'restore', 'participant_ids': [r.participant_id for r in registrations],
        })
        self.assertEqual(response.status_code, 412)
        self.assertFalse(self.tournament.participations.exists())
        self.assert_unchanged(registrations)
        self.assertEqual(WalletTransaction.balance_for_user(self.players[0]), Decimal('100'))

    def test_missing_registration_does_not_create_legacy_registration(self):
        participants = [Participant.get_or_create_for_user(user) for user in self.players]
        Participation.objects.create(tournament=self.tournament, participant=participants[0], slot_id=0)
        response = self.request('PATCH', {
            'action': 'mark_paid', 'participant_ids': [p.pk for p in participants],
        })
        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.tournament.registrations.exists())

    def test_successful_restore_and_withdraw_build_response_after_commit_and_refund_once(self):
        registrations = self.withdrawn_registrations()
        ids = [r.participant_id for r in registrations]
        restored = self.request('PATCH', {'action': 'restore', 'participant_ids': ids})
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(json.loads(restored.content)['summary']['registered'], 2)
        for attempt, expected_refunds in ((1, 2), (2, 0)):
            with self.subTest(attempt=attempt):
                response = self.request('PATCH', {'action': 'withdraw', 'participant_ids': ids})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(json.loads(response.content)['refunded_count'], expected_refunds)
        self.assertFalse(self.tournament.participations.exists())
        for user in self.players:
            self.assertEqual(WalletTransaction.balance_for_user(user), Decimal('100'))
