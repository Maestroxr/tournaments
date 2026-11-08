"""Read-only historical performance from the signed game service."""
import json
import math
import time
from http.client import HTTPException
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from gamelink.models import LinkedAccount
from gamelink.signing import sign_command_body


PERFORMANCE_ERRORS = (
    OSError, HTTPException, ImproperlyConfigured, RuntimeError, ValueError, KeyError, TypeError,
)


def _read_signed_performance(purpose, **subjects):
    base = getattr(settings, "GAMELINK_BACKGAMMON_URL", "").rstrip("/")
    if not settings.GAMELINK_ENABLED or not base:
        raise ImproperlyConfigured("GameLink performance is unavailable.")

    issuer = settings.GAMELINK_ISSUER
    raw = json.dumps({"purpose": purpose, **subjects, "iss": issuer}, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-Gamelink-Issuer": issuer,
        "X-Gamelink-Timestamp": timestamp,
        "X-Gamelink-Signature": sign_command_body(raw, timestamp),
    }
    request = Request(base + "/api/link/performance/", data=raw, headers=headers, method="POST")
    with urlopen(request, timeout=5) as result:
        return json.load(result)


def read_leaderboard_performance(identities):
    """Return PR by linked identity, or None if the batch is unavailable."""
    if not identities:
        return {}
    try:
        data = _read_signed_performance("leaderboard_performance", subs=identities)["players"]
        performance = {identity: data[identity]["pr"] for identity in identities}
        if any(
            pr is not None and (not isinstance(pr, str) or not math.isfinite(float(pr)))
            for pr in performance.values()
        ):
            return None
        return performance
    except PERFORMANCE_ERRORS:
        return None


@require_GET
def player_performance(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    identity = LinkedAccount.objects.filter(user=request.user).values_list("external_id", flat=True).first()
    if identity is None:
        response = JsonResponse({"pr": None, "matches": 0, "decisions": 0})
    else:
        try:
            data = _read_signed_performance("player_performance", sub=str(identity))
            response = JsonResponse({key: data[key] for key in ("pr", "matches", "decisions")})
        except PERFORMANCE_ERRORS:
            response = JsonResponse({"detail": "Performance unavailable."}, status=503)
    response["Cache-Control"] = "private, no-store"
    return response
