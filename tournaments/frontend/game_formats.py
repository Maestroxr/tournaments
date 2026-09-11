"""Server-owned quotes, escrow debits and settlement for versioned game formats."""
import copy
import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone

from tournaments.models import DirectPlaySettings, HeadToHeadTable, WalletTransaction


def money(value):
    return Decimal(str(value)).quantize(Decimal('0.01'))


def required_reserve(table, amount=None):
    stake = money(table.amount if amount is None else amount)
    multiplier = table.rules_snapshot['loss_limit_multiplier'] if table.game_format == 'money' else 1
    return money(stake * multiplier)


def held(table, user):
    total = table.wallet_transactions.filter(user=user, kind=WalletTransaction.KIND_HEAD_TO_HEAD_ENTRY).aggregate(total=Sum('amount'))['total']
    return money(-(total or 0))


def reserve(table, user, amount):
    balance = money(WalletTransaction.balance_for_user(user))
    if balance < amount:
        raise ValidationError(f'Insufficient coins: {amount} required, {balance} available for reservation.')
    WalletTransaction.create_entry(user=user, amount=-amount, kind=WalletTransaction.KIND_HEAD_TO_HEAD_ENTRY,
                                   head_to_head_table=table, note=f'Reserved for {table.game_format} table {table.code}')


def quote(settings, data, quick):
    name = data.get('game_format')
    if name not in ('match', 'money'):
        raise ValidationError('Unknown game format.')
    profile = settings.format_profiles[name]
    access = 'quick' if quick else 'private' if data.get('mode') == 'friend' else 'public'
    if data.get('mode', 'match') not in ('match', 'friend'):
        raise ValidationError('Unknown table access.')
    if not settings.enabled or not profile['enabled'] or not profile[access]:
        raise ValidationError('This game format or access method is disabled.')
    points = data.get('target_points', 1 if name == 'money' else 5)
    clock = data.get('time_control', 'normal')
    doubling = data.get('doubling_enabled', True)
    if (type(points) is not int or points not in profile['target_points']
            or clock not in profile['time_controls'] or type(doubling) is not bool
            or doubling not in profile['doubling_options']):
        raise ValidationError('Select the available rules for this format.')
    raw = data.get('amounts', [data.get('amount')]) if quick else [data.get('amount')]
    if not isinstance(raw, list) or not raw or len(raw) > 100:
        raise ValidationError('Select an available stake.')
    stakes = []
    for item in raw:
        if isinstance(item, bool):
            raise ValidationError('Invalid stake.')
        value = Decimal(str(item))
        if not value.is_finite() or value not in profile['stake_amounts']:
            raise ValidationError('Select an available stake.')
        stakes.append(money(value))
    return name, copy.deepcopy(profile), sorted(set(stakes)), points, clock, doubling


def create_or_match(request, *, quick=False):
    from .api import _serialize_head_to_head, _new_table_code, _create_friend_table, FriendCodesUnavailable
    try:
        data = json.loads(request.body or '{}')
        if not isinstance(data, dict):
            raise ValidationError('Expected a game settings object.')
        with transaction.atomic():
            settings = DirectPlaySettings.objects.select_for_update().get(pk=1)
            name, profile, stakes, points, clock, doubling = quote(settings, data, quick)
            fields = dict(game_format=name, rules_snapshot=profile, target_points=points,
                          time_control=clock, doubling_enabled=doubling, is_quick_match=quick)
            if quick:
                queue = HeadToHeadTable.objects.select_for_update().filter(
                    game_format=name, target_points=points, time_control=clock, doubling_enabled=doubling,
                    is_quick_match=True, status='open', guest__isnull=True).select_related('host').order_by('created_at', 'pk')
                for existing in queue.filter(host=request.user):
                    if existing.rules_snapshot == profile and [money(x) for x in existing.quick_stakes] == stakes:
                        return JsonResponse({**_serialize_head_to_head(existing), 'matched': False})
                for candidate in queue.exclude(host=request.user):
                    common = sorted(set(stakes) & {money(x) for x in candidate.quick_stakes})
                    if not common or candidate.rules_snapshot != profile:
                        continue
                    list(User.objects.select_for_update().filter(pk__in=sorted((candidate.host_id, request.user.pk))).order_by('pk'))
                    stake = common[0]
                    required = required_reserve(candidate, stake)
                    if held(candidate, candidate.host) < required:
                        continue
                    reserve(candidate, request.user, required)
                    candidate.amount = stake
                    candidate.fee_per_player = money(stake * candidate.fee_percent / 100)
                    candidate.guest = request.user
                    candidate.status = 'ready'
                    candidate.save(update_fields=['amount', 'fee_per_player', 'guest', 'status', 'updated_at'])
                    return JsonResponse({**_serialize_head_to_head(candidate), 'matched': True})
            User.objects.select_for_update().get(pk=request.user.pk)
            fields.update(mode='match' if quick else data.get('mode', 'match'), host=request.user,
                          amount=stakes[0], quick_stakes=[str(x) for x in stakes] if quick else [],
                          fee_percent=money(profile['fee_percent']),
                          fee_per_player=money(stakes[0] * money(profile['fee_percent']) / 100))
            table = _create_friend_table(**fields) if fields['mode'] == 'friend' else HeadToHeadTable.objects.create(code=_new_table_code(), **fields)
            reserve(table, request.user, required_reserve(table, max(stakes)))
            return JsonResponse({**_serialize_head_to_head(table), 'matched': False}, status=201)
    except FriendCodesUnavailable:
        return JsonResponse({'detail': 'No private invitation codes are available.'}, status=503)
    except (ValidationError, ValueError, TypeError, ArithmeticError) as error:
        return JsonResponse({'detail': '; '.join(getattr(error, 'messages', [str(error)]))}, status=400)


