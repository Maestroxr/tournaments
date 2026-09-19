"""Session-authenticated bridge to the analysis service."""
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from django.conf import settings
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from gamelink.models import GameLink
from tournaments.models import HeadToHeadTable


def allowed_rooms(user):
    rooms = set(HeadToHeadTable.objects.filter(Q(host=user) | Q(guest=user))
                .exclude(external_room_id="").values_list("external_room_id", flat=True))
    rooms.update(GameLink.objects.filter(Q(fixture__player1__user=user) | Q(fixture__player2__user=user))
                 .exclude(external_room_id="").values_list("external_room_id", flat=True))
    return rooms


def read_results(path, params=None):
    token = getattr(settings, "ANALYSIS_API_TOKEN", "") or os.environ.get("ANALYSIS_API_TOKEN", "")
    base = getattr(settings, "ANALYSIS_SERVICE_URL", "") or os.environ.get("ANALYSIS_SERVICE_URL", "http://127.0.0.1:8002")
    if not token:
        raise ValueError("Analysis connection is not configured.")
    url = f"{base.rstrip('/')}/api/v1/internal/results/{path}"
    if params:
        url += "?" + urlencode(params)
    with urlopen(Request(url, headers={"Authorization": f"Bearer {token}"}), timeout=15) as response:
        return json.load(response)


@require_GET
def analysis_results(request, analysis_id=None):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    rooms = allowed_rooms(request.user)
    try:
        if analysis_id is not None:
            data = read_results(f"{analysis_id}/")
            if not request.user.is_staff and data.get("room_id") not in rooms:
                return JsonResponse({"detail": "Analysis not found."}, status=404)
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
    except HTTPError as exc:
        return JsonResponse({"detail": "Analysis not found." if exc.code == 404 else "Analysis service unavailable."}, status=404 if exc.code == 404 else 503)
    except (URLError, TimeoutError, ValueError, OSError):
        return JsonResponse({"detail": "Analysis service unavailable."}, status=503)
    response = JsonResponse(data)
    response["Cache-Control"] = "private, no-store"
    return response
