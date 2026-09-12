import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings, Client
from django.urls import reverse
from django.utils import timezone

from .models import CheckoutEvent, CheckoutRefund, CheckoutRequest, Payment, Subscription, TranzilaIssue, TranzilaRun
from .operations import run_reports
from .services import entitlement_for
from .test_tranzila_flow import CONFIG, TranzilaFlowTests
from .tranzila import ProviderError, Tranzila
from .tranzila_flow import prepare, verify_payment


@override_settings(**CONFIG)
class PaymentOperationsTests(TestCase):
    order = TranzilaFlowTests.order
    record = TranzilaFlowTests.record

    def setUp(self):
        TranzilaFlowTests.setUp(self)
        self.client.force_login(self.staff)
        self.operations_patcher = patch('billing.operations.Tranzila', return_value=self.provider)
        self.operations_patcher.start()
        self.addCleanup(self.operations_patcher.stop)
        self.report = {'index': 100, 'child_terminal': 'merchanttest', 'user_defined_1': str(self.row.pk)}
        self.provider.report_page.return_value = ([self.report], 1)

    def paid(self):
        prepare(self.row.pk, self.user)
        verify_payment(self.row.pk, 100)

    def refund(self, **changes):
        data = dict(amount='2.00', provider_reference='REF-1', idempotency_key=str(uuid.uuid4()), confirmed_in_provider=True)
        data.update(changes)
        return self.client.post(reverse('api-admin-tranzila-refund', args=[self.row.pk]), data, content_type='application/json')

    def test_highest_tier_falls_back_to_lower_then_free_after_expiry(self):
        now = timezone.now()
        low = self.order(product='subscription', tier='GOLD', coin_quantity=0, status='paid',
                         paid_at=now, valid_until=now + timedelta(days=365), environment='live')
        high = self.order(product='subscription', tier='VIP', coin_quantity=0, status='paid',
                          paid_at=now, valid_until=now + timedelta(days=30), environment='live')
        self.assertEqual(entitlement_for(self.user)['tier'], 'VIP')
        self.assertEqual(entitlement_for(self.user)['valid_until'], high.valid_until)
        CheckoutRequest.objects.filter(pk=high.pk).update(valid_until=now - timedelta(seconds=1))
        self.assertEqual(entitlement_for(self.user)['tier'], 'GOLD')
        CheckoutRequest.objects.filter(pk=low.pk).update(valid_until=now - timedelta(seconds=1))
        self.assertFalse(entitlement_for(self.user)['membership'])
        self.assertEqual(entitlement_for(self.user)['tier'], 'FREE')
        self.assertIsNone(entitlement_for(self.user)['valid_until'])

    def test_only_membership_expiring_returns_to_free_and_test_membership_grants_nothing(self):
        now = timezone.now()
        self.order(product='subscription', tier='VIP', coin_quantity=0, status='paid',
                   paid_at=now - timedelta(days=40), valid_until=now, environment='live')
        self.order(product='subscription', tier='VIP', coin_quantity=0, status='paid',
                   paid_at=now, valid_until=now + timedelta(days=30), environment='sandbox')
        self.assertEqual(entitlement_for(self.user)['tier'], 'FREE')

    def test_same_tier_purchase_extends_legacy_period_and_uses_calendar_months(self):
        end = timezone.now().replace(year=2028, month=1, day=31)
        legacy = Subscription.objects.create(user=self.user, tier='GOLD', plan_id='old', status='cancelled', amount=10, currency='ILS')
        Payment.objects.create(subscription=legacy, provider_id='legacy', amount=10, currency='ILS',
                               paid_at=timezone.now(), period_end=end)
        self.row.product, self.row.tier, self.row.coin_quantity = 'subscription', 'GOLD', 0
        self.row.save()
        self.paid()
        self.row.refresh_from_db()
        self.assertEqual(self.row.valid_until, end.replace(month=2, day=29))

    def test_report_access_check_is_read_only_and_can_precede_mapping_approval(self):
        with override_settings(TRANZILA_REPORT_MAPPING_CONFIRMED=False):
            response = self.client.post(reverse('api-admin-tranzila-health'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        self.provider.handshake.assert_not_called()
        self.provider.lookup.assert_not_called()
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'draft')

    def test_health_failure_is_visible_without_leaking_raw_provider_errors(self):
        self.provider.report_page.side_effect = ProviderError('secret-payload')
        response = self.client.post(reverse('api-admin-tranzila-health'))
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, 'secret-payload', status_code=503)
        self.assertEqual(TranzilaRun.objects.get().status, 'failed')

    def test_scheduler_recovers_missing_notification_once_and_records_coverage(self):
        prepare(self.row.pk, self.user)
        today = timezone.localdate()
        first = run_reports(today, today)
        second = run_reports(today, today)
        self.assertEqual((first.status, first.checked, first.recovered), ('success', 1, 1))
        self.assertEqual(second.recovered, 0)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'paid')
        from tournaments.models import WalletTransaction
        self.assertEqual(WalletTransaction.objects.filter(user=self.user).count(), 1)

    def test_scheduler_detects_paid_record_changes_and_unmatched_transactions(self):
        self.paid()
        self.provider.lookup.return_value = self.record(transtatus='cancelled')
        self.provider.report_page.return_value = ([self.report, {**self.report, 'index': 101, 'user_defined_1': ''}], 2)
        today = timezone.localdate()
        for _ in range(2):
            run = run_reports(today, today)
            self.assertEqual(run.issues, 2)
        self.assertEqual(TranzilaIssue.objects.count(), 2)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'paid')  # Unknown cancellation semantics require review.

    def test_scheduler_rechecks_old_paid_transactions_outside_report_dates(self):
        self.paid()
        self.provider.report_page.return_value = ([], 0)
        self.provider.lookup.return_value = self.record(transtatus='cancelled')
        today = timezone.localdate()
        run = run_reports(today, today)
        self.assertEqual((run.checked, run.issues), (1, 1))
        self.assertEqual(TranzilaIssue.objects.get().code, 'verification_failed')
        self.row.refresh_from_db()
        self.assertIsNotNone(self.row.last_reconciled_at)

    def test_old_pending_order_is_discovered_without_notification_or_replacement_charge(self):
        prepare(self.row.pk, self.user)
        old = timezone.now() - timedelta(days=60)
        CheckoutRequest.objects.filter(pk=self.row.pk).update(session_expires_at=old)
        self.provider.report_page.side_effect = [([], 0), ([self.report], 1)]
        today = timezone.localdate()
        run = run_reports(today, today)
        self.assertEqual(run.recovered, 1)
        self.assertEqual(self.provider.report_page.call_args.kwargs['checkout_id'], str(self.row.pk))
        self.provider.handshake.assert_called_once()

    def test_old_pending_no_match_stays_pending_and_opens_review(self):
        prepare(self.row.pk, self.user)
        CheckoutRequest.objects.filter(pk=self.row.pk).update(session_expires_at=timezone.now() - timedelta(days=60))
        self.provider.report_page.return_value = ([], 0)
        today = timezone.localdate()
        run_reports(today, today)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'pending')
        self.assertEqual(TranzilaIssue.objects.get().code, 'pending_unresolved')

    def test_refund_rejects_malformed_body_and_undocumented_confirmation(self):
        self.paid()
        url = reverse('api-admin-tranzila-refund', args=[self.row.pk])
        self.assertEqual(self.client.post(url, [], content_type='application/json').status_code, 400)
        self.assertEqual(self.refund(confirmed_in_provider=False).status_code, 400)
        self.assertEqual(self.refund(amount='NaN').status_code, 400)
        self.assertEqual(self.refund(amount='0.001').status_code, 400)
        self.assertFalse(CheckoutRefund.objects.exists())

    def test_multiple_refunds_do_not_duplicate_totals_in_review_filter(self):
        self.paid()
        self.refund(provider_reference='REF-A')
        self.refund(provider_reference='REF-B')
        data = self.client.get(reverse('api-admin-checkouts'), {'review': 'refund'}).json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['status_counts']['paid'], 1)
        self.assertEqual(Decimal(data['totals'][0]['amount']), Decimal('10'))
        self.assertEqual(Decimal(data['totals'][0]['net']), Decimal('6'))

    def test_pagination_fails_closed_and_command_returns_nonzero_for_partial_run(self):
        self.provider.report_page.return_value = ([], 5)
        with self.assertRaises(CommandError):
            call_command('reconcile_tranzila')
        self.assertEqual(TranzilaRun.objects.get().status, 'failed')
        self.assertEqual(CheckoutRequest.objects.get(pk=self.row.pk).status, 'draft')

    def test_pagination_fetches_all_pages_and_marks_page_limit_incomplete(self):
        self.provider.report_page.side_effect = [([self.report], 2), ([{**self.report, 'index': 101}], 2)]
        today = timezone.localdate()
        run = run_reports(today, today)
        self.assertEqual((run.status, run.checked), ('success', 2))
        self.provider.report_page.side_effect = None
        self.provider.report_page.return_value = ([self.report], 2)
        self.assertEqual(run_reports(today, today, max_pages=1).status, 'incomplete')

    def test_refund_retry_limits_totals_and_pending_adjustment(self):
        self.paid()
        key = str(uuid.uuid4())
        self.assertEqual(self.refund(idempotency_key=key).status_code, 201)
        self.assertEqual(self.refund(idempotency_key=key).status_code, 200)
        self.assertEqual(self.refund(idempotency_key=key, amount='3.00').status_code, 409)
        self.assertEqual(self.refund(amount='9.00', provider_reference='REF-2').status_code, 400)
        self.assertEqual(self.refund(provider_reference='REF-1').status_code, 409)
        self.assertEqual(CheckoutRefund.objects.count(), 1)
        data = self.client.get(reverse('api-admin-checkouts'), {'review': 'refund'}).json()
        self.assertEqual(data['totals'][0]['net'], '8')
        self.assertIsNone(data['items'][0]['refund_records'][0]['adjusted_at'])
        self.assertEqual(data['count'], 1)

    def test_full_refund_requires_separate_attested_adjustment_before_closing(self):
        self.paid()
        response = self.refund(amount='10.00')
        self.assertEqual(response.status_code, 201)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'paid')
        url = reverse('api-admin-tranzila-adjustment', args=[self.row.pk, response.json()['id']])
        self.assertEqual(self.client.post(url, {'adjustment_reference': 'WALLET-42'}, content_type='application/json').status_code, 400)
        for _ in range(2):
            self.assertEqual(self.client.post(url, {'adjustment_reference': 'WALLET-42', 'adjustment_completed': True}, content_type='application/json').status_code, 200)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'refunded')
        self.assertEqual(CheckoutEvent.objects.filter(kind='refund_adjustment_completed').count(), 1)
        self.assertEqual(self.client.post(url, {'adjustment_reference': 'OTHER', 'adjustment_completed': True}, content_type='application/json').status_code, 409)

    def test_finance_permission_and_csrf_are_required(self):
        self.paid()
        viewer = get_user_model().objects.create_user('viewer', is_staff=True)
        self.client.force_login(viewer)
        self.assertEqual(self.refund().status_code, 403)
        self.assertEqual(self.client.post(reverse('api-admin-tranzila-health')).status_code, 403)
        self.assertFalse(self.client.get(reverse('api-admin-tranzila-operations')).json()['can_manage'])
        self.assertEqual(self.client.get(reverse('api-admin-checkouts')).status_code, 200)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.staff)
        self.assertEqual(csrf.post(reverse('api-admin-tranzila-health')).status_code, 403)

    def test_filters_apply_to_totals_and_invalid_dates_are_rejected(self):
        self.paid()
        url = reverse('api-admin-checkouts')
        self.assertEqual(self.client.get(url, {'date_from': 'not-date'}).status_code, 400)
        self.assertEqual(self.client.get(url, {'date_from': '2026-02-30'}).status_code, 400)
        self.assertEqual(self.client.get(url, {'actor': 'missing'}).json()['totals'], [])
        self.assertEqual(self.client.get(url, {'provider': 'paypal'}).json()['count'], 0)
        self.assertEqual(self.client.get(url, {'date_from': timezone.localdate().isoformat()}).json()['count'], 1)


@override_settings(**CONFIG)
class ReportAdapterTests(TestCase):
    def test_report_contract_and_metadata_validation(self):
        today = timezone.localdate()
        adapter = Tranzila()
        with patch.object(adapter, '_send', return_value={'transactions': [], 'total': '0'}) as send:
            self.assertEqual(adapter.report_page(today, today, 2), ([], 0))
            self.assertIn('"page": 2', send.call_args.args[1])
            self.assertIn('transaction_start_date', send.call_args.args[1])
        for response in ({'transactions': [], 'total': -1}, {'transactions': ['bad'], 'total': 1}, {'error_code': 1},
                         {'transactions': [], 'total': 0, 'error_code': 1}, {'transactions': [{}], 'total': 0}):
            with patch.object(adapter, '_send', return_value=response), self.assertRaises(ProviderError):
                adapter.report_page(today, today)
