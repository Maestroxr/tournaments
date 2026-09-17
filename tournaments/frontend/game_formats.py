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

    # Money-game exposure is negotiated dynamically between both players
    # and stored on the table settlement.
    settlement = table.settlement or {}

    if table.game_format == 'money':
        dynamic_max_exposure = settlement.get('dynamic_max_exposure')
        if dynamic_max_exposure is not None:
            return money(dynamic_max_exposure)

        dynamic_multiplier = settlement.get('dynamic_reserve_multiplier')
        if dynamic_multiplier is not None:
            return money(stake * dynamic_multiplier)

    # Backward compatibility for older tables.
    snap = table.rules_snapshot or {}

    if 'dynamic_reserve_multiplier' in snap:
        return money(stake * snap['dynamic_reserve_multiplier'])

    if 'reserve_multiplier' in snap:
        return money(stake * snap['reserve_multiplier'])

    multiplier = (
        snap.get('loss_limit_multiplier', 8)
        if table.game_format == 'money'
        else 1
    )

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
    net = (
        table.wallet_transactions
        .filter(
            user=user,
            kind__in=(
                WalletTransaction.KIND_HEAD_TO_HEAD_ENTRY,
                WalletTransaction.KIND_FRIEND_GAME_FEE,
                WalletTransaction.KIND_HEAD_TO_HEAD_REFUND,
            ),
        )
        .aggregate(total=Sum('amount'))['total']
        or Decimal('0')
    )
    return money(max(Decimal('0'), -net))


def reserve(table, user, amount):
    balance = money(WalletTransaction.balance_for_user(user))
    if balance < amount:
        raise ValidationError(f'Insufficient coins: {amount} required, {balance} available for reservation.')
    kind = (
        WalletTransaction.KIND_FRIEND_GAME_FEE
        if table.is_friend_game
        else WalletTransaction.KIND_HEAD_TO_HEAD_ENTRY
    )
    WalletTransaction.create_entry(user=user, amount=-amount, kind=kind,
                                   head_to_head_table=table, note=f'Reserved for {table.game_format} table {table.code}')