def join_table(table, user, settings):
    profile = settings.format_profiles[table.game_format]
    access = 'private' if table.mode == 'friend' else 'public'
    if not settings.enabled or not profile['enabled'] or not profile[access]:
        raise ValidationError('This game format or access method is disabled.')
    list(User.objects.select_for_update().filter(pk__in=sorted((table.host_id, user.pk))).order_by('pk'))
    required = required_reserve(table)
    if held(table, table.host) < required:
        raise ValidationError('The host reservation is missing.')
    reserve(table, user, required)
    table.guest = user
    table.status = 'ready'
    table.save(update_fields=['guest', 'status', 'updated_at'])


def settle(table, body):
    """Called only for an authenticated result, under the table row lock."""
    if table.external_room_id and table.external_room_id != body['room_id']:
        raise ValidationError('Game room does not match this table.')
    cancelled = body['status'] == 'cancelled'
    if not cancelled and (not table.guest_id or table.status not in ('ready', 'playing')):
        raise ValidationError('The game has not been funded.')
    players = [table.host] + ([table.guest] if table.guest_id else [])
    list(User.objects.select_for_update().filter(pk__in=sorted(player.pk for player in players)).order_by('pk'))
    reserves = {player.pk: held(table, player) for player in players}
    if any(table.wallet_transactions.filter(user=player, kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND).exists() for player in players):
        raise ValidationError('Reservation has already been released.')
    winner = None
    transfer = Decimal(0)
    fee = Decimal(0)
    result = body.get('financial_result')
    if not cancelled:
        if any(value < required_reserve(table) for value in reserves.values()):
            raise ValidationError('Missing game reservation.')
        winner = table.host if body.get('winner_seat') == 'p1' else table.guest if body.get('winner_seat') == 'p2' else None
        if winner is None:
            raise ValidationError('Missing winner.')
        transfer = money(table.amount)
        if table.game_format == 'money':
            if not isinstance(result, dict) or result.get('format') != 'money':
                raise ValidationError('A verified money-game result is required.')
            cube, win_type = result.get('cube'), result.get('win_type')
            if type(cube) is not int or cube not in (1, 2, 4, 8, 16, 32, 64) or cube > table.rules_snapshot['max_cube']:
                raise ValidationError('Invalid final cube.')
            if not table.doubling_enabled and cube != 1:
                raise ValidationError('Doubling is disabled for this table.')
            if win_type not in ('single', 'gammon', 'backgammon'):
                raise ValidationError('Invalid win type.')
            multiplier = {'single': 1, 'gammon': 2, 'backgammon': 3}[win_type]
            if table.rules_snapshot['jacoby'] and cube == 1:
                multiplier = 1
            transfer = min(required_reserve(table), money(table.amount * cube * multiplier))
        fee = money(transfer * table.fee_percent / 100)
    for player in players:
        # Returning the winner's own reservation is not winnings. Only the loser
        # transfers the settled stake. Combined wallet change equals minus fee.
        release = reserves[player.pk] if cancelled or player == winner else reserves[player.pk] - transfer
        if release:
            WalletTransaction.create_entry(user=player, amount=release, kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND,
                                           head_to_head_table=table, note='Unused game reservation released')
    if winner and transfer > fee:
        WalletTransaction.create_entry(user=winner, amount=transfer - fee, kind=WalletTransaction.KIND_HEAD_TO_HEAD_PRIZE,
                                       head_to_head_table=table, note=f'Game winnings; fee {fee}')
    table.external_room_id = body['room_id']
    table.winner = winner
    table.status = 'cancelled' if cancelled else 'completed'
    table.completed_at = timezone.now()
    table.settlement = {'transfer': str(transfer), 'fee': str(fee), 'result': result, 'reservation_released': True}
    table.save(update_fields=['external_room_id', 'winner', 'status', 'completed_at', 'settlement', 'updated_at'])
