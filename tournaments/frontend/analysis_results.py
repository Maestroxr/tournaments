"""Session-authenticated bridge to the analysis service."""
import json
import os
import logging
import time
import uuid
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from django.conf import settings
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import cache_control
from django.utils.crypto import salted_hmac

from gamelink.models import GameLink, PracticePurchase
from tournaments.models import HeadToHeadTable
from .list_pages import page_bounds

logger = logging.getLogger(__name__)
_unavailable_until = {}
DIRECT_ROOM_LIMIT = 32
SCOPE_CHUNK_SIZE = 128


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


def read_results(path, params=None, *, payload=None, headers=None, method=None):
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
        request_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        request_headers.update(headers or {})
        with urlopen(Request(url, data=body, headers=request_headers, method=method),
                     timeout=getattr(settings, 'ANALYSIS_READ_TIMEOUT_SECONDS', 3)) as response:
            result = {} if getattr(response, "status", None) == 204 else json.load(response)
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


def scoped_results(request, rooms, *, limit, offset):
    """Upload a fresh ACL snapshot in bounded messages, then query one page.

    The binding includes this session, user and request. Scope IDs never cross
    the browser boundary or survive an authorization refresh. Initial upload
    still visits the room history; no single request grows with that history.
    """
    session_key = getattr(getattr(request, "session", None), "session_key", "") or ""
    principal = getattr(request.user, "pk", "")
    binding = salted_hmac(
        "analysis-result-scope", f"{principal}:{session_key}:{uuid.uuid4()}",
        algorithm="sha256",
    ).hexdigest()
    headers = {"X-Analysis-Scope-Binding": binding}
    scope_id = None
    try:
        created = read_results("scopes/", payload={"room_count": len(rooms)}, headers=headers)
        scope_id = str(uuid.UUID(created["id"]))
        path = f"scopes/{scope_id}/"
        room_list = sorted(rooms)
        for start in range(0, len(room_list), SCOPE_CHUNK_SIZE):
            read_results(path, payload={"offset": start, "rooms": room_list[start:start + SCOPE_CHUNK_SIZE]}, headers=headers)
        read_results(path, payload={"finalize": True}, headers=headers)
        return read_results("", [("scope", scope_id), ("limit", limit), ("offset", offset)], headers=headers)
    finally:
        if scope_id:
            try:
                read_results(f"scopes/{scope_id}/", headers=headers, method="DELETE")
            except (AnalysisUnavailable, HTTPError, URLError, TimeoutError, OSError, ValueError):
                # An interrupted request is cleaned up by server-side expiry.
                logger.warning("event=analysis_scope_cleanup_deferred")
@require_http_methods(["GET", "POST"])
def analysis_results(request, analysis_id=None):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    if analysis_id is None and request.method == "GET":
        try:
            offset, limit = page_bounds(request.GET)
        except ValueError as exc:
            return JsonResponse({"detail": str(exc)}, status=400)
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
                response = JsonResponse({"matches": [], "count": 0, "next_offset": None})
                response["Cache-Control"] = "private, no-store"
                return response
            if len(rooms) > DIRECT_ROOM_LIMIT and not (request.user.is_staff and not room):
                data = scoped_results(request, rooms, limit=limit, offset=offset)
            else:
                params = [("staff", "1")] if request.user.is_staff and not room else [("room", room) for room in rooms]
                params.extend([("limit", limit), ("offset", offset)])
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
    except (URLError, TimeoutError, ValueError, OSError, KeyError, TypeError):
        return unavailable_response()
    response = JsonResponse(data, status=202 if payload is not None else 200)
    response["Cache-Control"] = "private, no-store"
    return response


@cache_control(private=True, no_store=True)
@require_http_methods(["GET"])
def analysis_record(request, analysis_id):
    """Fetch an authorized source record without loading the analysis detail."""
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    room = request.GET.get("room")
    if room:
        try:
            room = str(uuid.UUID(room))
        except (ValueError, AttributeError):
            return JsonResponse({"detail": "Analysis not found."}, status=404)
    if not request.user.is_staff and (not room or room not in allowed_rooms(request.user)):
        return JsonResponse({"detail": "Analysis not found."}, status=404)
    params = [("room", room)] if room else [("staff", "1")]
    try:
        data = read_results(f"{analysis_id}/record/", params)
        if data.get("id") != str(analysis_id) or (room and data.get("room_id") != room):
            return JsonResponse({"detail": "Analysis not found."}, status=404)
    except AnalysisUnavailable as exc:
        return unavailable_response(exc.reason, retryable=exc.retryable)
    except HTTPError as exc:
        if exc.code == 404:
            return JsonResponse({"detail": "Analysis not found."}, status=404)
        return unavailable_response()
    except (URLError, TimeoutError, ValueError, OSError, KeyError, TypeError, AttributeError):
        return unavailable_response()
    return JsonResponse(data)