def quote(settings, data, quick, match_search=False):
    name = data.get('game_format')
    if name not in ('match', 'money'):
        raise ValidationError('Unknown game format.')
    profile = settings.format_profiles[name]
    mode = data.get('mode', 'match')
    access = 'quick' if quick else 'private' if mode == 'friend' else 'public'
    if mode not in ('match', 'friend'):
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
        required_rules = (
            'target_points',
            'time_control',
            'doubling_enabled',
        )

        if any(key not in data for key in required_rules):
            raise ValidationError(
                'Missing required game rules. Refresh the game screen and try again.'
            )

        points = data['target_points']
        clock = data['time_control']
        doubling = data['doubling_enabled']

        if type(doubling) is not bool:
            raise ValidationError('Select the available rules for this format.')

        if name == 'match' and points == 1:
            doubling = False
        elif mode == 'friend' and points == 1:
            doubling = False
    if mode == 'friend' and points == 1:
        if type(points) is not int or points not in profile['target_points'] or clock not in profile['time_controls']:
            raise ValidationError('Select the available rules for this format.')
        if type(doubling) is not bool:
            raise ValidationError('Select the available rules for this format.')
    else:
        if (type(points) is not int or points not in profile['target_points']
                or clock not in profile['time_controls'] or type(doubling) is not bool
                or (doubling not in profile['doubling_options']
                    and not (name == 'match' and points == 1))):
            raise ValidationError('Select the available rules for this format.')
    if mode == 'friend':
        stakes = [settings.friend_fee_for(points)]
    else:
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
            name, profile, stakes, points, clock, doubling = quote(
                settings, data, quick, match_search)
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
                    common = sorted(set(stakes) & {money(
                        x) for x in candidate.quick_stakes})
                    if not common or not _snapshot_eq(candidate.rules_snapshot, profile):
                        continue
                    list(User.objects.select_for_update().filter(pk__in=sorted(
                        (candidate.host_id, request.user.pk))).order_by('pk'))
                    guest_balance = money(
                        WalletTransaction.balance_for_user(request.user))
                    # Dynamic check: minimum exposure
                    affordable_common = []
                    for s in common:
                        # for money, check can_join with Mars=2
                        if candidate.game_format == 'money':
                            params = calculate_dynamic_params(
                                guest_balance, s, candidate.rules_snapshot, mars_enabled=True)
                            if params['can_join']:
                                affordable_common.append(s)
                        else:
                            if guest_balance >= money(s):
                                affordable_common.append(s)
                    if not affordable_common:
                        continue
                    stake = affordable_common[0]
                    if candidate.game_format == 'money':
                        guest_params = calculate_dynamic_params(
                            guest_balance, stake, candidate.rules_snapshot, mars_enabled=True)
                        host_available = money(
                            WalletTransaction.balance_for_user(candidate.host)
                            + held(candidate, candidate.host)
                        )
                        host_params = calculate_dynamic_params(
                            host_available,
                            stake,
                            candidate.rules_snapshot,
                            mars_enabled=True,
                        )
                        print("=== DOUBLE DEBUG ===")
                        print("stake:", stake)
                        print("host_balance:", host_available)
                        print("host_params:", host_params)
                        print("guest_balance:", guest_balance)
                        print("guest_params:", guest_params)
                        shared_max_cube = min(
                            host_params['max_cube'], guest_params['max_cube']
                        )
                        print("shared_max_cube:", shared_max_cube)
                        print("====================")
                        shared_reserve_multiplier = 2 * shared_max_cube
                        shared_max_exposure = money(stake * shared_reserve_multiplier)
                        host_held = held(candidate, candidate.host)
                        if host_held < shared_max_exposure:
                            continue
                        try:
                            reserve(candidate, request.user, shared_max_exposure)
                        except ValidationError:
                            continue
                        if host_held > shared_max_exposure:
                            WalletTransaction.create_entry(
                                user=candidate.host,
                                amount=money(host_held - shared_max_exposure),
                                kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND,
                                head_to_head_table=candidate,
                                note='Shared max normalized: host excess reservation released',
                            )
                        if candidate.settlement is None:
                            candidate.settlement = {}
                        candidate.settlement['dynamic_max_cube'] = shared_max_cube
                        candidate.settlement['dynamic_reserve_multiplier'] = shared_reserve_multiplier
                        candidate.settlement['dynamic_max_exposure'] = str(
                            shared_max_exposure)
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
                    candidate.fee_per_player = money(
                        stake * candidate.fee_percent / 100)
                    candidate.guest = request.user
                    candidate.status = 'ready'
                    candidate.save(update_fields=[
                                   'amount', 'fee_per_player', 'guest', 'status', 'updated_at', 'settlement'])
                    from .push import queue_guest_joined_push
                    queue_guest_joined_push(candidate)
                    return JsonResponse({**_serialize_head_to_head(candidate), 'matched': True})
            User.objects.select_for_update().get(pk=request.user.pk)
            guest_balance = money(
                WalletTransaction.balance_for_user(request.user))
            # For money, use dynamic params for max stake
            if name == 'money':
                # check minimum exposure for max stake
                host_params = calculate_dynamic_params(
                    guest_balance, max(stakes), profile, mars_enabled=True)
                if not host_params['can_join']:
                    shortfall = money(
                        host_params['max_exposure'] - guest_balance)
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
            mode_val = data.get('mode', 'match') if not quick else 'match'
            if mode_val == 'friend':
                friend_cost = settings.friend_fee_for(points)
                fields.update(mode='friend', host=request.user,
                              amount=friend_cost, quick_stakes=[],
                              fee_percent=money(Decimal('0')),
                              fee_per_player=friend_cost,
                              rules_snapshot=snapshot)
            else:
                fields.update(mode='match' if quick else data.get('mode', 'match'), host=request.user,
                              amount=stakes[0], quick_stakes=[
                                  str(x) for x in stakes] if quick else [],
                              fee_percent=money(profile['fee_percent']),
                              fee_per_player=money(
                                  stakes[0] * money(profile['fee_percent']) / 100),
                              rules_snapshot=snapshot)
            table = _create_friend_table(
                **fields) if fields['mode'] == 'friend' else HeadToHeadTable.objects.create(code=_new_table_code(), **fields)
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
                reserve_amt = max_required if name == 'money' else money(
                    max(stakes))
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


