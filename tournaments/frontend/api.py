import json
from datetime import timedelta
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.shortcuts import get_object_or_404
from django.db.models import Count, Q
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from gamelink.views import playable_seat
from tournaments import models
from .forms import SignupForm, AdminUserCreateForm, CreateTournamentForm


def _build_definition_from_template(template, opts=None):
    """Build YAML dict from easy template - avoids manual YAML for Vue."""
    opts = opts or {}
    if template == "division":
        # Matches your paste: single Division stage + podium 1st/2nd/3rd Division
        return {
            "stages": [
                {
                    "id": "division",
                    "name": "Division",
                    "mode": "division",
                }
            ],
            "podium": [
                "division.placements[0]",
                "division.placements[1]",
                "division.placements[2]",
            ],
        }
    if template == "knockout":
        return {
            "stages": [
                {"id": "main_round", "name": "Main Round", "mode": "knockout"}
            ],
            "podium": [
                "main_round.placements[0]",
                "main_round.placements[1]",
            ],
        }
    if template == "groups-knockout":
        return {
            "stages": [
                {
                    "id": "preliminaries",
                    "name": "Preliminaries",
                    "mode": "groups",
                    "min-group-size": 3,
                    "max-group-size": 4,
                },
                {
                    "id": "main_round",
                    "name": "Main Round",
                    "mode": "knockout",
                    "played-by": ["preliminaries.placements[0]", "preliminaries.placements[1]"],
                },
            ],
            "podium": [
                "main_round.placements[0]",
                "main_round.placements[1]",
            ],
        }
    raise ValueError(f"Unknown template: {template}")


def _serialize_tournament(t, request):
    # mirrors frontend/views.py:87 state logic
    is_joined = False
    if request.user.is_authenticated:
        is_joined = t.participations.filter(
            participant__user=request.user).exists()
    starts = t.starts_at.isoformat() if getattr(t, "starts_at", None) else None
    # handle case where starts_at was stored as string (naive)
    if isinstance(getattr(t, "starts_at", None), str):
        starts = t.starts_at
    return {
        "id": t.id,
        "name": t.name,
        "state": t.state,  # draft/open/active/finished
        "status": t.state,  # alias for Vue frontend
        "published": t.published,
        "creator": t.creator.username if t.creator else None,
        "creator_id": t.creator_id,
        "is_creator": bool(request.user.is_authenticated and t.creator_id == request.user.id),
        "is_joined": is_joined,
        "participant_count": t.participations.count(),
        "starts_at": starts,
        "min_players": getattr(t, "min_players", 6),
        "max_players": getattr(t, "max_players", None),
        "target_points": getattr(t, "target_points", 5),
        "time_control": getattr(t, "time_control", "normal"),
        # placeholders for your Vue fields (map backend -> frontend)
        "enterPrice": 0,
        "prizeMoney": 0,
        "capacity": t.max_players or 8,
    }


def _validated_tournament_metadata(data):
    """Validate metadata shared by tournament creation and draft updates."""
    errors = {}
    cleaned = {}
    try:
        cleaned["min_players"] = int(data.get("min_players", 6))
        if cleaned["min_players"] < 2:
            errors["min_players"] = "Must be at least 2."
    except (TypeError, ValueError):
        errors["min_players"] = "Must be a whole number."

    max_players = data.get("max_players")
    if max_players in (None, ""):
        cleaned["max_players"] = None
    else:
        try:
            cleaned["max_players"] = int(max_players)
            if cleaned["max_players"] < 2:
                errors["max_players"] = "Must be at least 2."
            elif "min_players" in cleaned and cleaned["max_players"] < cleaned["min_players"]:
                errors["max_players"] = "Must be greater than or equal to minimum players."
        except (TypeError, ValueError):
            errors["max_players"] = "Must be a whole number."

    try:
        cleaned["target_points"] = int(data.get("target_points", 5))
        if cleaned["target_points"] < 1:
            errors["target_points"] = "Must be at least 1."
    except (TypeError, ValueError):
        errors["target_points"] = "Must be a whole number."

    time_control = data.get("time_control", "normal")
    if time_control not in {choice[0] for choice in models.Tournament.TIME_CHOICES}:
        errors["time_control"] = "Invalid time control."
    else:
        cleaned["time_control"] = time_control

    starts_at = data.get("starts_at")
    if starts_at in (None, ""):
        cleaned["starts_at"] = None
    elif not isinstance(starts_at, str) or parse_datetime(starts_at) is None:
        errors["starts_at"] = "Invalid date and time."
    else:
        parsed_starts_at = parse_datetime(starts_at)
        if timezone.is_naive(parsed_starts_at):
            parsed_starts_at = timezone.make_aware(parsed_starts_at)
        if parsed_starts_at < timezone.now():
            errors["starts_at"] = "Must be in the future."
        else:
            cleaned["starts_at"] = parsed_starts_at
    return cleaned, errors


