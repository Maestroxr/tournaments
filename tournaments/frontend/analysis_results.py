"""Session-authenticated bridge to the analysis service."""
import json
import os
import logging
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from django.conf import settings
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from gamelink.models import GameLink, PracticePurchase
from tournaments.models import HeadToHeadTable

logger = logging.getLogger(__name__)
_unavailable_until = {}


class AnalysisUnavailable(ValueError):
    def __init__(self, reason, *, retryable=True):
        self.reason = reason
        self.retryable = retryable
        super().__init__('Analysis service unavailable.')


def unavailable_response(reason='analysis_service_unavailable', *, retryable=True):
    response = JsonResponse({'detail': 'Analysis service unavailable.',
                             'code': reason, 'retryable': retryable}, status=503)
    response['Retry-After'] = '30'
    response['Cache-Control'] = 'private, no-store'
    return response


def allowed_rooms(user):
    rooms = set(HeadToHeadTable.objects.filter(Q(host=user) | Q(guest=user))
                .exclude(external_room_id="").values_list("external_room_id", flat=True))
    rooms.update(GameLink.objects.filter(Q(fixture__player1__user=user) | Q(fixture__player2__user=user))
                 .exclude(external_room_id="").values_list("external_room_id", flat=True))
    rooms.update(str(room) for room in PracticePurchase.objects.filter(
        user=user, room_id__isnull=False).values_list("room_id", flat=True))
    return rooms


def read_results(path, params=None, *, payload=None):
    token = getattr(settings, "ANALYSIS_API_TOKEN", "") or os.environ.get("ANALYSIS_API_TOKEN", "")
    base = getattr(settings, "ANALYSIS_SERVICE_URL", "") or os.environ.get("ANALYSIS_SERVICE_URL", "http://127.0.0.1:8002")
    if not token:
        raise AnalysisUnavailable('analysis_not_configured', retryable=False)
    if time.monotonic() < _unavailable_until.get(base, 0):
        raise AnalysisUnavailable('analysis_service_cooldown')
    url = f"{base.rstrip('/')}/api/v1/internal/results/{path}"
    if params:
        url += "?" + urlencode(params)
    body = json.dumps(payload).encode() if payload is not None else None
    started = time.monotonic()
    try:
        with urlopen(Request(url, data=body, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}),
                     timeout=getattr(settings, 'ANALYSIS_READ_TIMEOUT_SECONDS', 3)) as response:
            result = json.load(response)
        _unavailable_until.pop(base, None)
        return result
    except HTTPError as exc:
        if exc.code >= 500 or exc.code == 429:
            _unavailable_until[base] = time.monotonic() + 30
        raise
    except (URLError, TimeoutError, OSError):
        _unavailable_until[base] = time.monotonic() + 30
        logger.warning('event=analysis_provider_unavailable duration_ms=%s',
                       round((time.monotonic() - started) * 1000, 1))
        raise


@require_http_methods(["GET", "POST"])
def analysis_results(request, analysis_id=None):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    payload = None
    if request.method == "POST":
        try:
            payload = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({"detail": "Invalid JSON."}, status=400)
        if not analysis_id or not isinstance(payload, dict) or payload.get("eval_level") not in ("1ply", "2ply", "3ply"):
            return JsonResponse({"detail": "Choose 1ply, 2ply or 3ply for a match."}, status=400)
    rooms = allowed_rooms(request.user)
    try:
        if analysis_id is not None:
            data = read_results(f"{analysis_id}/")
            if not request.user.is_staff and data.get("room_id") not in rooms:
                return JsonResponse({"detail": "Analysis not found."}, status=404)
            if payload is not None:
                data = read_results(f"{analysis_id}/", payload={"eval_level": payload["eval_level"]})
        else:
            room = request.GET.get("room")
            if room:
                if not request.user.is_staff and room not in rooms:
                    return JsonResponse({"detail": "Analysis not found."}, status=404)
                rooms = {room}
            if not rooms and not request.user.is_staff:
                return JsonResponse({"matches": []})
            params = [("staff", "1")] if request.user.is_staff and not room else [("room", room) for room in rooms]
            data = read_results("", params)
            # Defense in depth: never forward an unrelated match to a player.
            if not request.user.is_staff or room:
                data["matches"] = [m for m in data["matches"] if m.get("room_id") in rooms]
    except AnalysisUnavailable as exc:
        return unavailable_response(exc.reason, retryable=exc.retryable)
    except HTTPError as exc:
        if exc.code == 409:
            return JsonResponse({"detail": "Analysis is already queued or processing."}, status=409)
        return JsonResponse({'detail': 'Analysis not found.'}, status=404) if exc.code == 404 else unavailable_response()
    except (URLError, TimeoutError, ValueError, OSError):
        return unavailable_response()
    response = JsonResponse(data, status=202 if payload is not None else 200)
    response["Cache-Control"] = "private, no-store"
    return response
