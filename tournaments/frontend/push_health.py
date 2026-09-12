"""Staff-only push diagnostics. Never expose subscription endpoints or signing keys."""
from datetime import timedelta
from importlib.util import find_spec

from django.conf import settings
from django.db.models import Count, Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import PushDelivery, TablePushDelivery, PushWorkerStatus
from .push import configured


def heartbeat(interval=5):
    now = timezone.now()
    PushWorkerStatus.objects.update_or_create(pk=1, defaults={
        'last_seen_at': now,
        'expected_by': now + timedelta(seconds=max(120, interval * 3)),
    })


@require_GET
def admin_push_health(request):
    from .api import _require_staff
    error = _require_staff(request)
    if error:
        return error
    now = timezone.now()
    issues = []
    missing = [name for name in ('WEB_PUSH_PUBLIC_KEY', 'WEB_PUSH_PRIVATE_KEY', 'WEB_PUSH_SUBJECT')
               if not getattr(settings, name, '')]
    if missing:
        issues.append({'code': 'configuration_missing', 'fields': missing})
    if find_spec('pywebpush') is None:
        issues.append({'code': 'library_missing'})
    worker = PushWorkerStatus.objects.filter(pk=1).first()
    if configured() and (not worker or worker.expected_by <= now):
        issues.append({'code': 'worker_stopped'})
    counts = {'failed': 0, 'retrying': 0, 'delayed': 0}
    for model in (PushDelivery, TablePushDelivery):
        result = model.objects.filter(delivered_at=None, discarded_at=None).aggregate(
            failed=Count('pk', filter=Q(attempts__gte=5, next_attempt_at__lte=now)),
            retrying=Count('pk', filter=Q(attempts__gt=0, attempts__lt=5, next_attempt_at__lte=now)),
            delayed=Count('pk', filter=Q(attempts__lt=5, next_attempt_at__lt=now - timedelta(minutes=2))),
        )
        for key in counts:
            counts[key] += result[key]
    for key, count in counts.items():
        if count:
            issues.append({'code': key, 'count': count})
    response = JsonResponse({'issues': issues, 'checked_at': now.isoformat(),
                             'last_worker_seen_at': worker.last_seen_at.isoformat() if worker else None})
    response['Cache-Control'] = 'private, no-store'
    return response
