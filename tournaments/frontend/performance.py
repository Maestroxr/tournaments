"""Session-authenticated, read-only historical performance for the profile."""
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from gamelink.models import LinkedAccount
from gamelink.signing import sign_command_body


@require_GET
def player_performance(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    identity = LinkedAccount.objects.filter(user=request.user).values_list("external_id", flat=True).first()
    if identity is None:
        response = JsonResponse({"pr": None, "matches": 0, "decisions": 0})
    else:
        base = getattr(settings, "GAMELINK_BACKGAMMON_URL", "").rstrip("/")
        if not settings.GAMELINK_ENABLED or not base:
            response = JsonResponse({"detail": "Performance unavailable."}, status=503)
        else:
            try:
                raw = json.dumps({"purpose": "player_performance", "sub": str(identity),
                                  "iss": settings.GAMELINK_ISSUER}, separators=(",", ":")).encode()
                timestamp = str(int(time.time()))
                headers = {"Content-Type": "application/json",
                           "X-Gamelink-Issuer": settings.GAMELINK_ISSUER,
                           "X-Gamelink-Timestamp": timestamp,
                           "X-Gamelink-Signature": sign_command_body(raw, timestamp)}
                with urlopen(Request(base + "/api/link/performance/", data=raw, headers=headers), timeout=5) as result:
                    data = json.load(result)
                response = JsonResponse({key: data[key] for key in ("pr", "matches", "decisions")})
            except (HTTPError, URLError, OSError, RuntimeError, ValueError, KeyError, TypeError):
                response = JsonResponse({"detail": "Performance unavailable."}, status=503)
    response["Cache-Control"] = "private, no-store"
    return response
