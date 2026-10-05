"""Validate and order status events while accepting older snapshot senders."""
import uuid

from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

EVENT_FIELDS = {'event_id', 'event_type', 'event_revision', 'occurred_at', 'started_at'}
EVENT_TYPES = {'started', 'admin_required', 'admin_cleared'}


def validate_status_event(body):
    if not EVENT_FIELDS.intersection(body):
        return
    if not EVENT_FIELDS.issubset(body):
        raise ValueError('Incomplete status event')
    if (not isinstance(body['event_id'], str)
            or str(uuid.UUID(body['event_id'])) != body['event_id']
            or body['event_type'] not in EVENT_TYPES
            or type(body['event_revision']) is not int or body['event_revision'] < 1
            or body['status'] != 'playing'):
        raise ValueError('Invalid status event')
    occurred_at = parse_event_time(body['occurred_at'])
    if body['started_at'] is not None and parse_event_time(body['started_at']) > occurred_at:
        raise ValueError('Status event precedes room start')
    presence = body['state'].get('presence')
    if not isinstance(presence, dict) or type(presence.get('needsAdminAdjudication')) is not bool:
        raise ValueError('Invalid admin status')
    if body['event_type'] == 'admin_required' and not presence['needsAdminAdjudication']:
        raise ValueError('Admin-required event has no admin requirement')
    if body['event_type'] == 'admin_cleared' and presence['needsAdminAdjudication']:
        raise ValueError('Admin-cleared event still requires an admin')
    if body['event_type'] == 'started' and body['started_at'] != body['occurred_at']:
        raise ValueError('Start event must carry its start time')


def parse_event_time(value):
    if not isinstance(value, str):
        raise ValueError('Invalid event time')
    parsed = parse_datetime(value)
    if parsed is None or timezone.is_naive(parsed):
        raise ValueError('Event time must include a timezone')
    return parsed


def should_record_snapshot(body, previous, *, allow_equal_sequence=False):
    previous = previous or {}
    if 'event_revision' in body:
        # Presence transitions may share the same game-action sequence. Their
        # own revision orders both duplicates and delayed admin/start events.
        return body['event_revision'] > previous.get('event_revision', 0)
    if 'event_revision' in previous:
        # Previously queued legacy snapshots cannot overwrite a status event.
        return False
    previous_sequence = previous.get('sequence', -1)
    return (body['sequence'] > previous_sequence or (
        allow_equal_sequence and body['sequence'] == previous_sequence and body != previous
    ))


def snapshot_response(body, status):
    payload = {'status': status}
    if 'event_id' in body:
        payload['event_id'] = body['event_id']
    return JsonResponse(payload)
