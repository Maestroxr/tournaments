"""Read-only provider monitoring and audited local finance operations."""
import json
import re
import uuid
import time
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import F, Sum
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import CheckoutEvent, CheckoutRefund, CheckoutRequest, TranzilaIssue, TranzilaRun
from .tranzila import ProviderError, Tranzila
from .tranzila_flow import check_configuration, response_errors, verify_payment


def can_manage(user):
    return bool(user.is_authenticated and user.is_active and
                (user.is_superuser or (user.is_staff and user.has_perm('billing.manage_payments'))))


def require_finance(request):
    if not can_manage(request.user):
        return JsonResponse({'detail': 'Payment management permission required.'}, status=403)


def current_environment():
    return 'live' if settings.TRANZILA_ENVIRONMENT == 'live' else 'sandbox'


def reference(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_./:-]{1,100}', value):
        raise ValueError('Use an operation reference, not personal or card data.')
    return value


def json_body(request):
    if len(request.body) > 16 * 1024:
        raise ValueError('Request too large')
    data = json.loads(request.body)
    if not isinstance(data, dict):
        raise ValueError('Expected an object')
    return data


def audit_issue(index, code, checkout=None):
    now = timezone.now()
    issue, _ = TranzilaIssue.objects.get_or_create(terminal=settings.TRANZILA_TERMINAL,
        environment=current_environment(), transaction_index=str(index), code=code,
        defaults={'checkout': checkout})
    issue.last_seen_at = now
    issue.checkout = checkout
    # Recurrence after a manual resolution must become visible again.
    issue.resolved_at = None
    issue.resolved_by = None
    issue.resolution_reference = ''
    issue.save()
    return issue


def reconcile_one(identifier, index, actor=None):
    """Also re-read paid transactions, so refunds/changes are not hidden by retries."""
    row = CheckoutRequest.objects.get(pk=identifier)
    CheckoutEvent.objects.create(checkout=row, kind='reconciliation_started', actor=actor)
    try:
        if row.status == 'paid':
            check_configuration()
            provider = Tranzila()
            if (row.provider_terminal != provider.terminal or row.environment != current_environment()
                    or row.provider_transaction_index != str(index)):
                raise ValueError('Wrong payment reference')
            record = provider.lookup(index)
            if (record['checkout_id'] != str(row.pk) or record['duplicate_key'] != str(row.pk)
                    or record['terminal'] != row.provider_terminal or record['transaction_index'] != index
                    or Decimal(record['amount']) != row.amount or record['currency'] != row.currency
                    or record['processor_response_code'] != '000' or record['tranmode'] != 'A'
                    or record['txn_type'].upper() != 'DEBIT'
                    or record['transtatus'] != settings.TRANZILA_APPROVED_TRANSTATUS):
                raise ValueError('Provider payment changed; review required')
        else:
            row = verify_payment(identifier, index)
    except (ProviderError, ValueError, IntegrityError):
        CheckoutEvent.objects.create(checkout_id=identifier, kind='reconciliation_failed', actor=actor)
        audit_issue(index, 'verification_failed', row)
        raise
    finally:
        CheckoutRequest.objects.filter(pk=identifier).update(last_reconciled_at=timezone.now())
    CheckoutEvent.objects.create(checkout_id=identifier, kind='reconciliation_completed', actor=actor)
    TranzilaIssue.objects.filter(terminal=settings.TRANZILA_TERMINAL, environment=current_environment(),
        transaction_index=str(index), code='verification_failed', resolved_at__isnull=True).update(
            resolved_at=timezone.now(), resolution_reference='verified-provider-report')
    return row


def begin_run(kind, date_from, date_to, actor=None):
    if kind != 'health':
        check_configuration()
    else:
        Tranzila()  # Report access can be tested before approving report mappings.
    # A crashed process cannot block the scheduler permanently. The bounded job
    # is expected to finish within 30 minutes; do not run unbounded backfills.
    TranzilaRun.objects.filter(status='running', started_at__lt=timezone.now() - timedelta(minutes=30)).update(
        status='interrupted', finished_at=timezone.now())
    return TranzilaRun.objects.create(kind=kind, terminal=settings.TRANZILA_TERMINAL,
        environment=current_environment(), date_from=date_from, date_to=date_to, actor=actor)


