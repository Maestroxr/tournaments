import json
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.shortcuts import get_object_or_404
from django.db.models import Count, Q

from tournaments import models
from .forms import SignupForm, AdminUserCreateForm, CreateTournamentForm


def _serialize_tournament(t, request):
    # mirrors frontend/views.py:87 state logic
    is_joined = False
    if request.user.is_authenticated:
        is_joined = t.participations.filter(
            participant__user=request.user).exists()
    return {
        "id": t.id,
        "name": t.name,
        "state": t.state,  # draft/open/active/finished
        "status": t.state,  # alias for Vue frontend
        "published": t.published,
        "creator": t.creator.username if t.creator else None,
        "is_creator": bool(request.user.is_authenticated and t.creator_id == request.user.id),
        "is_joined": is_joined,
        "participant_count": t.participations.count(),
        # placeholders for your Vue fields (map backend -> frontend)
        "enterPrice": 0,
        "prizeMoney": 0,
        "capacity": 16,
    }


@ensure_csrf_cookie
@require_http_methods(["GET"])
def api_csrf(request):
    return JsonResponse({"detail": "CSRF cookie set"})


@require_http_methods(["GET"])
def api_me(request):
    if request.user.is_authenticated:
        return JsonResponse({"id": request.user.id, "username": request.user.username, "is_authenticated": True})
    return JsonResponse({"is_authenticated": False}, status=401)


@csrf_exempt
@require_http_methods(["POST"])
def api_login(request):
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)
    user = authenticate(request, username=data.get(
        "username"), password=data.get("password"))
    if user is None:
        return JsonResponse({"detail": "Invalid credentials"}, status=401)
    login(request, user)
    return JsonResponse({"id": user.id, "username": user.username})


@csrf_exempt
@require_http_methods(["POST"])
def api_logout(request):
    logout(request)
    return JsonResponse({"detail": "Logged out"})


@csrf_exempt
@require_http_methods(["POST"])
def api_signup(request):
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)
    form = SignupForm(data)
    if form.is_valid():
        form.save()
        user = authenticate(username=data.get("username"),
                            password=data.get("password1"))
        if user:
            login(request, user)
        return JsonResponse({"id": user.id, "username": user.username}, status=201)
    return JsonResponse({"errors": form.errors}, status=400)


@require_http_methods(["GET"])
def api_tournaments(request):
    qs = models.Tournament.objects.filter(published=True).annotate(
        fixtures=Count('stages__fixtures'),
        podium_size=Count('participations', filter=Q(
            participations__podium_position__isnull=False))
    )
    # optional ?state=open|active|finished or ?q=search
    state = request.GET.get("state")
    q = request.GET.get("q")
    if q:
        qs = qs.filter(name__icontains=q)
    tournaments = []
    for t in qs:
        # reuse state filter like IndexView
        if state and t.state != state:
            continue
        tournaments.append(_serialize_tournament(t, request))
    return JsonResponse(tournaments, safe=False)


@require_http_methods(["GET"])
def api_tournament_detail(request, pk):
    t = get_object_or_404(models.Tournament, pk=pk)
    # allow draft only for creator (like UpdateTournamentView:128)
    if t.state == "draft" and (not request.user.is_authenticated or t.creator_id != request.user.id):
        return JsonResponse({"detail": "Not found"}, status=404)
    data = _serialize_tournament(t, request)
    data["definition"] = t.definition
    data["participants"] = list(
        t.participations.values_list("participant__name", flat=True))
    return JsonResponse(data)


@csrf_exempt
@require_http_methods(["POST"])
def api_join(request, pk):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required"}, status=401)
    t = get_object_or_404(models.Tournament, pk=pk)
    if t.state != "open":
        return JsonResponse({"detail": f"Cannot join, state={t.state}"}, status=412)
    if not t.participations.filter(participant__user=request.user).exists():
        participant, _ = models.Participant.objects.get_or_create(
            user=request.user, defaults={"name": request.user.username})
        models.Participation.objects.create(
            tournament=t, participant=participant, slot_id=models.Participation.next_slot_id(t))
    return JsonResponse(_serialize_tournament(t, request))


