"""One active direct game per player, with a ten-minute arrival deadline."""
import json
import logging
from decimal import Decimal
from datetime import timedelta
from urllib.request import Request, urlopen
from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from tournaments.models import DirectPlaySettings, HeadToHeadTable, WalletTransaction

logger = logging.getLogger(__name__)
ACTIVE = ('open', 'ready', 'playing')


def active_table(user_id, exclude=None):
    tables = HeadToHeadTable.objects.filter(Q(host_id=user_id) | Q(guest_id=user_id), status__in=ACTIVE)
    if exclude is not None:
        tables = tables.exclude(pk=exclude)
    return tables.first()


def remote_expiry(table):
    from gamelink.signing import sign_command_body
    raw = json.dumps({'v': 1, 'action': 'expire_unstarted', 'fixture_id': -table.pk}).encode()
    timestamp = str(int(timezone.now().timestamp()))
    request = Request(settings.GAMELINK_BACKGAMMON_URL.rstrip('/') + '/api/link/admin-command/',
        data=raw, headers={'Content-Type': 'application/json', 'X-Gamelink-Timestamp': timestamp,
            'X-Gamelink-Issuer': settings.GAMELINK_ISSUER,
            'X-Gamelink-Signature': sign_command_body(raw, timestamp)}, method='POST')
    with urlopen(request, timeout=3) as response:
        return json.load(response).get('status')


def expire_unstarted_tables(user_id=None):
    cutoff = timezone.now() - timedelta(minutes=10)
    tables = HeadToHeadTable.objects.filter(status__in=ACTIVE, created_at__lte=cutoff)
    if user_id is not None:
        tables = tables.filter(Q(host_id=user_id) | Q(guest_id=user_id) | Q(status='open'))
    ids = list(tables.values_list('pk', flat=True))
    for pk in ids:
        observed = HeadToHeadTable.objects.get(pk=pk)
        if (observed.settlement or {}).get('entry_confirmed'):
            continue
        result = None
        if observed.status == 'playing' or observed.external_room_id:
            try:
                result = remote_expiry(observed)
            except Exception:
                logger.warning('Entry expiry deferred for table %s: game server unavailable', pk)
                continue
            if result == 'started':
                with transaction.atomic():
                    current = HeadToHeadTable.objects.select_for_update().get(pk=pk)
                    current.settlement = {**(current.settlement or {}), 'entry_confirmed': True}
                    current.save(update_fields=['settlement'])
                continue
            if result not in ('missing', 'cancelled'):
                continue
        # Same settings -> table -> users lock order as creation and joining.
        with transaction.atomic():
            DirectPlaySettings.objects.select_for_update().get(pk=1)
            table = HeadToHeadTable.objects.select_for_update().get(pk=pk)
            if table.status not in ACTIVE:
                continue
            if table.status != observed.status or table.external_room_id != observed.external_room_id:
                continue
            from django.contrib.auth.models import User
            players = list(User.objects.select_for_update().filter(pk__in=[table.host_id, table.guest_id]).order_by('pk'))
            for player in players:
                net = table.wallet_transactions.filter(user=player).filter(
                    Q(amount__lt=0) | Q(kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND)
                ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
                if net < 0:
                    WalletTransaction.create_entry(user=player, amount=-net,
                        kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND,
                        head_to_head_table=table, note=f'Entry deadline expired: {table.code}')
            table.status = 'cancelled'
            table.completed_at = timezone.now()
            table.save(update_fields=['status', 'completed_at', 'updated_at'])
