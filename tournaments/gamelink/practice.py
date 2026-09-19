"""Issue a practice-only ticket; no entry fee, fixture or wallet operation."""
import time
import uuid
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core import signing
from django.http import HttpResponseRedirect, JsonResponse
from django.views import View

from .models import LinkedAccount
from .signing import _ticket_secret


class StartPracticeView(LoginRequiredMixin, View):
    http_method_names = ['post']

    def post(self, request):
        base = getattr(settings, 'GAMELINK_BACKGAMMON_URL', '').rstrip('/')
        if not settings.GAMELINK_ENABLED or not base:
            return JsonResponse({'error': 'Practice unavailable'}, status=503)
        difficulty = request.POST.get('difficulty', 'hard')
        if difficulty not in ('easy', 'medium', 'hard'):
            return JsonResponse({'error': 'Invalid difficulty'}, status=400)
        payload = {'v': 1, 'iss': settings.GAMELINK_ISSUER, 'aud': settings.GAMELINK_AUDIENCE,
            'jti': str(uuid.uuid4()), 'exp': int(time.time()) + 120,
            'sub': LinkedAccount.external_id_for(request.user),
            'name': request.user.username, 'difficulty': difficulty}
        token = signing.dumps(payload, key=_ticket_secret(), salt='gamelink.practice.v1', compress=False)
        response = HttpResponseRedirect(f'{base}/api/link/practice/?ticket={quote(token)}')
        response['Cache-Control'] = 'no-store'
        response['Referrer-Policy'] = 'no-referrer'
        return response
