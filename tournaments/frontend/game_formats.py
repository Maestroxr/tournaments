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
    # Use dynamic reserve if stored (shared max_cube), else fallback to loss_limit
    snap = table.rules_snapshot or {}
    if 'dynamic_reserve_multiplier' in snap:
        return money(stake * snap['dynamic_reserve_multiplier'])
    if 'reserve_multiplier' in snap:
        return money(stake * snap['reserve_multiplier'])
    multiplier = snap.get('loss_limit_multiplier', 8) if table.game_format == 'money' else 1
    return money(stake * multiplier)


def get_mars_multiplier(profile, mars_enabled=None):
    """Mars/Gammon multiplier: 2 if enabled else 1. Defaults to 2 for money games."""
    if mars_enabled is not None:
        return 2 if mars_enabled else 1
    if profile is None:
        return 1
    # explicit flag if present
    if 'mars_enabled' in profile:
        return 2 if profile['mars_enabled'] else 1
    # fallback: money games assume Mars enabled (gammon 2x), match 1x
    # jacoby implies money gammon, but we treat both as 2 for Quick
    return 2


def calculate_dynamic_params(balance, stake, profile, mars_enabled=True, is_quick=None):
    """Central dynamic calculation.

    Quick/Money games are balance-driven and must not inherit fixed profile caps.
    Match/Tournament games keep the configured profile limits.
    """
    stake = money(stake)
    balance = money(balance)
    mars = get_mars_multiplier(profile, mars_enabled)
    base = money(stake * mars)

    if is_quick is None:
        # Money/quick profiles are the only place that should use balance-driven
        # exposure; a scale of 1 point is the money-game contract.
        is_quick = bool(profile and profile.get('target_points') == [1])

    if balance < base:
        return {
            'can_join': False,
            'mars_multiplier': mars,
            'allowed_doubles': 0,
            'max_cube': 1,
            'reserve_multiplier': mars,
            'max_exposure': base,
        }
    if is_quick:
        max_cube = 1
        cube = 1
        while True:
            nxt = cube * 2
            if nxt > (1 << 20):
                break
            exp = money(stake * mars * nxt)
            if exp <= balance:
                max_cube = nxt
                cube = nxt
            else:
                break
        allowed = 0
        c = max_cube
        while c > 1:
            c //= 2
            allowed += 1
        reserve_mult = mars * max_cube
        max_exp = money(stake * reserve_mult)
        return {
            'can_join': True,
            'mars_multiplier': mars,
            'allowed_doubles': allowed,
            'max_cube': max_cube,
            'reserve_multiplier': reserve_mult,
            'max_exposure': max_exp,
        }

    max_cube_profile = profile.get('max_cube', 64) if profile else 64
    loss_limit = profile.get('loss_limit_multiplier', 8) if profile else 8
    loss_cap = money(stake * loss_limit)
    max_cube = 1
    cube = 1
    while cube * 2 <= max_cube_profile:
        nxt = cube * 2
        exp = min(money(stake * mars * nxt), loss_cap)
        if exp <= balance:
            max_cube = nxt
            cube = nxt
        else:
            break
    allowed = 0
    c = max_cube
    while c > 1:
        c //= 2
        allowed += 1
    reserve_mult = mars * max_cube
    max_exp = min(money(stake * reserve_mult), loss_cap)
    if max_exp > balance:
        max_exp = money(balance)
    return {
        'can_join': True,
        'mars_multiplier': mars,
        'allowed_doubles': allowed,
        'max_cube': max_cube,
        'reserve_multiplier': int(max_exp / stake) if stake != 0 else mars,
        'max_exposure': max_exp,
    }


def calculate_max_exposure(stake, profile, balance=None, mars_enabled=True):
    """Single source: max coins player must cover. If balance given, dynamic."""
    if balance is not None:
        return calculate_dynamic_params(balance, stake, profile, mars_enabled)['max_exposure']
    stake = money(stake)
    # fallback legacy fixed multiplier (for settlement of old tables)
    multiplier = profile.get('loss_limit_multiplier', 8) if profile else 8
    # for dynamic, use mars*max_cube, but old tables use loss_limit
    return money(stake * multiplier)


def calculate_allowed_doubles(balance, stake, profile, mars_enabled=True):
    """How many additional doubles balance can support."""
    return calculate_dynamic_params(balance, stake, profile, mars_enabled)['allowed_doubles']


def can_afford_game(balance, stake, profile, mars_enabled=True):
    """Whether player can join/start game (minimum exposure)."""
    return calculate_dynamic_params(balance, stake, profile, mars_enabled)['can_join']


def can_accept_double(balance, stake, current_cube, profile, mars_enabled=True):
    """Whether player can accept one more double (cube*2)."""
    params = calculate_dynamic_params(balance, stake, profile, mars_enabled)
    next_cube = current_cube * 2
    return next_cube <= params['max_cube']


