"""Idempotent paid AI matches. A prepared room cannot be played before payment."""
import json
import time
import uuid
from decimal import Decimal
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import URLError

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponseRedirect, JsonResponse
from django.views import View

from tournaments.models import DirectPlaySettings, WalletTransaction
from .models import LinkedAccount, PracticePurchase
from .signing import _ticket_secret

POINTS = [1, 3, 5, 7, 9, 11, 15, 21, 25]
TIMES = ['none', 'fast', 'normal', 'slow']


def signed_payload(user, purchase, purpose, **extra):
    payload = {'v': 1, 'iss': settings.GAMELINK_ISSUER, 'aud': settings.GAMELINK_AUDIENCE,
        'jti': str(uuid.uuid4()), 'exp': int(time.time()) + 120,
        'sub': LinkedAccount.external_id_for(user), 'name': user.username,
        'purchase_id': str(purchase.id), 'purpose': purpose, **purchase.options, **extra}
    return signing.dumps(payload, key=_ticket_secret(), salt='gamelink.practice.v1', compress=False)


def prepare_room(base, token):
    body = json.dumps({'ticket': token}).encode()
    with urlopen(Request(base + '/api/link/practice/prepare/', data=body,
                        headers={'Content-Type': 'application/json'}), timeout=10) as response:
        return json.load(response)


class StartPracticeView(LoginRequiredMixin, View):
    http_method_names = ['get', 'post']

    def get(self, request):
        row = DirectPlaySettings.load()
        response = JsonResponse({'fee': str(row.ai_game_fee), 'target_points': POINTS,
            'time_controls': TIMES, 'balance': str(WalletTransaction.balance_for_user(request.user))})
        response['Cache-Control'] = 'private, no-store'
        return response

    def post(self, request):
        base = getattr(settings, 'GAMELINK_BACKGAMMON_URL', '').rstrip('/')
        if not settings.GAMELINK_ENABLED or not base:
            return JsonResponse({'error': 'Practice unavailable'}, status=503)
        try:
            data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
            request_id = uuid.UUID(data['request_id'])
            options = {'difficulty': data.get('difficulty'), 'tp': data.get('target_points'),
                       'tc': data.get('time_control'), 'dbl': data.get('doubling_enabled')}
            if (options['difficulty'] not in ('easy', 'medium', 'hard')
                    or type(options['tp']) is not int or options['tp'] not in POINTS
                    or options['tc'] not in TIMES or type(options['dbl']) is not bool):
                raise ValueError('Invalid settings')
            quoted_fee = Decimal(str(data['fee']))
            if not quoted_fee.is_finite() or quoted_fee < 0:
                raise ValueError('Invalid price')
        except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError):
            return JsonResponse({'error': 'Invalid practice settings'}, status=400)
        # Persist the request before contacting the game service: a lost HTTP
        # response can be retried without losing its room or charging twice.
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            purchase = PracticePurchase.objects.filter(pk=request_id).first()
            if purchase and purchase.user_id != request.user.pk:
                return JsonResponse(status=403, data={'error': 'Invalid purchase'})
            if purchase is None:
                fee = DirectPlaySettings.load().ai_game_fee
                if quoted_fee != fee:
                    return JsonResponse({'error': 'Price changed. Refresh the practice page.', 'code': 'price_changed'}, status=409)
                purchase = PracticePurchase.objects.create(id=request_id, user=request.user, options=options, fee=fee)
        try:
            prepared = prepare_room(base, signed_payload(request.user, purchase, 'prepare'))
            room_id = uuid.UUID(prepared['room_id'])
            prepared_purchase = prepared.get('purchase_id')
            with transaction.atomic():
                get_user_model().objects.select_for_update().get(pk=request.user.pk)
                if prepared_purchase is not None:
                    purchase = PracticePurchase.objects.select_for_update().get(
                        id=uuid.UUID(prepared_purchase), user=request.user)
                    if not purchase.paid:
                        if purchase.fee != quoted_fee:
                            if quoted_fee != DirectPlaySettings.load().ai_game_fee:
                                return JsonResponse({'error': 'Price changed. Refresh the practice page.', 'code': 'price_changed'}, status=409)
                            purchase.fee = quoted_fee
                        if WalletTransaction.balance_for_user(request.user) < purchase.fee:
                            return JsonResponse({'error': 'Not enough 6B coins.', 'code': 'insufficient_funds'}, status=402)
                        if purchase.fee:
                            purchase.wallet_entry = WalletTransaction.create_entry(user=request.user,
                                amount=-purchase.fee, kind=WalletTransaction.KIND_AI_GAME_FEE,
                                note=f'Open Sage match {room_id}')
                        purchase.paid = True
                        purchase.room_id = room_id
                        purchase.save(update_fields=['paid', 'room_id', 'wallet_entry', 'fee'])
                    elif purchase.room_id != room_id:
                        raise ValueError('Room mismatch')
                else:
                    purchase.room_id = room_id
                    purchase.save(update_fields=['room_id'])
                # Legacy free sessions remain resumable without a new fee.
                token = signed_payload(request.user, purchase, 'enter', room_id=str(room_id))
        except ValidationError:
            return JsonResponse({'error': 'Not enough 6B coins.', 'code': 'insufficient_funds'}, status=402)
        except (URLError, TimeoutError, OSError, ValueError, KeyError, PracticePurchase.DoesNotExist):
            return JsonResponse({'error': 'Could not prepare the game. Retry safely; no duplicate charge.', 'code': 'unavailable'}, status=503)
        url = f'{base}/api/link/practice/?ticket={quote(token)}'
        response = JsonResponse({'url': url}) if request.content_type == 'application/json' else HttpResponseRedirect(url)
        response['Cache-Control'] = 'no-store'
        response['Referrer-Policy'] = 'no-referrer'
        return response