def _capacity_error(tournament):
    if tournament.max_players is not None and tournament.participations.count() >= tournament.max_players:
        return JsonResponse({"detail": f"Tournament is full ({tournament.max_players} players)."}, status=412)
    return None


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
        capacity_error = _capacity_error(t)
        if capacity_error:
            return capacity_error
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


@csrf_exempt
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
    # Easy template path: {name, template:"division"} -> generate definition
    if data.get("template"):
        try:
            tmpl = _build_definition_from_template(data.get("template"), data)
            import yaml
            data["definition"] = yaml.safe_dump(tmpl)
        except Exception as e:
            return JsonResponse({"detail": str(e)}, status=400)
    extra_kwargs, metadata_errors = _validated_tournament_metadata(data)
    if metadata_errors:
        return JsonResponse({"errors": metadata_errors}, status=400)
    form = CreateTournamentForm(data)
    # CreateTournamentForm expects definition as YAML string; allow dict or string
    if isinstance(data.get("definition"), dict):
        import yaml
        data["definition"] = yaml.safe_dump(data["definition"])
        form = CreateTournamentForm(data)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)
    tournament = form.create_tournament(request)
    # Apply easy fields after creation (keep YAML intact)
    for k, v in extra_kwargs.items():
        setattr(tournament, k, v)
    tournament.save(update_fields=list(extra_kwargs.keys()))
    return JsonResponse(_serialize_tournament(tournament, request), status=201)


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
def api_admin_tournament_detail(request, pk):
    err = _require_staff(request)
    if err:
        return err
    t = get_object_or_404(models.Tournament, pk=pk)
    if request.method == "GET":
        data = _serialize_tournament(t, request)
        data["definition"] = t.definition
        data["participants"] = [
            {
                "id": participant["participant__id"],
                "name": participant["participant__name"],
                "user_id": participant["participant__user__id"],
                "username": participant["participant__user__username"],
            }
            for participant in t.participations.values(
                "participant__id",
                "participant__name",
                "participant__user__id",
                "participant__user__username",
            )
        ]
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
    if data.get("template"):
        try:
            tmpl = _build_definition_from_template(data.get("template"), data)
            import yaml
            data["definition"] = yaml.safe_dump(tmpl)
        except Exception as e:
            return JsonResponse({"detail": str(e)}, status=400)
    metadata, metadata_errors = _validated_tournament_metadata(data)
    if metadata_errors:
        return JsonResponse({"errors": metadata_errors}, status=400)
    form = CreateTournamentForm(data)
    if isinstance(data.get("definition"), dict):
        import yaml
        data["definition"] = yaml.safe_dump(data["definition"])
        form = CreateTournamentForm(data)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)
    with transaction.atomic():
        replacement = form.create_tournament(request)
        t.stages.non_polymorphic().all().delete()
        replacement.stages.non_polymorphic().update(tournament_id=t.id)
        t.name = replacement.name
        t.definition = replacement.definition
        t.podium_spec = replacement.podium_spec
        for field, value in metadata.items():
            setattr(t, field, value)
        replacement.delete()
        t.save()
    return JsonResponse(_serialize_tournament(t, request))