def held(table, user):
    total = table.wallet_transactions.filter(user=user, kind=WalletTransaction.KIND_HEAD_TO_HEAD_ENTRY).aggregate(total=Sum('amount'))['total']
    return money(-(total or 0))


def reserve(table, user, amount):
    balance = money(WalletTransaction.balance_for_user(user))
    if balance < amount:
        raise ValidationError(f'Insufficient coins: {amount} required, {balance} available for reservation.')
    WalletTransaction.create_entry(user=user, amount=-amount, kind=WalletTransaction.KIND_HEAD_TO_HEAD_ENTRY,
                                   head_to_head_table=table, note=f'Reserved for {table.game_format} table {table.code}')


def quote(settings, data, quick, match_search=False):
    name = data.get('game_format')
    if name not in ('match', 'money'):
        raise ValidationError('Unknown game format.')
    profile = settings.format_profiles[name]
    access = 'quick' if quick else 'private' if data.get('mode') == 'friend' else 'public'
    if data.get('mode', 'match') not in ('match', 'friend'):
        raise ValidationError('Unknown table access.')
    expected_format = 'money' if quick and not match_search else 'match'
    if name != expected_format:
        raise ValidationError('Quick games use money format; public, friend and match-search games use match format.')
    if not settings.enabled or not profile['enabled'] or not profile[access]:
        raise ValidationError('This game format or access method is disabled.')
    if quick and name == 'money':
        # Money-game players choose stakes only. Preserve the UI's preferred
        # defaults, with the configured first option as fallback, for every client.
        points = 1
        clock = 'normal' if 'normal' in profile['time_controls'] else profile['time_controls'][0]
        doubling = True if True in profile['doubling_options'] else profile['doubling_options'][0]
    else:
        points = data.get('target_points', 5)
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