@transaction.atomic
def create_rematch_table(source):
    from django.contrib.auth.models import User
    import copy
    # lock users in order
    if not source.guest_id:
        raise ValidationError('Rematch requires two players')
    user_ids = sorted([source.host_id, source.guest_id])
    list(User.objects.select_for_update().filter(pk__in=user_ids).order_by('pk'))
    # reject if either already has active table
    active_statuses = [HeadToHeadTable.STATUS_OPEN, HeadToHeadTable.STATUS_READY, HeadToHeadTable.STATUS_PLAYING]
    for uid in user_ids:
        if HeadToHeadTable.objects.filter(
            host_id=uid, status__in=active_statuses
        ).exclude(pk=source.pk).exists() or HeadToHeadTable.objects.filter(
            guest_id=uid, status__in=active_statuses
        ).exclude(pk=source.pk).exists():
            raise ValidationError('Player already in active game')
    # copy contract settings
    from .api import _new_table_code
    new_code = _new_table_code()
    # friend check via is_friend_game property would need instance, use mode
    is_friend = source.mode == HeadToHeadTable.MODE_FRIEND
    new_table = HeadToHeadTable(
        code=new_code,
        host=source.host,
        guest=source.guest,
        mode=source.mode,
        game_format=source.game_format,
        target_points=source.target_points,
        time_control=source.time_control,
        doubling_enabled=source.doubling_enabled,
        rules_snapshot=copy.deepcopy(source.rules_snapshot),
        amount=source.amount,
        fee_percent=source.fee_percent,
        fee_per_player=source.fee_per_player,
        is_quick_match=source.is_quick_match,
        status=HeadToHeadTable.STATUS_READY,
    )
    if source.game_format == 'money':
        host_bal = WalletTransaction.balance_for_user(source.host)
        guest_bal = WalletTransaction.balance_for_user(source.guest)
        host_params = calculate_dynamic_params(host_bal, source.amount, source.rules_snapshot, mars_enabled=True, is_quick=True)
        guest_params = calculate_dynamic_params(guest_bal, source.amount, source.rules_snapshot, mars_enabled=True, is_quick=True)
        if not host_params['can_join'] or not guest_params['can_join']:
            raise ValidationError('Insufficient funds for rematch')
        shared_max_cube = min(host_params['max_cube'], guest_params['max_cube'])
        shared_reserve_multiplier = 2 * shared_max_cube
        shared_max_exposure = money(source.amount * shared_reserve_multiplier)
        new_table.settlement = {
            'dynamic_max_cube': shared_max_cube,
            'dynamic_reserve_multiplier': shared_reserve_multiplier,
            'dynamic_max_exposure': str(shared_max_exposure),
        }
        new_table.save()
        reserve(new_table, source.host, shared_max_exposure)
        reserve(new_table, source.guest, shared_max_exposure)
        return new_table
    elif source.game_format == 'match' and not is_friend:
        required = money(source.amount)
        host_bal = WalletTransaction.balance_for_user(source.host)
        guest_bal = WalletTransaction.balance_for_user(source.guest)
        if host_bal < required or guest_bal < required:
            raise ValidationError('Insufficient funds for rematch')
        new_table.settlement = {}
        new_table.save()
        reserve(new_table, source.host, required)
        reserve(new_table, source.guest, required)
        return new_table
    else:  # friend
        required = money(source.fee_per_player)
        host_bal = WalletTransaction.balance_for_user(source.host)
        guest_bal = WalletTransaction.balance_for_user(source.guest)
        if host_bal < required or guest_bal < required:
            raise ValidationError('Insufficient funds for rematch')
        new_table.settlement = {}
        new_table.save()
        reserve(new_table, source.host, required)
        reserve(new_table, source.guest, required)
        return new_table


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
        if table.is_friend_game:
            transfer = money(0)
            fee = money(0)
        else:
            fee = money(transfer * table.fee_percent / 100)
    for player in players:
        if cancelled:
            release = reserves[player.pk]
        elif table.is_friend_game:
            release = Decimal('0')
        else:
            release = reserves[player.pk] if player == winner else reserves[player.pk] - transfer
        if release:
            WalletTransaction.create_entry(user=player, amount=release, kind=WalletTransaction.KIND_HEAD_TO_HEAD_REFUND,
                                           head_to_head_table=table, note='Unused game reservation released')
    if winner and not table.is_friend_game and transfer > fee:
        WalletTransaction.create_entry(user=winner, amount=transfer - fee, kind=WalletTransaction.KIND_HEAD_TO_HEAD_PRIZE,
                                       head_to_head_table=table, note=f'Game winnings; fee {fee}')
    table.external_room_id = body['room_id']
    table.winner = winner
    table.status = 'cancelled' if cancelled else 'completed'
    table.completed_at = timezone.now()
    table.settlement = {'transfer': str(transfer), 'fee': str(fee), 'result': result, 'reservation_released': True}
    table.save(update_fields=['external_room_id', 'winner', 'status', 'completed_at', 'settlement', 'updated_at'])