@csrf_exempt
@require_http_methods(["POST"])
def api_admin_tournament_publish(request, pk):
    err = _require_staff(request)
    if err:
        return err
    t = get_object_or_404(models.Tournament, pk=pk)
    if t.state != "draft":
        return JsonResponse({"detail": f"Cannot publish, state={t.state}"}, status=412)
    t.published = True
    t.save()
    return JsonResponse(_serialize_tournament(t, request))


@csrf_exempt
@require_http_methods(["POST"])
def api_admin_tournament_draft(request, pk):
    err = _require_staff(request)
    if err:
        return err
    t = get_object_or_404(models.Tournament, pk=pk)
    if t.state != "open":
        return JsonResponse({"detail": f"Cannot draft, state={t.state}"}, status=412)
    t.published = False
    t.participations.all().delete()
    t.save()
    return JsonResponse(_serialize_tournament(t, request))


@csrf_exempt
@require_http_methods(["GET", "POST", "DELETE"])
def api_admin_tournament_attendees(request, pk):
    err = _require_staff(request)
    if err:
        return err
    t = get_object_or_404(models.Tournament, pk=pk)
    if request.method == "GET":
        # Allow viewing attendees in any state (open/active/finished), only block mutating when not open
        pass
    elif t.state != "open":
        return JsonResponse({"detail": f"Cannot manage attendees, state={t.state}"}, status=412)
    if request.method == "GET":
        q = request.GET.get("q", "").strip()
        participants = list(t.participations.select_related("participant").values(
            "participant__id", "participant__name", "participant__user__id", "participant__user__username"))
        # map
        parts = [{"id": p["participant__id"], "name": p["participant__name"], "user_id": p["participant__user__id"],
                  "username": p["participant__user__username"]} for p in participants]
        avail_qs = User.objects.exclude(
            participant__participations__tournament=t).order_by("username")
        if q:
            avail_qs = avail_qs.filter(username__icontains=q)
        avail = list(avail_qs.values("id", "username", "email")[:50])
        return JsonResponse({"participants": parts, "available": avail, "tournament": _serialize_tournament(t, request)})
    if request.method == "POST":
        try:
            data = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"detail": "Invalid JSON"}, status=400)
        capacity_error = _capacity_error(t)
        if capacity_error:
            return capacity_error
        # add single user or virtual name
        if data.get("user_id"):
            try:
                u = User.objects.get(pk=int(data["user_id"]))
                participant = models.Participant.get_or_create_for_user(u)
                if t.participations.filter(participant=participant).exists():
                    return JsonResponse({"detail": "Already in tournament"}, status=400)
                models.Participation.objects.create(
                    tournament=t, participant=participant, slot_id=models.Participation.next_slot_id(t))
                return JsonResponse({"detail": "Added"})
            except (User.DoesNotExist, ValueError):
                return JsonResponse({"detail": "User not found"}, status=404)
        if data.get("name"):
            name = data["name"].strip()
            if not name:
                return JsonResponse({"detail": "Name required"}, status=400)
            participant = models.Participant.objects.get_or_create(name=name)[
                0]
            if t.participations.filter(participant=participant).exists():
                return JsonResponse({"detail": "Already in tournament"}, status=400)
            models.Participation.objects.create(
                tournament=t, participant=participant, slot_id=models.Participation.next_slot_id(t))
            return JsonResponse({"detail": "Added"})
        return JsonResponse({"detail": "Provide user_id or name"}, status=400)
    # DELETE ?participant_id=123
    pid = request.GET.get("participant_id") or request.GET.get("id")
    if not pid:
        try:
            data = json.loads(request.body or "{}")
            pid = data.get("participant_id") or data.get("id")
        except:
            pass
    if not pid:
        return JsonResponse({"detail": "participant_id required"}, status=400)
    try:
        p = models.Participant.objects.get(pk=int(pid))
        participation = t.participations.get(participant=p)
        participation.delete()
        if p.user is None and not p.participations.exists():
            p.delete()
        return JsonResponse({"detail": "Removed"})
    except (models.Participant.DoesNotExist, models.Participation.DoesNotExist, ValueError):
        return JsonResponse({"detail": "Not found"}, status=404)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_admin_tournament_progress(request, pk):
    # Allow any authenticated user to view/progress (like TournamentProgressView), but keep staff check for start via separate endpoint
    # For progress, participant or staff can view/edit
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required"}, status=401)
    t = get_object_or_404(models.Tournament, pk=pk)
    if t.state == "draft":
        return JsonResponse({"detail": "Tournament is draft"}, status=412)
    # If open, try to start it (like TournamentProgressView GET does)
    if t.state == "open":
        # if t.creator and t.creator_id != request.user.id:
        #     return JsonResponse({"detail": "Only creator can start"}, status=403)
        required = t.min_players
        if t.participations.count() < required:
            return JsonResponse({"detail": f"Need at least {required} attendees"}, status=412)
        from django.core.exceptions import ValidationError
        try:
            t.test()
        except ValidationError as e:
            return JsonResponse({"detail": "; ".join(e.messages) if hasattr(e, "messages") else str(e)}, status=400)
        t.shuffle_participants()
        t.update_state()
    if request.method == "GET":
        stages = {}
        current_stage_idx = None
        for idx, stage in enumerate(t.stages.all()):
            levels = []
            for level in range(stage.levels):
                fixtures = []
                for fixture in stage.fixtures.select_related(
                    "player1__user",
                    "player2__user",
                ).filter(level=level):

                    player1 = fixture.player1
                    player2 = fixture.player2

                    player1_user = player1.user if player1 and player1.user else None
                    player2_user = player2.user if player2 and player2.user else None

                    is_player1 = (
                        player1_user is not None
                        and player1_user.id == request.user.id
                    )

                    is_player2 = (
                        player2_user is not None
                        and player2_user.id == request.user.id
                    )

                    current_user = player1_user if is_player1 else player2_user if is_player2 else None
                    opponent = player2_user if is_player1 else player1_user if is_player2 else None

                    fixtures.append({
                        "id": fixture.id,

                        "player1": {
                            "id": player1.id if player1 else None,
                            "user_id": player1_user.id if player1_user else None,
                            "name": player1.name if player1 else None,
                            "username": player1_user.username if player1_user else None,
                        } if player1 else None,

                        "player2": {
                            "id": player2.id if player2 else None,
                            "user_id": player2_user.id if player2_user else None,
                            "name": player2.name if player2 else None,
                            "username": player2_user.username if player2_user else None,
                        } if player2 else None,

                        "current_user": {
                            "id": current_user.id,
                            "username": current_user.username,
                            "participant_id": (
                                player1.id if is_player1
                                else player2.id if is_player2
                                else None
                            ),
                        } if current_user else None,

                        "opponent": {
                            "id": opponent.id,
                            "username": opponent.username,
                            "participant_id": (
                                player2.id if is_player1
                                else player1.id if is_player2
                                else None
                            ),
                        } if opponent else None,

                        "is_current_user": current_user is not None,
                        # Use the exact predicate that StartGameView uses, so the Vue client
                        # never offers a game link for an old, settled, or otherwise unavailable
                        # fixture.  StartGameView repeats this check when the form is submitted.
                        "can_play": playable_seat(request.user, fixture)[0] is not None,

                        "score1": fixture.score1,
                        "score2": fixture.score2,
                        "is_confirmed": fixture.is_confirmed,
                        "confirmations": fixture.confirmations.count(),
                        "required_confirmations": fixture.required_confirmations_count,

                        "editable": (
                            not fixture.is_confirmed
                            and level == stage.current_level
                        ),

                        "has_confirmed": fixture.confirmations.filter(
                            id=request.user.id
                        ).exists(),
                    })
                    print(
                        "FIXTURE DEBUG:",
                        fixture.id,
                        "| REQUEST USER:",
                        request.user.id,
                        request.user.username,
                        "| P1:",
                        player1.id if player1 else None,
                        player1.user_id if player1 else None,
                        player1.user.username if player1 and player1.user else None,
                        "| P2:",
                        player2.id if player2 else None,
                        player2.user_id if player2 else None,
                        player2.user.username if player2 and player2.user else None,
                    )
                levels.append(
                    {"fixtures": fixtures, "name": stage.get_level_name(level)})
            stages[stage.id] = {"levels": levels}
            if t.current_stage and stage.id == t.current_stage.id:
                current_stage_idx = idx + 1
        if t.current_stage is None:
            current_stage_idx = t.stages.count() + 1
            print(
                "REQUEST USER:",
                request.user.id,
                request.user.username,
            )

        print(
            "FIXTURE:",
            fixture.id,
            "PLAYER1:",
            fixture.player1_id,
            "PLAYER2:",
            fixture.player2_id,
        )
        return JsonResponse({
            "tournament": _serialize_tournament(t, request),
            "stages": stages,
            "current_stage": current_stage_idx,
            "is_finished": t.state == "finished",
            "podium": list(t.podium.values("id", "name")) if t.state == "finished" else [],
        })
    # POST - submit score
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)
    try:
        fixture = models.Fixture.objects.get(id=data.get("fixture_id"))
    except models.Fixture.DoesNotExist:
        return JsonResponse({"detail": "Fixture not found"}, status=404)
    # checks
    if t.state != "active":
        return JsonResponse({"detail": f"Tournament not active, state={t.state}"}, status=412)
    if fixture.mode_id != t.current_stage.id:
        return JsonResponse({"detail": "Fixture not in current stage"}, status=412)
    if fixture.level != t.current_stage.current_level:
        return JsonResponse({"detail": "Fixture not in current level"}, status=412)
    try:
        new_score = (int(str(data.get("score1")).strip()),
                     int(str(data.get("score2")).strip()))
    except:
        return JsonResponse({"detail": "Invalid score"}, status=400)
    if fixture.score != new_score:
        if fixture.is_confirmed:
            return JsonResponse({"detail": "Already confirmed"}, status=412)
        fixture.score = new_score
        try:
            fixture.full_clean()
        except Exception as e:
            return JsonResponse({"detail": str(e)}, status=400)
        fixture.save()
        fixture.confirmations.clear()
    if not fixture.confirmations.filter(id=request.user.id).exists():
        fixture.confirmations.add(request.user)
    if fixture.is_confirmed:
        t.update_state()
    return JsonResponse({"detail": "Saved", "is_confirmed": fixture.is_confirmed})