def run_reports(date_from, date_to, *, health_only=False, actor=None, max_pages=20):
    if date_from > date_to or (date_to - date_from).days > 31 or not 1 <= max_pages <= 20:
        raise ValueError('Report range must be at most 32 days and 20 pages.')
    run = begin_run('health' if health_only else 'reconcile', date_from, date_to, actor)
    try:
        provider = Tranzila()
        deadline = time.monotonic() + 600
        seen = set()
        for page in range(1, max_pages + 1):
            records, total = provider.report_page(date_from, date_to, page, 100)
            if health_only:
                run.status = 'success'
                break
            if not records and len(seen) < total:
                raise ProviderError('Incomplete report pagination.')
            for record in records:
                if time.monotonic() >= deadline:
                    raise ProviderError('Report time budget exceeded; use a narrower range.')
                index = record.get('index')
                if type(index) is not int or not 0 < index <= 999999999999 or index in seen:
                    raise ProviderError('Invalid or repeated report index.')
                seen.add(index)
                run.checked += 1
                if record.get('child_terminal') != provider.terminal:
                    audit_issue(index, 'terminal_mismatch')
                    run.issues += 1
                    continue
                try:
                    identifier = uuid.UUID(str(record.get('user_defined_1', '')))
                except ValueError:
                    identifier = None
                row = CheckoutRequest.objects.filter(pk=identifier, provider_terminal=provider.terminal,
                    environment=current_environment()).first() if identifier else None
                if row is None:
                    audit_issue(index, 'unmatched_transaction')
                    run.issues += 1
                    continue
                if row.status == 'refunded':
                    # Staff already recorded the refund and adjusted fulfillment.
                    continue
                was_pending = row.status == 'pending'
                try:
                    reconcile_one(row.pk, index, actor)
                    run.recovered += int(was_pending)
                except (ProviderError, ValueError, IntegrityError):
                    run.issues += 1
            if len(seen) >= total:
                run.status = 'success'
                break
        else:
            run.status = 'incomplete'
        if not health_only and run.status == 'success':
            # Round-robin inspection of old paid records catches refunds that
            # alter an original transaction outside the recent report window.
            old_paid = CheckoutRequest.objects.filter(provider_terminal=provider.terminal,
                environment=current_environment(), status='paid', paid_at__isnull=False).exclude(
                provider_transaction_index__in=[str(index) for index in seen]).order_by(
                    F('last_reconciled_at').asc(nulls_first=True), 'created_at', 'pk')[:100]
            for row in old_paid:
                if time.monotonic() >= deadline:
                    run.status = 'incomplete'
                    break
                try:
                    index = int(row.provider_transaction_index)
                    reconcile_one(row.pk, index, actor)
                except (ProviderError, ValueError, IntegrityError):
                    run.issues += 1
                run.checked += 1
            old_pending = CheckoutRequest.objects.filter(provider_terminal=provider.terminal,
                environment=current_environment(), status='pending', session_expires_at__date__lt=date_from).order_by(
                    F('last_reconciled_at').asc(nulls_first=True), 'created_at', 'pk')[:25]
            for row in old_pending:
                if time.monotonic() >= deadline:
                    run.status = 'incomplete'
                    break
                # A hosted session has a bounded payment window. Include a day
                # either side for the provider timezone; no match is NOT proof
                # of failure and never authorizes a replacement charge.
                session_day = row.session_expires_at.date()
                try:
                    records, total = provider.report_page(session_day - timedelta(days=1),
                        session_day + timedelta(days=1), checkout_id=str(row.pk))
                    if total != 1 or len(records) != 1:
                        raise ValueError('Missing or ambiguous payment')
                    index = records[0].get('index')
                    if type(index) is not int or not 0 < index <= 999999999999:
                        raise ValueError('Invalid transaction index')
                    reconcile_one(row.pk, index, actor)
                    run.recovered += 1
                    TranzilaIssue.objects.filter(checkout=row, code='pending_unresolved', resolved_at__isnull=True).update(
                        resolved_at=timezone.now(), resolution_reference='verified-provider-report')
                except (ProviderError, ValueError, IntegrityError):
                    audit_issue(row.pk.hex, 'pending_unresolved', row)
                    run.issues += 1
                finally:
                    CheckoutRequest.objects.filter(pk=row.pk).update(last_reconciled_at=timezone.now())
                run.checked += 1
    except (ProviderError, ValueError, IntegrityError, OperationalError):
        run.status = 'failed'
    except Exception:
        run.status = 'failed'
        raise
    finally:
        run.finished_at = timezone.now()
        run.save()
    return run


def serialize_run(run):
    return dict(id=run.pk, kind=run.kind, status=run.status, started_at=run.started_at.isoformat(),
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        date_from=run.date_from.isoformat() if run.date_from else None,
        date_to=run.date_to.isoformat() if run.date_to else None,
        checked=run.checked, recovered=run.recovered, issues=run.issues)