def create_or_match(request, *, quick=False, match_search=False):
    from .api import _serialize_head_to_head, _new_table_code, _create_friend_table, FriendCodesUnavailable
    try:
        data = json.loads(request.body or '{}')
        if not isinstance(data, dict):
            raise ValidationError('Expected a game settings object.')
        if 'game_format' not in data:
            return JsonResponse({
                'code': 'game_format_required',
                'detail': 'Refresh the game screen to review the current rules before creating a game.',
            }, status=400)
        # Finish upgrade cleanup before taking matchmaking's user locks. Keeping
        # cleanup locks while acquiring a different pair can invert wallet order.
        from .search_lifecycle import reconcile_searches_locked
        reconcile_searches_locked()
        with transaction.atomic():
            settings = DirectPlaySettings.objects.select_for_update().get(pk=1)
            name, profile, stakes, points, clock, doubling = quote(settings, data, quick, match_search)
            fields = dict(game_format=name, rules_snapshot=profile, target_points=points,
                          time_control=clock, doubling_enabled=doubling, is_quick_match=quick)
            if quick:
                queue = HeadToHeadTable.objects.select_for_update(of=('self',)).filter(
                    game_format=name, target_points=points, time_control=clock, doubling_enabled=doubling,
                    is_quick_match=True, status='open', guest__isnull=True).select_related('host').order_by('created_at', 'pk')
                def _snapshot_eq(a, b):
                    return {k: v for k, v in (a or {}).items() if not str(k).startswith('dynamic_')} == {k: v for k, v in (b or {}).items() if not str(k).startswith('dynamic_')}
                for existing in queue.filter(host=request.user):
                    if _snapshot_eq(existing.rules_snapshot, profile) and [money(x) for x in existing.quick_stakes] == stakes:
                        return JsonResponse({**_serialize_head_to_head(existing), 'matched': False})
                for candidate in queue.exclude(host=request.user):
                    common = sorted(set(stakes) & {money(x) for x in candidate.quick_stakes})
                    if not common or not _snapshot_eq(candidate.rules_snapshot, profile):
                        continue
                    list(User.objects.select_for_update().filter(pk__in=sorted((candidate.host_id, request.user.pk))).order_by('pk'))
                    guest_balance = money(WalletTransaction.balance_for_user(request.user))
                    # Dynamic check: minimum exposure
                    affordable_common = []
                    for s in common:
                        # for money, check can_join with Mars=2
                        if candidate.game_format == 'money':
                            params = calculate_dynamic_params(guest_balance, s, candidate.rules_snapshot, mars_enabled=True)
                            if params['can_join']:
                                affordable_common.append(s)
                        else:
                            if guest_balance >= money(s):
                                affordable_common.append(s)
                    if not affordable_common:
                        continue
                    stake = affordable_common[0]
                    if candidate.game_format == 'money':
                        guest_params = calculate_dynamic_params(guest_balance, stake, candidate.rules_snapshot, mars_enabled=True)
                        # Money-game caps are dynamic and derived from both players'
                        # current balance exposure, not the static profile cap.
                        host_params = calculate_dynamic_params(
                            money(WalletTransaction.balance_for_user(candidate.host)),
                            stake,
                            candidate.rules_snapshot,
                            mars_enabled=True,
                        )
                        host_max_cube = host_params['max_cube']
                        shared_max_cube = min(host_max_cube, guest_params['max_cube'])
                        mars_mult = guest_params.get('mars_multiplier', 2)
                        shared_reserve_mult = mars_mult * shared_max_cube
                        shared_max_exp = money(stake * shared_reserve_mult)
                        # cap by guest's max_exposure (which already caps by loss if needed)
                        shared_max_exp = min(shared_max_exp, guest_params['max_exposure'])
                        if held(candidate, candidate.host) < shared_max_exp:
                            continue
                        try:
                            reserve(candidate, request.user, shared_max_exp)
                        except ValidationError:
                            continue
                        if candidate.settlement is None:
                            candidate.settlement = {}
                        candidate.settlement['dynamic_max_cube'] = shared_max_cube
                        candidate.settlement['dynamic_reserve_multiplier'] = shared_reserve_mult
                        candidate.settlement['dynamic_max_exposure'] = str(shared_max_exp)
                    else:
                        # Match: stake fixed, no Mars multiplier
                        if guest_balance < money(stake):
                            continue
                        shared_max_exp = money(stake)
                        if held(candidate, candidate.host) < shared_max_exp:
                            continue
                        try:
                            reserve(candidate, request.user, shared_max_exp)
                        except ValidationError:
                            continue
                        # no dynamic needed for match
                    candidate.amount = stake
                    candidate.fee_per_player = money(stake * candidate.fee_percent / 100)
                    candidate.guest = request.user
                    candidate.status = 'ready'
                    candidate.save(update_fields=['amount', 'fee_per_player', 'guest', 'status', 'updated_at', 'settlement'])
                    from .push import queue_guest_joined_push
                    queue_guest_joined_push(candidate)
                    return JsonResponse({**_serialize_head_to_head(candidate), 'matched': True})
            User.objects.select_for_update().get(pk=request.user.pk)
            guest_balance = money(WalletTransaction.balance_for_user(request.user))
            # For money, use dynamic params for max stake
            if name == 'money':
                # check minimum exposure for max stake
                host_params = calculate_dynamic_params(guest_balance, max(stakes), profile, mars_enabled=True)
                if not host_params['can_join']:
                    shortfall = money(host_params['max_exposure'] - guest_balance)
                    return JsonResponse({
                        "detail": f"Insufficient coins: {host_params['max_exposure']} required, {guest_balance} available.",
                        "code": "insufficient_coins",
                        "required": str(host_params['max_exposure']),
                        "balance": str(guest_balance),
                        "shortfall": str(shortfall),
                    }, status=400)
                max_required = host_params['max_exposure']
            else:
                max_required = money(max(stakes))
                if guest_balance < max_required:
                    shortfall = money(max_required - guest_balance)
                    return JsonResponse({
                        "detail": f"Insufficient coins: {max_required} required, {guest_balance} available.",
                        "code": "insufficient_coins",
                        "required": str(max_required),
                        "balance": str(guest_balance),
                        "shortfall": str(shortfall),
                    }, status=400)
            # Use pure profile for snapshot (do not pollute with dynamic)
            snapshot = copy.deepcopy(profile)
            fields.update(mode='match' if quick else data.get('mode', 'match'), host=request.user,
                          amount=stakes[0], quick_stakes=[str(x) for x in stakes] if quick else [],
                          fee_percent=money(profile['fee_percent']),
                          fee_per_player=money(stakes[0] * money(profile['fee_percent']) / 100),
                          rules_snapshot=snapshot)
            table = _create_friend_table(**fields) if fields['mode'] == 'friend' else HeadToHeadTable.objects.create(code=_new_table_code(), **fields)
            # store dynamic values for later shared calc (in settlement, not snapshot)
            if name == 'money':
                table.settlement = {
                    'dynamic_max_cube': host_params['max_cube'],
                    'dynamic_reserve_multiplier': host_params['reserve_multiplier'],
                    'dynamic_max_exposure': str(host_params['max_exposure']),
                }
                table.save(update_fields=['settlement'])
            try:
                # Reserve dynamic max exposure for money, else fixed
                reserve_amt = max_required if name == 'money' else money(max(stakes))
                reserve(table, request.user, reserve_amt)
            except ValidationError as e:
                msg = '; '.join(getattr(e, 'messages', [str(e)]))
                if 'Insufficient coins' in msg:
                    table.delete()
                    return JsonResponse({
                        "detail": msg,
                        "code": "insufficient_coins",
                        "required": str(max_required),
                        "balance": str(guest_balance),
                        "shortfall": str(money(max_required - guest_balance)),
                    }, status=400)
                raise
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
    from .push import queue_guest_joined_push
    queue_guest_joined_push(table)


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
            dynamic_max_cube = (table.settlement or {}).get('dynamic_max_cube')
            if dynamic_max_cube is None:
                dynamic_max_cube = table.rules_snapshot.get('max_cube', 64)
            if type(cube) is not int or cube not in (1, 2, 4, 8, 16, 32, 64) or cube > dynamic_max_cube:
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