@csrf_exempt
@require_http_methods(["POST"])
def api_admin_tournament_start(request, pk):
    err = _require_staff(request)
    if err:
        return err
    t = get_object_or_404(models.Tournament, pk=pk)
    if t.state != "open":
        return JsonResponse({"detail": f"Cannot start, state={t.state}"}, status=412)
    # if t.creator and t.creator_id != request.user.id:
    #     return JsonResponse({"detail": "Only creator can start"}, status=403)
    required = t.min_players
    if t.participations.count() < required:
        return JsonResponse({"detail": f"Need at least {required} attendees (you have {t.participations.count()})"}, status=412)
    from django.core.exceptions import ValidationError
    try:
        t.test()
    except ValidationError as e:
        return JsonResponse({"detail": "; ".join(e.messages) if hasattr(e, "messages") else str(e)}, status=400)
    t.shuffle_participants()
    t.update_state()
    return JsonResponse(_serialize_tournament(t, request))


@csrf_exempt
@require_http_methods(["GET"])
def api_admin_dashboard(request):
    err = _require_staff(request)
    if err:
        return err

    try:
        days = int(request.GET.get("days", 7))
    except (TypeError, ValueError):
        days = 7
    if days not in {1, 7, 30}:
        days = 7

    now = timezone.now()
    period_start = now - timedelta(days=days)
    previous_start = period_start - timedelta(days=days)
    period_end = now + timedelta(days=days)
    tournaments = list(
        models.Tournament.objects
        .prefetch_related("participations", "stages__fixtures")
        .order_by("starts_at", "-id")
    )

    by_state = {"draft": [], "open": [], "active": [], "finished": []}
    for tournament in tournaments:
        by_state[tournament.state].append(tournament)

    def tournament_summary(tournament):
        participant_count = tournament.participations.count()
        return {
            "id": tournament.id,
            "name": tournament.name,
            "state": tournament.state,
            "starts_at": tournament.starts_at.isoformat() if tournament.starts_at else None,
            "participant_count": participant_count,
            "min_players": tournament.min_players,
            "max_players": tournament.max_players,
        }

    waiting = [
        tournament for tournament in by_state["open"]
        if tournament.participations.count() < tournament.min_players
    ]
    upcoming = [
        tournament for tournament in by_state["open"]
        if tournament.starts_at and now <= tournament.starts_at <= period_end
    ]

    pending_match_count = 0
    active_tournaments = []
    for tournament in by_state["active"]:
        stage = tournament.current_stage
        current_fixtures = list(stage.current_fixtures or []) if stage else []
        pending = sum(
            1 for fixture in current_fixtures
            if fixture.player1_id and fixture.player2_id and fixture.score1 is None
        )
        pending_match_count += pending
        stage_name = stage.name or stage.identifier if stage else "Tournament"
        round_name = stage.get_level_name(stage.current_level) if stage else None
        summary = tournament_summary(tournament)
        summary.update({
            "stage": stage_name,
            "round": round_name or "Current round",
            "pending_matches": pending,
        })
        active_tournaments.append(summary)

    attention = []
    for tournament in by_state["open"]:
        participant_count = tournament.participations.count()
        missing = max(tournament.min_players - participant_count, 0)
        if tournament.starts_at and tournament.starts_at < now:
            attention.append({
                **tournament_summary(tournament),
                "kind": "overdue",
                "severity": "critical",
                "message": "Start time has passed",
                "action_label": "Review tournament",
                "action_to": f"/tournaments/{tournament.id}",
            })
        elif missing:
            attention.append({
                **tournament_summary(tournament),
                "kind": "waiting_players",
                "severity": "warning",
                "message": f"Needs {missing} more player{'s' if missing != 1 else ''}",
                "action_label": "Manage players",
                "action_to": f"/tournaments/{tournament.id}/attendees",
            })

    for tournament in active_tournaments:
        if tournament["pending_matches"]:
            attention.append({
                **tournament,
                "kind": "pending_matches",
                "severity": "warning",
                "message": f"{tournament['pending_matches']} match{'es' if tournament['pending_matches'] != 1 else ''} waiting for results",
                "action_label": "View progress",
                "action_to": f"/tournaments/{tournament['id']}/progress",
            })

    for tournament in by_state["draft"][:3]:
        attention.append({
            **tournament_summary(tournament),
            "kind": "draft",
            "severity": "info",
            "message": "Draft has not been published",
            "action_label": "Continue editing",
            "action_to": f"/tournaments/{tournament.id}?edit=1",
        })

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    attention.sort(key=lambda item: (severity_order[item["severity"]], item["id"]))

    current_new_users = User.objects.filter(date_joined__gte=period_start).count()
    previous_new_users = User.objects.filter(
        date_joined__gte=previous_start,
        date_joined__lt=period_start,
    ).count()
    new_user_delta = current_new_users - previous_new_users
    active_attention = sum(1 for item in attention if item["kind"] == "pending_matches")
    total_missing_players = sum(
        tournament.min_players - tournament.participations.count()
        for tournament in waiting
    )

    return JsonResponse({
        "updated_at": now.isoformat(),
        "range_days": days,
        "kpis": {
            "active": {"value": len(by_state["active"]), "context": f"{active_attention} require attention"},
            "upcoming": {"value": len(upcoming), "context": f"In the next {days} day{'s' if days != 1 else ''}"},
            "waiting": {"value": len(waiting), "context": f"{total_missing_players} players still needed"},
            "pending_matches": {"value": pending_match_count, "context": "Waiting for automatic results"},
            "new_users": {
                "value": current_new_users,
                "context": f"{new_user_delta:+d} vs previous period",
            },
        },
        "counts": {state: len(items) for state, items in by_state.items()},
        "attention": attention[:8],
        "active_tournaments": active_tournaments[:6],
        "upcoming_tournaments": [tournament_summary(item) for item in upcoming[:6]],
        "recent_users": list(
            User.objects.order_by("-date_joined").values(
                "id", "username", "email", "is_staff", "is_active"
            )[:5]
        ),
    })


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