@require_GET
def operations_status(request):
    from frontend.api import _require_staff
    error = _require_staff(request)
    if error:
        return error
    scope = dict(terminal=settings.TRANZILA_TERMINAL, environment=current_environment())
    runs = TranzilaRun.objects.filter(**scope).order_by('-started_at', '-pk')[:10]
    issues = TranzilaIssue.objects.filter(**scope, resolved_at__isnull=True).order_by('-last_seen_at')
    response = JsonResponse({'can_manage': can_manage(request.user),
        'runs': [serialize_run(run) for run in runs], 'issue_count': issues.count(),
        'issues': [dict(id=i.pk, transaction_index=i.transaction_index, code=i.code,
            checkout_id=str(i.checkout_id) if i.checkout_id else None,
            last_seen_at=i.last_seen_at.isoformat()) for i in issues[:50]]})
    response['Cache-Control'] = 'private, no-store'
    return response


@require_POST
@response_errors
def health_check(request):
    error = require_finance(request)
    if error:
        return error
    today = timezone.localdate()
    run = run_reports(today, today, health_only=True, actor=request.user)
    return JsonResponse(serialize_run(run), status=200 if run.status == 'success' else 503)


@require_POST
@response_errors
def resolve_issue(request, identifier):
    error = require_finance(request)
    if error:
        return error
    data = json_body(request)
    ref = reference(data['resolution_reference'])
    with transaction.atomic():
        issue = TranzilaIssue.objects.select_for_update().filter(pk=identifier).first()
        if not issue:
            return JsonResponse({'detail': 'Issue not found.'}, status=404)
        if not issue.resolved_at:
            issue.resolved_at, issue.resolved_by, issue.resolution_reference = timezone.now(), request.user, ref
            issue.save()
            if issue.checkout_id:
                CheckoutEvent.objects.create(checkout_id=issue.checkout_id, kind='review_resolved', actor=request.user)
    return JsonResponse({'status': 'resolved'})


@require_POST
@response_errors
def record_refund(request, identifier):
    error = require_finance(request)
    if error:
        return error
    data = json_body(request)
    if data.get('confirmed_in_provider') is not True:
        raise ValueError('Confirm the completed external refund.')
    ref = reference(data['provider_reference'])
    key = uuid.UUID(str(data['idempotency_key']))
    try:
        amount = Decimal(str(data['amount']))
        if not amount.is_finite() or not 0 < amount < 100000000 or amount != amount.quantize(Decimal('.01')):
            raise ValueError('Invalid refund amount')
    except InvalidOperation:
        raise ValueError('Invalid refund amount') from None
    with transaction.atomic():
        row = CheckoutRequest.objects.select_for_update().get(pk=identifier)
        previous = CheckoutRefund.objects.filter(idempotency_key=key).first()
        if previous:
            if previous.checkout_id != row.pk or previous.amount != amount or previous.provider_reference != ref:
                return JsonResponse({'detail': 'Refund retry conflicts with the saved record.'}, status=409)
            return JsonResponse({'id': previous.pk, 'status': 'recorded'})
        if row.status != 'paid' or not row.provider_transaction_index:
            raise ValueError('A verified payment is required')
        refunded = row.refund_records.aggregate(total=Sum('amount'))['total'] or Decimal(0)
        if refunded + amount > row.amount:
            raise ValueError('Refunds exceed the payment')
        refund = CheckoutRefund.objects.create(checkout=row, amount=amount, provider_reference=ref,
            provider_terminal=row.provider_terminal, environment=row.environment, actor=request.user,
            idempotency_key=key)
        CheckoutEvent.objects.create(checkout=row, kind='external_refund_recorded', actor=request.user)
    return JsonResponse({'id': refund.pk, 'status': 'recorded'}, status=201)


@require_POST
@response_errors
def complete_adjustment(request, identifier, refund_id):
    error = require_finance(request)
    if error:
        return error
    data = json_body(request)
    ref = reference(data['adjustment_reference'])
    if data.get('adjustment_completed') is not True:
        raise ValueError('Confirm the reviewed fulfillment adjustment.')
    with transaction.atomic():
        row = CheckoutRequest.objects.select_for_update().get(pk=identifier)
        refund = row.refund_records.filter(pk=refund_id).first()
        if not refund:
            return JsonResponse({'detail': 'Refund not found.'}, status=404)
        if refund.adjusted_at and refund.adjustment_reference != ref:
            return JsonResponse({'detail': 'This refund already has a different adjustment reference.'}, status=409)
        if not refund.adjusted_at:
            refund.adjusted_at, refund.adjusted_by, refund.adjustment_reference = timezone.now(), request.user, ref
            refund.save()
            CheckoutEvent.objects.create(checkout=row, kind='refund_adjustment_completed', actor=request.user)
        if (not row.refund_records.filter(adjusted_at__isnull=True).exists()
                and row.refund_records.aggregate(total=Sum('amount'))['total'] == row.amount):
            row.status = 'refunded'
            row.save(update_fields=['status', 'updated_at'])
    return JsonResponse({'status': 'recorded'})
