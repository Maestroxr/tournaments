"""Reliable delivery of administrative score and terminal-state commands."""
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import models
from django.utils import timezone

from .models import AdminGameCommand
from .signing import sign_command_body

logger = logging.getLogger(__name__)
COMMAND_PATH = '/api/link/admin-command/'
TIMEOUT_SECONDS = 3.0


def deliver_admin_command(command_id):
    command = AdminGameCommand.objects.filter(pk=command_id).first()
    if command is None or command.status == 'delivered':
        return True
    base_url = getattr(settings, 'GAMELINK_BACKGAMMON_URL', '').rstrip('/')
    if not base_url:
        raise RuntimeError('GAMELINK_BACKGAMMON_URL is not configured')
    raw = json.dumps(command.body, separators=(',', ':'), sort_keys=True).encode()
    timestamp = str(int(timezone.now().timestamp()))
    headers = {
        'Content-Type': 'application/json',
        'X-Gamelink-Timestamp': timestamp,
        'X-Gamelink-Signature': sign_command_body(raw, timestamp),
        'X-Gamelink-Issuer': settings.GAMELINK_ISSUER,
    }
    try:
        request = Request(base_url + COMMAND_PATH, data=raw, headers=headers, method='POST')
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            if not 200 <= response.status < 300:
                raise HTTPError(request.full_url, response.status, 'command rejected', response.headers, None)
    except (HTTPError, URLError, OSError, RuntimeError) as error:
        AdminGameCommand.objects.filter(pk=command.pk).update(
            status='pending', attempts=models.F('attempts') + 1, last_error=str(error)[:2000])
        logger.warning('admin game command delivery failed command=%s: %s', command.pk, error)
        return False
    AdminGameCommand.objects.filter(pk=command.pk).update(
        status='delivered', attempts=models.F('attempts') + 1, last_error='', delivered_at=timezone.now())
    return True


def deliver_admin_command_safely(command_id):
    try:
        return deliver_admin_command(command_id)
    except Exception as error:
        logger.warning('admin game command unavailable command=%s: %s', command_id, error)
        return False


def queue_admin_command(game_link, payload):
    if not getattr(settings, 'GAMELINK_ENABLED', False) or not game_link.external_room_id:
        return None
    command = AdminGameCommand.objects.create(game_link=game_link, body={**payload})
    command.body['command_id'] = str(command.pk)
    command.body['room_id'] = game_link.external_room_id
    command.body['fixture_id'] = game_link.fixture_id
    command.save(update_fields=['body'])
    return command