@csrf_exempt
@require_http_methods(["POST"])
def api_withdraw(request, pk):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required"}, status=401)
    t = get_object_or_404(models.Tournament, pk=pk)
    if t.state != "open":
        return JsonResponse({"detail": f"Cannot withdraw, state={t.state}"}, status=412)
    t.participations.filter(participant__user=request.user).delete()
    return JsonResponse(_serialize_tournament(t, request))


# --- Admin API (staff only) ---

def _require_staff(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required"}, status=401)
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({"detail": "Admin required"}, status=403)
    return None


@require_http_methods(["GET", "POST"])
def api_admin_tournaments(request):
    err = _require_staff(request)
    if err:
        return err
    if request.method == "GET":
        qs = models.Tournament.objects.all().order_by("-id")
        q = request.GET.get("q")
        if q:
            qs = qs.filter(name__icontains=q)
        return JsonResponse([_serialize_tournament(t, request) for t in qs], safe=False)
    # POST create
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)
    form = CreateTournamentForm(data)
    # CreateTournamentForm expects definition as YAML string; allow dict or string
    if isinstance(data.get("definition"), dict):
        import yaml
        data["definition"] = yaml.safe_dump(data["definition"])
        form = CreateTournamentForm(data)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)
    tournament = form.create_tournament(request)
    return JsonResponse(_serialize_tournament(tournament, request), status=201)


@require_http_methods(["GET", "PUT", "DELETE"])
def api_admin_tournament_detail(request, pk):
    err = _require_staff(request)
    if err:
        return err
    t = get_object_or_404(models.Tournament, pk=pk)
    if request.method == "GET":
        data = _serialize_tournament(t, request)
        data["definition"] = t.definition
        data["participants"] = list(t.participations.values_list("participant__name", flat=True))
        return JsonResponse(data)
    if request.method == "DELETE":
        if t.state != "draft":
            return JsonResponse({"detail": f"Cannot delete, state={t.state}"}, status=412)
        t.delete()
        return JsonResponse({"detail": "Deleted"})
    # PUT update (re-create like UpdateTournamentForm)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)
    if t.state != "draft":
        return JsonResponse({"detail": f"Cannot update, state={t.state}"}, status=412)
    form = CreateTournamentForm(data)
    if isinstance(data.get("definition"), dict):
        import yaml
        data["definition"] = yaml.safe_dump(data["definition"])
        form = CreateTournamentForm(data)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)
    t.delete()
    tournament = form.create_tournament(request)
    return JsonResponse(_serialize_tournament(tournament, request))


@require_http_methods(["GET", "POST"])
def api_admin_users(request):
    err = _require_staff(request)
    if err:
        return err
    if request.method == "GET":
        qs = User.objects.all().order_by("username")
        q = request.GET.get("q")
        if q:
            qs = qs.filter(username__icontains=q)
        return JsonResponse([{"id": u.id, "username": u.username, "email": u.email, "is_staff": u.is_staff, "is_active": u.is_active} for u in qs], safe=False)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)
    form = AdminUserCreateForm(data)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)
    user = form.save()
    return JsonResponse({"id": user.id, "username": user.username, "email": user.email, "is_staff": user.is_staff}, status=201)


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
def api_admin_user_detail(request, pk):
    err = _require_staff(request)
    if err:
        return err
    u = get_object_or_404(User, pk=pk)
    if request.method == "GET":
        return JsonResponse({"id": u.id, "username": u.username, "email": u.email, "is_staff": u.is_staff, "is_active": u.is_active})
    if request.method == "DELETE":
        if u.id == request.user.id:
            return JsonResponse({"detail": "Cannot delete yourself"}, status=403)
        u.delete()
        return JsonResponse({"detail": "Deleted"})
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)
    # allow partial update
    if "username" in data:
        u.username = data["username"]
    if "email" in data:
        u.email = data["email"]
    if "is_staff" in data:
        u.is_staff = bool(data["is_staff"])
    if "is_active" in data:
        u.is_active = bool(data["is_active"])
    if data.get("new_password"):
        u.set_password(data["new_password"])
    try:
        u.full_clean()
        u.save()
    except Exception as e:
        return JsonResponse({"detail": str(e)}, status=400)
    return JsonResponse({"id": u.id, "username": u.username, "email": u.email, "is_staff": u.is_staff})
