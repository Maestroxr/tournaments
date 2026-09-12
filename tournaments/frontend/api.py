import csv
import json
import logging
import random
import secrets
import string
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.shortcuts import get_object_or_404
from django.db.models import Count, F, Q, Sum
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from gamelink.views import _playable_refusal_reason, playable_seat
from tournaments import models
from .forms import (
    SignupForm,
    AdminUserCreateForm,
    CreateTournamentForm,
    validate_admin_username,
    validate_phone_number,
    require_phone_number,
)

logger = logging.getLogger(__name__)


def _clip_client_value(value, limit=500):
    text = str(value or "")
    return text if len(text) <= limit else f"{text[:limit]}..."


PLAYABILITY_MESSAGES = {
    "disabled": "Game links are disabled on the tournaments server.",
    "not_authenticated": "The player is not signed in.",
    "tournament_not_active": "The tournament has not started yet.",
    "fixture_not_in_current_stage": "This match is not in the current tournament stage.",
    "fixture_not_in_current_level": "This match is not in the current round.",
    "fixture_already_confirmed": "This match already has a confirmed result.",
    "fixture_missing_player": "This match is still missing one of the players.",
    "fixture_player_has_no_user": "One of the matched players is not linked to a user account.",
    "user_not_in_fixture": "The signed-in player is not assigned to this match.",
    "backgammon_url_is_empty": "The Backgammon game URL is not configured.",
    "ready": "Ready to start the match.",
}


def _playability_payload(request, fixture):
    seat, refusal = playable_seat(request.user, fixture)
    reason = "ready" if seat is not None else _playable_refusal_reason(request.user, fixture)
    if reason == "ready" and not getattr(settings, "GAMELINK_BACKGAMMON_URL", "").strip():
        reason = "backgammon_url_is_empty"
        refusal = 412
    return {
        "can_play": seat is not None and reason == "ready",
        "seat": seat,
        "reason": reason,
        "status": refusal,
        "message": PLAYABILITY_MESSAGES.get(reason, "This match is not ready yet."),
    }


def _parse_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


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
    is_eliminated = False
    can_play = False
    registration_status = None
    if request.user.is_authenticated:
        is_joined = t.participations.filter(
            participant__user=request.user).exists()
        participation = t.participations.filter(
            participant__user=request.user).select_related("participant").first()
        own_registration = t.registrations.filter(participant__user=request.user).first()
        if own_registration:
            registration_status = own_registration.status
        elif participation:
            registration_status = models.TournamentRegistration.STATUS_REGISTERED
        if participation:
            participant = participation.participant
            user_fixtures = models.Fixture.objects.filter(
                mode__tournament=t
            ).filter(Q(player1=participant) | Q(player2=participant))
            current_stage = t.current_stage if t.state == "active" else None
            if current_stage is not None:
                current_fixtures = user_fixtures.select_related(
                    "mode__tournament", "player1__user", "player2__user"
                ).filter(
                    mode=current_stage,
                    level=current_stage.current_level,
                )
                # Keep the tournament-card status aligned with the exact predicate used when a
                # ticket is issued. This prevents a stale/future fixture or disabled GameLink from
                # being advertised as playable.
                can_play = any(
                    _playability_payload(request, fixture)["can_play"]
                    for fixture in current_fixtures
                )
            lost_confirmed = user_fixtures.filter(
                Q(
                    Q(player1=participant, score1__lt=F("score2"))
                    | Q(player2=participant, score2__lt=F("score1")),
                    score1__isnull=False,
                    score2__isnull=False,
                )
                | Q(
                    admin_result__in=("advance", "disqualify"),
                    admin_winner__isnull=False,
                )
                & ~Q(admin_winner=participant)
            ).exists()
            is_eliminated = t.state in ("active", "finished") and lost_confirmed and not can_play
    starts = t.starts_at.isoformat() if getattr(t, "starts_at", None) else None
    # handle case where starts_at was stored as string (naive)
    if isinstance(getattr(t, "starts_at", None), str):
        starts = t.starts_at
    podium = [
        {
            "id": participation.participant_id,
            "name": participation.participant.name,
            "position": participation.podium_position,
        }
        for participation in t.participations.filter(
            podium_position__isnull=False
        ).select_related("participant").order_by("podium_position")
    ]
    champion = podium[0] if podium else None
    payload = {
        "id": t.id,
        "name": t.name,
        "state": t.state,  # draft/open/active/finished
        "status": t.state,  # alias for Vue frontend
        "lifecycle_state": t.lifecycle_state,
        "published": t.published,
        "registration_open": t.registration_open,
        "registration_closed_at": t.registration_closed_at.isoformat() if t.registration_closed_at else None,
        "registration_closed_reason": t.registration_closed_reason if request.user.is_authenticated and request.user.is_staff else "",
        "draw_order": list(t.draw_order or []) if request.user.is_authenticated and request.user.is_staff else [],
        "draw_generated_at": t.draw_generated_at.isoformat() if t.draw_generated_at else None,
        "draw_confirmed_at": t.draw_confirmed_at.isoformat() if t.draw_confirmed_at else None,
        "results_confirmed_at": t.results_confirmed_at.isoformat() if t.results_confirmed_at else None,
        "creator": t.creator.username if t.creator else None,
        "creator_id": t.creator_id,
        "created_at": t.created_at.isoformat(),
        "is_creator": bool(request.user.is_authenticated and t.creator_id == request.user.id),
        "is_joined": is_joined,
        "registration_status": registration_status,
        "is_eliminated": is_eliminated,
        "can_play": can_play,
        "champion": champion,
        "podium": podium,
        "participant_count": t.participations.count(),
        "starts_at": starts,
        "min_players": getattr(t, "min_players", 6),
        "max_players": getattr(t, "max_players", None),
        "target_points": getattr(t, "target_points", 5),
        "time_control": getattr(t, "time_control", "normal"),
        "doubling_enabled": getattr(t, "doubling_enabled", True),
        "entry_fee": str(getattr(t, "entry_fee", Decimal("0.00"))),
        "prize_money": str(t.effective_prize_money),
        "platform_fee_percent": str(t.platform_fee_percent),
        "collected_entry_fees": str(t.collected_entry_fees),
        # placeholders for your Vue fields (map backend -> frontend)
        "enterPrice": float(getattr(t, "entry_fee", Decimal("0.00"))),
        "prizeMoney": float(t.effective_prize_money),
        "capacity": t.max_players or 8,
    }
    if request.user.is_authenticated and request.user.is_staff:
        payload["registration_summary"] = _registration_summary(t)
    return payload


def _serialize_user(user):
    contact = models.UserContact.objects.filter(user=user).first()
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "phone_number": contact.phone_number if contact else "",
        "is_staff": user.is_staff,
        "is_active": user.is_active,
        "balance": str(models.WalletTransaction.balance_for_user(user)),
    }


def _parse_money(value, field="amount"):
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be a valid amount.")
    if not amount.is_finite():
        raise ValueError(f"{field} must be a valid amount.")
    if amount < 0:
        raise ValueError(f"{field} cannot be negative.")
    return amount


def _serialize_wallet_transaction(item):
    return {
        "id": item.id,
        "user_id": item.user_id,
        "username": item.user.username,
        "kind": item.kind,
        "amount": str(item.amount),
        "balance_after": str(item.balance_after),
        "tournament_id": item.tournament_id,
        "tournament_name": item.tournament.name if item.tournament else None,
        "head_to_head_table_id": item.head_to_head_table_id,
        "head_to_head_code": item.head_to_head_table.code if item.head_to_head_table else None,
        "actor_id": item.actor_id,
        "actor_username": item.actor.username if item.actor else None,
        "note": item.note,
        "created_at": item.created_at.isoformat(),
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

    try:
        cleaned["entry_fee"] = _parse_money(data.get("entry_fee", data.get("enterPrice", 0)), "entry_fee")
    except ValueError as error:
        errors["entry_fee"] = str(error)

    try:
        cleaned["prize_money"] = _parse_money(data.get("prize_money", data.get("prizeMoney", 0)), "prize_money")
    except ValueError as error:
        errors["prize_money"] = str(error)

    try:
        cleaned["platform_fee_percent"] = _parse_money(
            data.get("platform_fee_percent", models.DirectPlaySettings.load().tournament_fee_percent),
            "platform_fee_percent",
        )
        if not Decimal("8") <= cleaned["platform_fee_percent"] <= Decimal("10"):
            errors["platform_fee_percent"] = "Must be between 8% and 10%."
    except ValueError as error:
        errors["platform_fee_percent"] = str(error)

    time_control = data.get("time_control", "normal")
    if time_control not in {choice[0] for choice in models.Tournament.TIME_CHOICES}:
        errors["time_control"] = "Invalid time control."
    else:
        cleaned["time_control"] = time_control

    cleaned["doubling_enabled"] = _parse_bool(data.get("doubling_enabled"), True)

    starts_at = data.get("starts_at")
    if starts_at in (None, ""):
        cleaned["starts_at"] = None
    elif not isinstance(starts_at, str) or parse_datetime(starts_at) is None:
        errors["starts_at"] = "Invalid date and time."
    else:
        parsed_starts_at = parse_datetime(starts_at)
        if timezone.is_naive(parsed_starts_at):
            parsed_starts_at = timezone.make_aware(parsed_starts_at)
        if parsed_starts_at < timezone.now().replace(second=0, microsecond=0):
            errors["starts_at"] = "Must be now or in the future."
        else:
            cleaned["starts_at"] = parsed_starts_at
    return cleaned, errors


def _capacity_error(tournament):
    if tournament.max_players is not None and tournament.participations.count() >= tournament.max_players:
        return JsonResponse({"detail": f"Tournament is full ({tournament.max_players} players)."}, status=412)
    return None


def _registration_summary(tournament):
    active_ids = list(tournament.participations.values_list('participant_id', flat=True))
    registrations = {
        registration.participant_id: registration
        for registration in tournament.registrations.all()
    }
    checked_in = 0
    unpaid = 0
    attention = 0
    for participant_id in active_ids:
        registration = registrations.get(participant_id)
        if registration and registration.checked_in_at:
            checked_in += 1
        payment_status = registration.payment_status if registration else models.TournamentRegistration.PAYMENT_PAID
        needs_payment = payment_status == models.TournamentRegistration.PAYMENT_UNPAID
        if needs_payment:
            unpaid += 1
        if needs_payment:
            attention += 1
    waitlisted = sum(
        registration.status == models.TournamentRegistration.STATUS_WAITLISTED
        for registration in registrations.values()
    )
    return {
        'registered': len(active_ids),
        'checked_in': checked_in,
        'unpaid': unpaid,
        'waitlisted': waitlisted,
        'attention': attention + waitlisted,
        'ready': max(len(active_ids) - attention, 0),
    }


def _ensure_registration(tournament, participant, *, status=None, payment_status=None):
    defaults = {
        'status': status or models.TournamentRegistration.STATUS_REGISTERED,
        'payment_status': payment_status or (
            models.TournamentRegistration.PAYMENT_PAID
            if tournament.entry_fee <= 0 or participant.user_id
            else models.TournamentRegistration.PAYMENT_UNPAID
        ),
    }
    registration, created = models.TournamentRegistration.objects.get_or_create(
        tournament=tournament,
        participant=participant,
        defaults=defaults,
    )
    if not created:
        changed = []
        if status is not None and registration.status != status:
            registration.status = status
            changed.append('status')
        if payment_status is not None and registration.payment_status != payment_status:
            registration.payment_status = payment_status
            changed.append('payment_status')
        if changed:
            changed.append('updated_at')
            registration.save(update_fields=changed)
    return registration


def _charge_registration(tournament, registration, actor):
    participant = registration.participant
    if tournament.entry_fee <= 0:
        registration.payment_status = models.TournamentRegistration.PAYMENT_PAID
        return
    if registration.payment_status in {
        models.TournamentRegistration.PAYMENT_PAID,
        models.TournamentRegistration.PAYMENT_WAIVED,
    }:
        return
    if participant.user_id is None:
        registration.payment_status = models.TournamentRegistration.PAYMENT_UNPAID
        return
    models.WalletTransaction.create_entry(
        user=participant.user,
        amount=-tournament.entry_fee,
        kind=models.WalletTransaction.KIND_TOURNAMENT_ENTRY,
        tournament=tournament,
        actor=actor,
        note=f"Entry fee for {tournament.name}",
    )
    registration.payment_status = models.TournamentRegistration.PAYMENT_PAID


def _refund_registration(tournament, registration, actor):
    participant = registration.participant
    if (
        tournament.entry_fee > 0
        and participant.user_id is not None
        and registration.payment_status == models.TournamentRegistration.PAYMENT_PAID
    ):
        models.WalletTransaction.create_entry(
            user=participant.user,
            amount=tournament.entry_fee,
            kind=models.WalletTransaction.KIND_TOURNAMENT_REFUND,
            tournament=tournament,
            actor=actor,
            note=f"Refund for {tournament.name}",
        )
        registration.payment_status = models.TournamentRegistration.PAYMENT_REFUNDED


def _add_to_active_roster(tournament, registration, actor):
    if tournament.participations.filter(participant=registration.participant).exists():
        registration.status = models.TournamentRegistration.STATUS_REGISTERED
        registration.withdrawn_at = None
        registration.save(update_fields=['status', 'withdrawn_at', 'updated_at'])
        return
    if tournament.max_players is not None and tournament.participations.count() >= tournament.max_players:
        raise ValidationError('Tournament is full.')
    if (
        registration.status == models.TournamentRegistration.STATUS_WITHDRAWN
        and tournament.entry_fee > 0
    ):
        registration.payment_status = models.TournamentRegistration.PAYMENT_UNPAID
    _charge_registration(tournament, registration, actor)
    models.Participation.objects.create(
        tournament=tournament,
        participant=registration.participant,
        slot_id=models.Participation.next_slot_id(tournament),
    )
    registration.status = models.TournamentRegistration.STATUS_REGISTERED
    registration.withdrawn_at = None
    registration.save(update_fields=['status', 'payment_status', 'withdrawn_at', 'updated_at'])


@ensure_csrf_cookie
@require_http_methods(["GET"])
def api_csrf(request):
    return JsonResponse({"detail": "CSRF cookie set"})


@csrf_exempt
@require_http_methods(["POST"])
def api_client_log(request):
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        data = {}

    level = str(data.get("level") or "error").lower()
    message = _clip_client_value(data.get("message"))
    path = _clip_client_value(data.get("path"), 200)
    source = _clip_client_value(data.get("source") or "frontend", 80)
    details = _clip_client_value(data.get("details"), 1000)

    log_message = "[client] source=%s path=%s message=%s details=%s"
    log_args = (source, path, message, details)

    if level in {"debug", "info"}:
        logger.info(log_message, *log_args)
    elif level == "warning":
        logger.warning(log_message, *log_args)
    else:
        logger.error(log_message, *log_args)

    return JsonResponse({"status": "logged"})


@require_http_methods(["GET"])
def api_me(request):
    if request.user.is_authenticated:
        data = _serialize_user(request.user)
        data["is_authenticated"] = True
        return JsonResponse(data)
    return JsonResponse({"is_authenticated": False}, status=401)


@require_http_methods(["PUT"])
def api_profile(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required"}, status=401)
    try:
        data = json.loads(request.body or "{}")
        phone_number = require_phone_number(data.get("phone_number"))
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)
    except ValidationError as error:
        return JsonResponse({"errors": {"phone_number": error.messages}}, status=400)
    models.UserContact.objects.update_or_create(user=request.user, defaults={"phone_number": phone_number})
    return JsonResponse(_serialize_user(request.user))


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
    return JsonResponse(_serialize_user(user))


@require_http_methods(["POST"])
def api_logout(request):
    logout(request)
    return JsonResponse({"detail": "Logged out"})


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
    data["participants"] = [
        participation.participant.user.username if participation.participant.user_id else participation.participant.name
        for participation in t.participations.select_related("participant__user")
    ]
    return JsonResponse(data)


@require_http_methods(["POST"])
def api_join(request, pk):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required"}, status=401)
    if not models.UserContact.objects.filter(user=request.user).exclude(phone_number='').exists():
        return JsonResponse({"detail": "Add a phone number to your profile before joining a tournament."}, status=412)
    try:
        with transaction.atomic():
            t = models.Tournament.objects.select_for_update().get(pk=pk)
            is_full = t.max_players is not None and t.participations.count() >= t.max_players
            if not t.registration_open and not (
                t.state == 'open' and is_full and t.registration_closed_reason == 'capacity'
            ):
                return JsonResponse({"detail": "Registration is closed"}, status=412)
            if t.participations.filter(participant__user=request.user).exists():
                return JsonResponse(_serialize_tournament(t, request))

            participant = models.Participant.get_or_create_for_user(request.user)
            registration = _ensure_registration(
                t,
                participant,
                status=(
                    models.TournamentRegistration.STATUS_WAITLISTED
                    if is_full else models.TournamentRegistration.STATUS_REGISTERED
                ),
                payment_status=(
                    models.TournamentRegistration.PAYMENT_PAID
                    if t.entry_fee <= 0 else models.TournamentRegistration.PAYMENT_UNPAID
                ),
            )
            if is_full:
                registration.checked_in_at = None
                registration.withdrawn_at = None
                registration.save(update_fields=['status', 'payment_status', 'checked_in_at', 'withdrawn_at', 'updated_at'])
                payload = _serialize_tournament(t, request)
                payload['registration_status'] = models.TournamentRegistration.STATUS_WAITLISTED
                return JsonResponse(payload)
            try:
                _add_to_active_roster(t, registration, request.user)
            except ValidationError:
                return JsonResponse({"detail": "Insufficient funds to join this tournament."}, status=412)
            t.close_registration_if_full()
    except models.Tournament.DoesNotExist:
        return JsonResponse({"detail": "Not found"}, status=404)
    except ValidationError as error:
        return JsonResponse({"detail": "; ".join(error.messages)}, status=400)
    return JsonResponse(_serialize_tournament(t, request))


@require_http_methods(["POST"])
def api_withdraw(request, pk):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required"}, status=401)
    t = get_object_or_404(models.Tournament, pk=pk)
    if t.state != 'open':
        return JsonResponse({"detail": "Registration is closed"}, status=412)
    participant = models.Participant.objects.filter(user=request.user).first()
    participation = t.participations.filter(participant=participant).first() if participant else None
    registration = t.registrations.filter(participant=participant).first() if participant else None
    if participation or registration:
        with transaction.atomic():
            if registration is None:
                registration = _ensure_registration(t, participant)
            if participation and not (
                t.registration_open or t.registration_closed_reason == 'capacity'
            ):
                return JsonResponse({"detail": "Registration is closed"}, status=412)
            if participation:
                _refund_registration(t, registration, request.user)
                participation.delete()
            registration.status = models.TournamentRegistration.STATUS_WITHDRAWN
            registration.checked_in_at = None
            registration.withdrawn_at = timezone.now()
            registration.save(update_fields=[
                'status', 'payment_status', 'checked_in_at', 'withdrawn_at', 'updated_at',
            ])
            if t.registration_closed_reason == 'capacity':
                t.registration_closed_at = None
                t.registration_closed_reason = ''
                t.clear_draw()
                t.save(update_fields=[
                    'registration_closed_at', 'registration_closed_reason', 'draw_order',
                    'draw_generated_at', 'draw_confirmed_at',
                ])
    return JsonResponse(_serialize_tournament(t, request))


def _serialize_head_to_head(table):
    from .game_formats import required_reserve
    reserve_stake = max(Decimal(value) for value in table.quick_stakes) if table.is_quick_match and table.status == 'open' and table.quick_stakes else table.amount
    return {
        "game_format": table.game_format,
        "rules_snapshot": table.rules_snapshot,
        "required_reserve": str(required_reserve(table, reserve_stake)) if table.game_format != 'legacy' else str(table.fee_per_player if table.is_friend_game else table.amount),
        "settlement": table.settlement,
        "id": table.pk,
        "code": table.code,
        "mode": table.mode,
        "host": table.host.username,
        "guest": table.guest.username if table.guest_id else None,
        "winner": table.winner.username if table.winner_id else None,
        "amount": str(table.amount),
        "fee_percent": str(table.fee_percent),
        "fee_per_player": str(table.fee_per_player),
        "target_points": table.target_points,
        "time_control": table.time_control,
        "doubling_enabled": table.doubling_enabled,
        "status": table.status,
        "is_quick_match": table.is_quick_match,
        "quick_stakes": table.quick_stakes,
        "external_room_id": table.external_room_id,
        "created_at": table.created_at.isoformat(),
    }


def _new_table_code():
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(20):
        code = ''.join(secrets.choice(alphabet) for _ in range(6))
        if not models.HeadToHeadTable.objects.filter(code=code).exists():
            return code
    raise RuntimeError("Could not allocate a table code")


class FriendCodesUnavailable(Exception):
    pass


def _create_friend_table(**fields):
    # Keep historical identifiers stable; never reuse a cancelled/completed code.
    occupied = set(models.HeadToHeadTable.objects.values_list('code', flat=True))
    available = [f'{number:04d}' for number in range(10000) if f'{number:04d}' not in occupied]
    while available:
        code = secrets.choice(available)
        try:
            # A concurrent creator can choose the same code. A savepoint keeps
            # that uniqueness failure from aborting the enclosing transaction.
            with transaction.atomic():
                return models.HeadToHeadTable.objects.create(code=code, **fields)
        except IntegrityError:
            if not models.HeadToHeadTable.objects.filter(code=code).exists():
                raise
            available.remove(code)
    raise FriendCodesUnavailable


@require_http_methods(["GET", "POST"])
def api_head_to_head_tables(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required"}, status=401)
    settings_row = models.DirectPlaySettings.load()
    if request.method == "GET":
        tables = models.HeadToHeadTable.objects.filter(
            mode=models.HeadToHeadTable.MODE_MATCH,
            is_quick_match=False,
            status=models.HeadToHeadTable.STATUS_OPEN,
        ).select_related('host').order_by('-created_at', '-pk')
        my_game_tables = models.HeadToHeadTable.objects.filter(
            Q(host=request.user) | Q(guest=request.user),
        ).select_related('host', 'guest', 'winner').order_by('-created_at', '-pk')
        closed_statuses = (
            models.HeadToHeadTable.STATUS_COMPLETED,
            models.HeadToHeadTable.STATUS_CANCELLED,
        )
        my_tables = my_game_tables.exclude(status__in=closed_statuses)[:20]
        my_history = my_game_tables.filter(status__in=closed_statuses)[:50]
        return JsonResponse({
            "enabled": settings_row.enabled,
            "friend_game_fee": str(settings_row.friend_game_fee),
            "match_fee_percent": str(settings_row.head_to_head_fee_percent),
            "stake_amounts": settings_row.stake_amounts,
            "game_rules": settings_row.game_rules,
            "format_profiles": settings_row.format_profiles,
            "tables": [_serialize_head_to_head(table) for table in tables],
            "my_tables": [_serialize_head_to_head(table) for table in my_tables],
            "my_history": [_serialize_head_to_head(table) for table in my_history],
        })
    if not settings_row.enabled:
        return JsonResponse({"detail": "One-on-one games are currently disabled."}, status=412)
    try:
        data = json.loads(request.body or "{}")
        if not isinstance(data, dict):
            raise ValidationError('Expected a game settings object.')
        mode = data.get("mode")
        if 'game_format' in data:
            from .game_formats import create_or_match
            return create_or_match(request)
        legacy_profile = settings_row.format_profiles['match']
        if not legacy_profile['enabled'] or not legacy_profile['private' if mode == 'friend' else 'public']:
            return JsonResponse({'detail': 'This game format or access method is disabled.'}, status=412)
        if mode not in (models.HeadToHeadTable.MODE_MATCH, models.HeadToHeadTable.MODE_FRIEND):
            raise ValidationError("Unknown game mode.")
        if not settings_row.mode_enabled(mode):
            return JsonResponse({"detail": "This game mode is currently disabled."}, status=412)
        target_points = int(data.get("target_points", 1))
        if target_points < 1 or target_points > 25:
            raise ValidationError("target_points must be between 1 and 25.")
        if mode == models.HeadToHeadTable.MODE_FRIEND and target_points not in (1, 3, 5, 7, 9):
            raise ValidationError("Friend games support 1, 3, 5, 7, or 9 points.")
        time_control = data.get("time_control", "normal")
        if time_control not in {choice[0] for choice in models.Tournament.TIME_CHOICES}:
            raise ValidationError("Invalid time control.")
        amount = settings_row.friend_fee_for(target_points) if mode == models.HeadToHeadTable.MODE_FRIEND else _parse_money(data.get("amount"), "amount")
        if amount <= 0:
            raise ValidationError("amount must be greater than zero.")
        if mode == models.HeadToHeadTable.MODE_MATCH and amount not in settings_row.stake_amounts:
            raise ValidationError("This stake is no longer available. Please select an available amount.")
        doubling_enabled = _parse_bool(data.get("doubling_enabled"), True)
        settings_row.validate_new_game(mode, target_points, time_control, doubling_enabled)
    except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as error:
        messages = getattr(error, 'messages', [str(error)])
        return JsonResponse({"detail": "; ".join(messages)}, status=400)
    fee_percent = Decimal("0.00") if mode == models.HeadToHeadTable.MODE_FRIEND else settings_row.head_to_head_fee_percent
    balance = models.WalletTransaction.balance_for_user(request.user)
    if balance < amount:
        return JsonResponse({
            "detail": "Insufficient coins to open this table.",
            "code": "insufficient_coins", "required": str(amount),
            "balance": str(balance), "shortfall": str(amount - balance),
        }, status=412)
    fee_per_player = amount if mode == models.HeadToHeadTable.MODE_FRIEND else (amount * fee_percent / Decimal("100")).quantize(Decimal("0.01"))
    fields = dict(
        mode=mode, host=request.user, amount=amount,
        fee_percent=fee_percent, fee_per_player=fee_per_player,
        target_points=target_points, time_control=time_control, doubling_enabled=doubling_enabled,
    )
    if mode == models.HeadToHeadTable.MODE_FRIEND:
        try:
            table = _create_friend_table(**fields)
        except FriendCodesUnavailable:
            return JsonResponse({
                "code": "friend_codes_unavailable",
                "detail": "לא ניתן ליצור כרגע קוד חדש למשחק נגד חבר.",
            }, status=503)
    else:
        table = models.HeadToHeadTable.objects.create(code=_new_table_code(), **fields)
    return JsonResponse(_serialize_head_to_head(table), status=201)


@require_http_methods(["GET"])
def api_head_to_head_table(request, code):
    """Preview every table rule before the player commits coins."""
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required"}, status=401)
    table = get_object_or_404(
        models.HeadToHeadTable.objects.select_related('host', 'guest', 'winner'),
        code=code.upper(),
    )
    if table.status != models.HeadToHeadTable.STATUS_OPEN or table.guest_id:
        return JsonResponse({"detail": "This table is no longer available."}, status=409)
    return JsonResponse(_serialize_head_to_head(table))


@require_http_methods(["POST"])
def api_head_to_head_quick_match(request):
    """Join a compatible random opponent, or wait in the queue.

    Match at a stake selected by both players, with the same game rules.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required"}, status=401)
    settings_row = models.DirectPlaySettings.load()
    try:
        if 'game_format' in json.loads(request.body or '{}'):
            from .game_formats import create_or_match
            return create_or_match(request, quick=True)
    except (ValueError, TypeError):
        return JsonResponse({'detail': 'Invalid game request.'}, status=400)
    if not settings_row.mode_enabled('quick'):
        return JsonResponse({"detail": "One-on-one games are currently disabled."}, status=412)
    if not settings_row.format_profiles['match']['enabled'] or not settings_row.format_profiles['match']['quick']:
        return JsonResponse({'detail': 'This game format or access method is disabled.'}, status=412)
    try:
        data = json.loads(request.body or "{}")
        target_points = int(data.get("target_points", 5))
        raw_stakes = data.get("amounts", [data.get("amount", "100")])
        if not isinstance(raw_stakes, list) or not raw_stakes or len(raw_stakes) > len(settings_row.stake_amounts):
            raise ValidationError("Select at least one available stake.")
        stakes = sorted(set(_parse_money(value, "amount") for value in raw_stakes))
        if any(value < Decimal("100.00") or value not in settings_row.stake_amounts for value in stakes):
            raise ValidationError("This stake is no longer available. Please select an available amount.")
        stake = max(stakes)
        stored_stakes = [str(value) for value in stakes]
        if target_points < 1 or target_points > 25:
            raise ValidationError("target_points must be between 1 and 25.")
        doubling_enabled = _parse_bool(data.get("doubling_enabled"), True)
        time_control = data.get("time_control", "normal")
        if time_control not in {choice[0] for choice in models.Tournament.TIME_CHOICES}:
            raise ValidationError("Invalid time control.")
        settings_row.validate_new_game('quick', target_points, time_control, doubling_enabled)
    except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as error:
        messages = getattr(error, 'messages', [str(error)])
        return JsonResponse({"detail": "; ".join(messages)}, status=400)

    with transaction.atomic():
        User.objects.select_for_update().get(pk=request.user.pk)
        own_balance = models.WalletTransaction.balance_for_user(request.user)
        if own_balance < stake:
            return JsonResponse({
                "detail": "Insufficient coins for the selected Quick Match amount.",
                "code": "insufficient_coins", "required": str(stake),
                "balance": str(own_balance), "shortfall": str(stake - own_balance),
            }, status=412)
        existing = models.HeadToHeadTable.objects.select_for_update().filter(
            game_format='legacy',
            host=request.user,
            mode=models.HeadToHeadTable.MODE_MATCH,
            is_quick_match=True,
            status=models.HeadToHeadTable.STATUS_OPEN,
            target_points=target_points,
            time_control=time_control,
            doubling_enabled=doubling_enabled,
        )
        existing = next((table for table in existing if sorted(Decimal(value) for value in (table.quick_stakes or [table.amount])) == stakes), None)
        if existing:
            payload = _serialize_head_to_head(existing)
            payload["matched"] = False
            return JsonResponse(payload)

        candidates = models.HeadToHeadTable.objects.select_for_update().select_related('host').filter(
            game_format='legacy',
            mode=models.HeadToHeadTable.MODE_MATCH,
            is_quick_match=True,
            status=models.HeadToHeadTable.STATUS_OPEN,
            guest__isnull=True,
            target_points=target_points,
            time_control=time_control,
            doubling_enabled=doubling_enabled,
        ).exclude(host=request.user).order_by('created_at')

        for candidate in candidates:
            common_stakes = sorted(set(stakes).intersection(Decimal(value) for value in (candidate.quick_stakes or [candidate.amount])))
            if not common_stakes:
                continue
            list(User.objects.select_for_update().filter(
                pk__in=sorted((candidate.host_id, request.user.id)),
            ).order_by('pk'))
            host_balance = models.WalletTransaction.balance_for_user(candidate.host)
            affordable = [value for value in common_stakes if value <= host_balance]
            if affordable:
                stake = affordable[0]
                candidate.amount = stake
                fee = (stake * settings_row.head_to_head_fee_percent / Decimal("100")).quantize(Decimal("0.01"))
                candidate.fee_percent = settings_row.head_to_head_fee_percent
                candidate.fee_per_player = fee
                for player in (candidate.host, request.user):
                    models.WalletTransaction.create_entry(
                        user=player,
                        amount=-stake,
                        kind=models.WalletTransaction.KIND_HEAD_TO_HEAD_ENTRY,
                        head_to_head_table=candidate,
                        note=f"Quick Match table {candidate.code}",
                    )
                candidate.guest = request.user
                candidate.status = models.HeadToHeadTable.STATUS_READY
                candidate.save(update_fields=[
                    'amount', 'fee_percent', 'fee_per_player', 'guest', 'status', 'updated_at',
                ])
                from .push import queue_guest_joined_push
                queue_guest_joined_push(candidate)
                payload = _serialize_head_to_head(candidate)
                payload["matched"] = True
                return JsonResponse(payload)
            if not any(Decimal(value) <= host_balance for value in (candidate.quick_stakes or [candidate.amount])):
                candidate.status = models.HeadToHeadTable.STATUS_CANCELLED
                candidate.save(update_fields=['status', 'updated_at'])

        table = models.HeadToHeadTable.objects.create(
            code=_new_table_code(),
            mode=models.HeadToHeadTable.MODE_MATCH,
            host=request.user,
            amount=min(stakes),
            quick_stakes=stored_stakes,
            fee_percent=settings_row.head_to_head_fee_percent,
            fee_per_player=(min(stakes) * settings_row.head_to_head_fee_percent / Decimal("100")).quantize(Decimal("0.01")),
            target_points=target_points,
            time_control=time_control,
            doubling_enabled=doubling_enabled,
            is_quick_match=True,
        )
        payload = _serialize_head_to_head(table)
        payload["matched"] = False
        return JsonResponse(payload, status=201)


def _recurring_bonus_payload(user, settings_row):
    latest = models.WalletTransaction.objects.filter(
        user=user,
        kind=models.WalletTransaction.KIND_RECURRING_BONUS,
    ).order_by('-created_at').first()
    next_available_at = (
        latest.created_at + timedelta(hours=settings_row.coin_grant_interval_hours)
        if latest else timezone.now()
    )
    return {
        "enabled": settings_row.coin_grant_enabled,
        "amount": str(settings_row.coin_grant_amount),
        "interval_hours": settings_row.coin_grant_interval_hours,
        "available": settings_row.coin_grant_enabled and next_available_at <= timezone.now(),
        "next_available_at": next_available_at.isoformat(),
        "balance": str(models.WalletTransaction.balance_for_user(user)),
    }


@require_http_methods(["GET", "POST"])
def api_recurring_coin_bonus(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required"}, status=401)
    settings_row = models.DirectPlaySettings.load()
    if request.method == "GET":
        return JsonResponse(_recurring_bonus_payload(request.user, settings_row))
    with transaction.atomic():
        locked_user = User.objects.select_for_update().get(pk=request.user.pk)
        payload = _recurring_bonus_payload(locked_user, settings_row)
        if not payload["enabled"]:
            return JsonResponse({"detail": "The recurring coin bonus is disabled."}, status=412)
        if not payload["available"]:
            return JsonResponse({
                "detail": "The recurring coin bonus is not available yet.",
                "next_available_at": payload["next_available_at"],
            }, status=409)
        models.WalletTransaction.create_entry(
            user=locked_user,
            amount=settings_row.coin_grant_amount,
            kind=models.WalletTransaction.KIND_RECURRING_BONUS,
            note=f"Recurring {settings_row.coin_grant_interval_hours}-hour coin bonus",
        )
        return JsonResponse(_recurring_bonus_payload(locked_user, settings_row))


@require_http_methods(["POST"])
def api_head_to_head_join(request, code):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required"}, status=401)
    settings_row = models.DirectPlaySettings.load()
    if not settings_row.enabled:
        return JsonResponse({"detail": "One-on-one games are currently disabled."}, status=412)
    try:
        with transaction.atomic():
            table = models.HeadToHeadTable.objects.select_for_update().select_related('host').get(code=code.upper())
            if table.game_format == 'legacy' and not settings_row.mode_enabled('quick' if table.is_quick_match else table.mode):
                return JsonResponse({"detail": "This game mode is currently disabled."}, status=412)
            if table.game_format == 'legacy':
                legacy_profile = settings_row.format_profiles['match']
                access = 'quick' if table.is_quick_match else 'private' if table.mode == 'friend' else 'public'
                if not legacy_profile['enabled'] or not legacy_profile[access]:
                    return JsonResponse({'detail': 'This game format or access method is disabled.'}, status=412)
            if table.status != models.HeadToHeadTable.STATUS_OPEN or table.guest_id:
                return JsonResponse({"detail": "This table is no longer available."}, status=409)
            if table.is_quick_match:
                return JsonResponse({"detail": "Quick Match tables can only be joined through matchmaking."}, status=409)
            if table.host_id == request.user.id:
                return JsonResponse({"detail": "You cannot join your own table."}, status=400)
            if table.game_format != 'legacy':
                from .game_formats import join_table
                try:
                    join_table(table, request.user, settings_row)
                except ValidationError as error:
                    return JsonResponse({'detail': '; '.join(error.messages)}, status=400)
                return JsonResponse(_serialize_head_to_head(table))
            # Lock both balances in a stable order before charging either player.
            list(User.objects.select_for_update().filter(pk__in=sorted([table.host_id, request.user.id])).order_by('pk'))
            charge = table.fee_per_player if table.is_friend_game else table.amount
            kind = models.WalletTransaction.KIND_FRIEND_GAME_FEE if table.is_friend_game else models.WalletTransaction.KIND_HEAD_TO_HEAD_ENTRY
            guest_balance = models.WalletTransaction.balance_for_user(request.user)
            if guest_balance < charge:
                return JsonResponse({"detail": "Insufficient coins to join this table.", "code": "insufficient_coins", "required": str(charge), "balance": str(guest_balance), "shortfall": str(charge - guest_balance)}, status=412)
            if models.WalletTransaction.balance_for_user(table.host) < charge:
                return JsonResponse({"detail": "The host no longer has enough coins for this table.", "code": "opponent_insufficient_coins"}, status=412)
            for player in (table.host, request.user):
                models.WalletTransaction.create_entry(
                    user=player, amount=-charge, kind=kind, head_to_head_table=table,
                    note=f"{table.get_mode_display()} table {table.code}",
                )
            table.guest = request.user
            table.status = models.HeadToHeadTable.STATUS_READY
            table.save(update_fields=['guest', 'status', 'updated_at'])
            from .push import queue_guest_joined_push
            queue_guest_joined_push(table)
    except models.HeadToHeadTable.DoesNotExist:
        return JsonResponse({"detail": "Table not found."}, status=404)
    return JsonResponse(_serialize_head_to_head(table))


def _refund_head_to_head(table, actor=None):
    charges = table.wallet_transactions.filter(amount__lt=0).select_related('user')
    for charge in charges:
        already_refunded = table.wallet_transactions.filter(
            user=charge.user, kind=models.WalletTransaction.KIND_HEAD_TO_HEAD_REFUND,
        ).exists()
        if not already_refunded:
            models.WalletTransaction.create_entry(
                user=charge.user, amount=-charge.amount,
                kind=models.WalletTransaction.KIND_HEAD_TO_HEAD_REFUND,
                head_to_head_table=table, actor=actor,
                note=f"Refund for cancelled table {table.code}",
            )


@require_http_methods(["POST"])
def api_head_to_head_cancel(request, code):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required"}, status=401)
    with transaction.atomic():
        table = get_object_or_404(models.HeadToHeadTable.objects.select_for_update(), code=code.upper())
        if table.host_id != request.user.id:
            return JsonResponse({"detail": "Only the table owner can cancel it."}, status=403)
        if table.status not in (models.HeadToHeadTable.STATUS_OPEN, models.HeadToHeadTable.STATUS_READY):
            return JsonResponse({"detail": "This table can no longer be cancelled."}, status=409)
        _refund_head_to_head(table)
        table.status = models.HeadToHeadTable.STATUS_CANCELLED
        table.save(update_fields=['status', 'updated_at'])
    return JsonResponse(_serialize_head_to_head(table))


@require_http_methods(["GET", "PUT"])
def api_admin_direct_play_settings(request):
    err = _require_staff(request)
    if err:
        return err
    row = models.DirectPlaySettings.load()
    if request.method == "PUT":
        try:
            data = json.loads(request.body or "{}")
            row.enabled = _parse_bool(data.get("enabled"), row.enabled)
            if 'format_profiles' in data:
                models.validate_format_profiles(data['format_profiles'])
                row.format_profiles = data['format_profiles']
            if "game_rules" in data:
                models.validate_game_rules(data["game_rules"])
                row.game_rules = data["game_rules"]
                for rule in row.game_rules.values():
                    rule['target_points'].sort()
            if "stake_amounts" in data:
                models.validate_stake_amounts(data["stake_amounts"])
                row.stake_amounts = sorted(data["stake_amounts"])
            row.friend_game_fee = _parse_money(data.get("friend_game_fee", row.friend_game_fee), "friend_game_fee")
            row.head_to_head_fee_percent = _parse_money(data.get("head_to_head_fee_percent", row.head_to_head_fee_percent), "head_to_head_fee_percent")
            row.tournament_fee_percent = _parse_money(data.get("tournament_fee_percent", row.tournament_fee_percent), "tournament_fee_percent")
            row.coin_grant_enabled = _parse_bool(data.get("coin_grant_enabled"), row.coin_grant_enabled)
            row.coin_grant_amount = _parse_money(data.get("coin_grant_amount", row.coin_grant_amount), "coin_grant_amount")
            row.coin_grant_interval_hours = int(data.get("coin_grant_interval_hours", row.coin_grant_interval_hours))
            if row.head_to_head_fee_percent > 100:
                raise ValidationError("The Match Play fee cannot exceed 100%.")
            if not Decimal("8") <= row.tournament_fee_percent <= Decimal("10"):
                raise ValidationError("The tournament fee must be between 8% and 10%.")
            row.full_clean()
            row.save()
        except (json.JSONDecodeError, ValueError, ValidationError) as error:
            messages = getattr(error, 'messages', [str(error)])
            return JsonResponse({"detail": "; ".join(messages)}, status=400)
    return JsonResponse({
        "enabled": row.enabled,
        "friend_game_fee": str(row.friend_game_fee),
        "stake_amounts": row.stake_amounts,
        "game_rules": row.game_rules,
        "format_profiles": row.format_profiles,
        "head_to_head_fee_percent": str(row.head_to_head_fee_percent),
        "tournament_fee_percent": str(row.tournament_fee_percent),
        "coin_grant_enabled": row.coin_grant_enabled,
        "coin_grant_amount": str(row.coin_grant_amount),
        "coin_grant_interval_hours": row.coin_grant_interval_hours,
        "updated_at": row.updated_at.isoformat(),
    })


@require_http_methods(["GET"])
def api_admin_head_to_head_tables(request):
    err = _require_staff(request)
    if err:
        return err
    tables = models.HeadToHeadTable.objects.select_related('host', 'guest', 'winner')
    status_filter = request.GET.get('status')
    if status_filter:
        tables = tables.filter(status=status_filter)
    # Never let recent history hide a player who is still waiting or playing.
    closed = (models.HeadToHeadTable.STATUS_COMPLETED, models.HeadToHeadTable.STATUS_CANCELLED)
    active = list(tables.exclude(status__in=closed))
    history = tables.filter(status__in=closed)
    return JsonResponse({
        "tables": [_serialize_admin_direct_play(table) for table in active + list(history[:250])],
        "history_total": history.count(),
        "history_limit": 250,
    })


def _serialize_admin_direct_play(table):
    return {
        **_serialize_head_to_head(table),
        "host_id": table.host_id,
        "guest_id": table.guest_id,
        "winner_id": table.winner_id,
        "updated_at": table.updated_at.isoformat(),
        "completed_at": table.completed_at.isoformat() if table.completed_at else None,
    }


@require_http_methods(["POST"])
def api_admin_head_to_head_cancel(request, pk):
    err = _require_staff(request)
    if err:
        return err
    with transaction.atomic():
        table = get_object_or_404(models.HeadToHeadTable.objects.select_for_update(), pk=pk)
        if table.status in (models.HeadToHeadTable.STATUS_COMPLETED, models.HeadToHeadTable.STATUS_CANCELLED):
            return JsonResponse({"detail": "This table is already closed."}, status=409)
        _refund_head_to_head(table, actor=request.user)
        table.status = models.HeadToHeadTable.STATUS_CANCELLED
        table.save(update_fields=['status', 'updated_at'])
    return JsonResponse(_serialize_admin_direct_play(table))


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
        state = request.GET.get("state")
        q = request.GET.get("q")
        if state in ("draft", "open", "active", "finished"):
            qs = [tournament for tournament in qs if tournament.state == state]
        if q:
            if hasattr(qs, "filter"):
                qs = qs.filter(name__icontains=q)
            else:
                q_lower = q.lower()
                qs = [tournament for tournament in qs if q_lower in tournament.name.lower()]
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
    # Save metadata and publish together, so a failed create cannot leave a partial draft.
    # Other callers can still explicitly create drafts by omitting open_registration.
    with transaction.atomic():
        tournament = form.create_tournament(request)
        for k, v in extra_kwargs.items():
            setattr(tournament, k, v)
        tournament.published = data.get("open_registration") is True
        tournament.save(update_fields=[*extra_kwargs.keys(), "published"])
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


@require_http_methods(["POST"])
def api_admin_tournament_publish(request, pk):
    err = _require_staff(request)
    if err:
        return err
    t = get_object_or_404(models.Tournament, pk=pk)
    if t.state != "draft":
        return JsonResponse({"detail": f"Cannot publish, state={t.state}"}, status=412)
    t.published = True
    t.registration_closed_at = None
    t.registration_closed_reason = ''
    t.clear_draw()
    t.results_confirmed_at = None
    t.save(update_fields=[
        "published", "registration_closed_at", "registration_closed_reason", "draw_order", "draw_generated_at",
        "draw_confirmed_at", "results_confirmed_at",
    ])
    return JsonResponse(_serialize_tournament(t, request))


@require_http_methods(["POST"])
def api_admin_tournament_draft(request, pk):
    err = _require_staff(request)
    if err:
        return err
    t = get_object_or_404(models.Tournament, pk=pk)
    if t.state != "open":
        return JsonResponse({"detail": f"Cannot draft, state={t.state}"}, status=412)
    with transaction.atomic():
        if t.entry_fee > 0:
            for participation in t.participations.select_related("participant__user"):
                registration = _ensure_registration(t, participation.participant)
                _refund_registration(t, registration, request.user)
        t.published = False
        t.registration_closed_at = None
        t.registration_closed_reason = ''
        t.clear_draw()
        t.results_confirmed_at = None
        t.participations.all().delete()
        t.registrations.all().delete()
        t.save(update_fields=[
            "published", "registration_closed_at", "registration_closed_reason", "draw_order", "draw_generated_at",
            "draw_confirmed_at", "results_confirmed_at",
        ])
    return JsonResponse(_serialize_tournament(t, request))


def _attendee_rows(tournament):
    participations = {
        participation.participant_id: participation
        for participation in tournament.participations.select_related('participant__user')
    }
    registrations = {
        registration.participant_id: registration
        for registration in tournament.registrations.select_related('participant__user')
    }
    rows = []
    for participant_id in sorted(
        set(participations) | set(registrations),
        key=lambda item: (
            participations[item].slot_id if item in participations else 10**9,
            registrations[item].registered_at if item in registrations else timezone.now(),
        ),
    ):
        participation = participations.get(participant_id)
        registration = registrations.get(participant_id)
        participant = (
            participation.participant if participation else registration.participant
        )
        status = registration.status if registration else models.TournamentRegistration.STATUS_REGISTERED
        if participation and participation.disqualified_at:
            status = models.TournamentRegistration.STATUS_DISQUALIFIED
        payment_status = (
            registration.payment_status
            if registration else models.TournamentRegistration.PAYMENT_PAID
        )
        checked_in_at = registration.checked_in_at if registration else None
        attention_reasons = []
        if status == models.TournamentRegistration.STATUS_WAITLISTED:
            attention_reasons.append('waitlisted')
        elif status == models.TournamentRegistration.STATUS_REGISTERED:
            if payment_status == models.TournamentRegistration.PAYMENT_UNPAID:
                attention_reasons.append('payment')
        rows.append({
            'id': participant.id,
            'name': participant.name,
            'user_id': participant.user_id,
            'username': participant.user.username if participant.user else None,
            'status': status,
            'payment_status': payment_status,
            'refundable': str(
                tournament.entry_fee
                if participant.user_id is not None
                and payment_status == models.TournamentRegistration.PAYMENT_PAID
                else Decimal('0.00')
            ),
            'checked_in_at': checked_in_at.isoformat() if checked_in_at else None,
            'withdrawn_at': (
                registration.withdrawn_at.isoformat()
                if registration and registration.withdrawn_at else None
            ),
            'internal_note': registration.internal_note if registration else '',
            'disqualified': status == models.TournamentRegistration.STATUS_DISQUALIFIED,
            'requires_attention': bool(attention_reasons),
            'attention_reasons': attention_reasons,
            'slot': participation.slot_id + 1 if participation else None,
        })
    return rows


def _attendee_csv(tournament, rows):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="tournament-{tournament.id}-attendees.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow([
        'Name', 'Username', 'Registration status', 'Payment status',
        'Checked in', 'Internal note',
    ])
    for row in rows:
        writer.writerow([
            row['name'], row['username'] or '', row['status'], row['payment_status'],
            row['checked_in_at'] or '', row['internal_note'],
        ])
    return response


@require_http_methods(["GET", "POST", "PATCH", "DELETE"])
@transaction.atomic
def api_admin_tournament_attendees(request, pk):
    err = _require_staff(request)
    if err:
        return err
    queryset = models.Tournament.objects.select_for_update() if request.method != 'GET' else models.Tournament.objects.all()
    t = get_object_or_404(queryset, pk=pk)

    if request.method == 'GET':
        q = request.GET.get('q', '').strip().lower()
        rows = _attendee_rows(t)
        if q:
            rows = [
                row for row in rows
                if q in row['name'].lower() or q in (row['username'] or '').lower()
            ]
        if request.GET.get('format') == 'csv':
            return _attendee_csv(t, rows)
        excluded_user_ids = [
            row['user_id'] for row in rows
            if row['user_id'] and row['status'] in {'registered', 'waitlisted', 'disqualified'}
        ]
        avail_qs = User.objects.exclude(pk__in=excluded_user_ids).order_by('username')
        if q:
            avail_qs = avail_qs.filter(username__icontains=q)
        available = [
            {
                'id': user.id,
                'username': user.username,
                'phone_number': user.contact.phone_number if hasattr(user, 'contact') else '',
                'balance': str(user.wallet_balance or Decimal('0.00')),
            }
            for user in avail_qs.select_related('contact').annotate(
                wallet_balance=Sum('wallet_transactions__amount')
            )[:50]
        ]
        return JsonResponse({
            'participants': rows,
            'available': available,
            'summary': _registration_summary(t),
            'tournament': _serialize_tournament(t, request),
        })

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'detail': 'Invalid JSON'}, status=400)

    if request.method == 'POST':
        is_full = t.max_players is not None and t.participations.count() >= t.max_players
        if t.state != 'open':
            return JsonResponse({'detail': 'Registration is closed'}, status=412)
        if is_full:
            return JsonResponse({
                'code': 'capacity_full',
                'detail': 'Tournament is full.',
            }, status=412)
        try:
            if data.get('user_id'):
                user = User.objects.get(pk=int(data['user_id']))
                if not models.UserContact.objects.filter(user=user).exclude(phone_number='').exists():
                    return JsonResponse({
                        'errors': {'phone_number': [
                            'Phone number is required before adding this player to a tournament.'
                        ]},
                    }, status=400)
                participant = models.Participant.get_or_create_for_user(user)
            elif data.get('name'):
                name = str(data['name']).strip()
                if not name:
                    return JsonResponse({'detail': 'Name required'}, status=400)
                participant = models.Participant.objects.get_or_create(name=name)[0]
            else:
                return JsonResponse({'detail': 'Provide user_id or name'}, status=400)

            existing = t.registrations.filter(participant=participant).first()
            if existing and existing.status in {'registered', 'waitlisted', 'disqualified'}:
                return JsonResponse({'detail': 'Already registered'}, status=400)
            if existing:
                registration = existing
            else:
                registration = _ensure_registration(
                    t,
                    participant,
                    status=models.TournamentRegistration.STATUS_REGISTERED,
                    payment_status=(
                        models.TournamentRegistration.PAYMENT_PAID
                        if t.entry_fee <= 0 else models.TournamentRegistration.PAYMENT_UNPAID
                    ),
                )
            registration.checked_in_at = None
            registration.withdrawn_at = None
            _add_to_active_roster(t, registration, request.user)
            if t.registration_closed_at is not None or t.draw_generated_at is not None:
                t.registration_closed_at = None
                t.registration_closed_reason = ''
                t.clear_draw()
                t.save(update_fields=[
                    'registration_closed_at', 'registration_closed_reason', 'draw_order',
                    'draw_generated_at', 'draw_confirmed_at',
                ])
            t.close_registration_if_full()
            return JsonResponse({'detail': 'Added', 'status': registration.status})
        except (User.DoesNotExist, ValueError):
            return JsonResponse({'detail': 'User not found'}, status=404)
        except ValidationError as error:
            if 'Insufficient funds.' in error.messages:
                balance = models.WalletTransaction.balance_for_user(user)
                return JsonResponse({
                    'code': 'insufficient_funds',
                    'detail': 'Insufficient balance for the entry fee.',
                    'balance': str(balance),
                    'entry_fee': str(t.entry_fee),
                    'shortfall': str(max(Decimal('0.00'), t.entry_fee - balance)),
                }, status=400)
            return JsonResponse({'detail': error.messages}, status=400)

    participant_ids = data.get('participant_ids') or []
    if request.method == 'DELETE':
        participant_id = request.GET.get('participant_id') or request.GET.get('id') or data.get('participant_id') or data.get('id')
        participant_ids = [participant_id] if participant_id else []
        data['action'] = 'withdraw'
    try:
        participant_ids = list(dict.fromkeys(int(item) for item in participant_ids))
    except (TypeError, ValueError):
        return JsonResponse({'detail': 'participant_ids must contain valid IDs'}, status=400)
    if not participant_ids:
        return JsonResponse({'detail': 'participant_ids required'}, status=400)

    action = data.get('action')
    participants = {
        participant.id: participant
        for participant in models.Participant.objects.filter(pk__in=participant_ids)
    }
    if len(participants) != len(participant_ids):
        return JsonResponse({'detail': 'Participant not found'}, status=404)
    registrations = {}
    for participant_id in participant_ids:
        registration = t.registrations.select_for_update().filter(participant_id=participant_id).first()
        if registration is None and t.participations.filter(participant_id=participant_id).exists():
            registration = _ensure_registration(t, participants[participant_id])
        if registration is None:
            return JsonResponse({'detail': 'Registration not found'}, status=404)
        registrations[participant_id] = registration

    if action == 'update_note':
        if len(participant_ids) != 1:
            return JsonResponse({'detail': 'A note can be updated for one participant at a time'}, status=400)
        registration = registrations[participant_ids[0]]
        registration.internal_note = str(data.get('note') or '')[:1000]
        registration.save(update_fields=['internal_note', 'updated_at'])
    elif action in {'check_in', 'undo_check_in'}:
        if t.state != 'open':
            return JsonResponse({'detail': 'Check-in is only available before the tournament starts'}, status=412)
        for registration in registrations.values():
            if registration.status != models.TournamentRegistration.STATUS_REGISTERED:
                continue
            registration.checked_in_at = timezone.now() if action == 'check_in' else None
            registration.save(update_fields=['checked_in_at', 'updated_at'])
    elif action in {'mark_paid', 'mark_unpaid', 'waive_payment'}:
        status_by_action = {
            'mark_paid': models.TournamentRegistration.PAYMENT_PAID,
            'mark_unpaid': models.TournamentRegistration.PAYMENT_UNPAID,
            'waive_payment': models.TournamentRegistration.PAYMENT_WAIVED,
        }
        for registration in registrations.values():
            registration.payment_status = status_by_action[action]
            registration.save(update_fields=['payment_status', 'updated_at'])
    elif action in {'withdraw', 'disqualify'}:
        if t.state != 'open':
            return JsonResponse({'detail': 'The roster is locked'}, status=412)
        refund_requested = bool(data.get('refund', action == 'withdraw'))
        refunded_count = 0
        for registration in registrations.values():
            participation = t.participations.filter(participant=registration.participant).first()
            if action == 'withdraw':
                registration.status = models.TournamentRegistration.STATUS_WITHDRAWN
                registration.withdrawn_at = timezone.now()
            else:
                registration.status = models.TournamentRegistration.STATUS_DISQUALIFIED
                registration.withdrawn_at = None
            previous_payment_status = registration.payment_status
            if refund_requested:
                _refund_registration(t, registration, request.user)
                if previous_payment_status != registration.payment_status:
                    refunded_count += 1
            registration.checked_in_at = None
            if participation:
                participation.delete()
            registration.save(update_fields=[
                'status', 'payment_status', 'checked_in_at', 'withdrawn_at', 'updated_at',
            ])
        if t.registration_closed_at is not None or t.draw_generated_at is not None:
            t.registration_closed_at = None
            t.registration_closed_reason = ''
            t.clear_draw()
            t.save(update_fields=[
                'registration_closed_at', 'registration_closed_reason', 'draw_order',
                'draw_generated_at', 'draw_confirmed_at',
            ])
    elif action in {'promote', 'restore'}:
        if t.state != 'open':
            return JsonResponse({'detail': 'The roster is locked'}, status=412)
        try:
            for registration in registrations.values():
                _add_to_active_roster(t, registration, request.user)
        except ValidationError as error:
            return JsonResponse({'detail': '; '.join(error.messages)}, status=412)
        if t.registration_closed_at is not None or t.draw_generated_at is not None:
            t.registration_closed_at = None
            t.registration_closed_reason = ''
            t.clear_draw()
            t.save(update_fields=[
                'registration_closed_at', 'registration_closed_reason', 'draw_order',
                'draw_generated_at', 'draw_confirmed_at',
            ])
        t.close_registration_if_full()
    else:
        return JsonResponse({'detail': 'Unsupported attendee action'}, status=400)

    return JsonResponse({
        'detail': 'Updated',
        'participants': _attendee_rows(t),
        'summary': _registration_summary(t),
        **({'refunded_count': refunded_count} if action in {'withdraw', 'disqualify'} else {}),
    })


@require_http_methods(["GET", "POST"])
@transaction.atomic
def api_admin_tournament_progress(request, pk):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required"}, status=401)
    t = get_object_or_404(models.Tournament.objects.select_for_update() if request.method == 'POST' else models.Tournament.objects.all(), pk=pk)
    if t.state == "draft":
        return JsonResponse({"detail": "Tournament is draft"}, status=412)
    if t.state == "open":
        return JsonResponse({"detail": "Tournament has not started"}, status=412)
    if request.method == "GET":
        stages = {}
        current_stage_idx = None
        operational_fixtures = []
        waiting_players = []
        now = timezone.now()
        for idx, stage in enumerate(t.stages.all()):
            levels = []
            for level in range(stage.levels):
                fixtures = []
                for fixture in stage.fixtures.select_related(
                    "player1__user",
                    "player2__user",
                    "game_link",
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
                    playability = _playability_payload(request, fixture)
                    game_link = fixture.game_link if hasattr(fixture, 'game_link') else None
                    live_snapshot = game_link.live_snapshot if game_link else None
                    start_event = fixture.audit_events.filter(
                        action='live_started').order_by('created_at').first()
                    is_current_round = bool(
                        t.current_stage and stage.id == t.current_stage.id
                        and level == stage.current_level
                    )
                    started_at = (
                        start_event.created_at if start_event else
                        game_link.created_at if game_link and game_link.status in {'playing', 'completed'} else None
                    )
                    ended_at = fixture.admin_resolved_at or (
                        game_link.completed_at if game_link else None)
                    last_activity_at = (
                        game_link.live_updated_at if game_link else None
                    ) or started_at or fixture.created_at
                    live_status = live_snapshot.get('status') if isinstance(live_snapshot, dict) else None
                    live_playing = bool(
                        game_link and (
                            game_link.status == 'playing'
                            or live_status == 'playing'
                        )
                    )
                    stalled = bool(
                        live_playing and last_activity_at
                        and (now - last_activity_at).total_seconds() >= 120
                    )
                    if fixture.is_confirmed:
                        operational_status = 'completed'
                    elif fixture.score1 is not None or fixture.confirmations.exists():
                        operational_status = 'review'
                    elif stalled:
                        operational_status = 'stalled'
                    elif live_playing:
                        operational_status = 'playing'
                    elif is_current_round and player1 and player2:
                        operational_status = 'waiting'
                    elif is_current_round and (player1 or player2):
                        operational_status = 'waiting_opponent'
                    else:
                        operational_status = 'upcoming'
                    duration_seconds = None
                    if started_at:
                        duration_seconds = max(0, int(((ended_at or now) - started_at).total_seconds()))

                    fixture_payload = {
                        "id": fixture.id,
                        "stage_id": str(stage.id),
                        "stage_name": stage.name or stage.identifier,
                        "round_name": stage.get_level_name(level),
                        "round_index": level,
                        "is_current_round": is_current_round,
                        "operational_status": operational_status,
                        "ready_at": fixture.created_at.isoformat(),
                        "started_at": started_at.isoformat() if started_at else None,
                        "last_activity_at": last_activity_at.isoformat() if last_activity_at else None,
                        "ended_at": ended_at.isoformat() if ended_at else None,
                        "duration_seconds": duration_seconds,
                        "stalled": stalled,
                        "admin_resolution": fixture.admin_result,
                        "winner_id": fixture.winner.pk if fixture.is_confirmed and fixture.winner else None,
                        "bracket": ({
                            "position": fixture.extras.get("position"),
                            "winner_to": fixture.extras.get("propagate", {}).get("winner"),
                        } if isinstance(stage, models.Knockout) and not stage.double_elimination
                           and isinstance(fixture.extras, dict) else None),

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
                        "can_play": playability["can_play"],
                        "playability": playability,

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
                        "game_result": (
                            game_link.raw_result
                            if game_link and game_link.raw_result
                            else None
                        ),
                        "live": live_snapshot,
                    }
                    fixtures.append(fixture_payload)
                    operational_fixtures.append(fixture_payload)
                    if operational_status == 'waiting_opponent':
                        waiting_player = player1 or player2
                        waiting_players.append({
                            'id': waiting_player.id,
                            'name': waiting_player.name,
                            'user_id': waiting_player.user_id,
                            'fixture_id': fixture.id,
                            'round_name': stage.get_level_name(level),
                        })
                levels.append(
                    {"fixtures": fixtures, "name": stage.get_level_name(level)})
            stages[stage.id] = {
                "levels": levels,
                "bracket_kind": "single_elimination" if isinstance(stage, models.Knockout)
                    and not stage.double_elimination else None,
            }
            if t.current_stage and stage.id == t.current_stage.id:
                current_stage_idx = idx + 1
        if t.current_stage is None:
            current_stage_idx = t.stages.count() + 1
        return JsonResponse({
            "tournament": _serialize_tournament(t, request),
            "stages": stages,
            "current_stage": current_stage_idx,
            "is_finished": t.state == "finished",
            "podium": list(t.podium.values("id", "name")) if t.state == "finished" else [],
            "control_room": {
                "current_stage": (
                    t.current_stage.name or t.current_stage.identifier
                    if t.current_stage else None
                ),
                "current_round": t.current_stage.get_level_name(t.current_stage.current_level) if t.current_stage else None,
                "counts": {
                    status: sum(
                        fixture['operational_status'] == status
                        for fixture in operational_fixtures
                    )
                    for status in ['playing', 'waiting', 'waiting_opponent', 'review', 'stalled', 'completed', 'upcoming']
                },
                "waiting_players": waiting_players,
                "round_total": sum(
                    bool(fixture['is_current_round']) for fixture in operational_fixtures
                ),
                "round_completed": sum(
                    fixture['is_current_round'] and fixture['operational_status'] == 'completed'
                    for fixture in operational_fixtures
                ),
                "stale_after_seconds": 120,
                "generated_at": now.isoformat(),
            },
        })
    # POST - submit score
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)
    try:
        fixture = models.Fixture.objects.select_for_update().get(id=data.get("fixture_id"))
    except models.Fixture.DoesNotExist:
        return JsonResponse({"detail": "Fixture not found"}, status=404)
    # checks
    if t.state != "active":
        return JsonResponse({"detail": f"Tournament not active, state={t.state}"}, status=412)
    if fixture.mode_id != t.current_stage.id:
        return JsonResponse({"detail": "Fixture not in current stage"}, status=412)
    if fixture.level != t.current_stage.current_level:
        return JsonResponse({"detail": "Fixture not in current level"}, status=412)
    if not fixture.players.filter(id=request.user.id).exists():
        return JsonResponse({"detail": "You are not a player in this match"}, status=403)
    if not t.participations.filter(participant__user=request.user).exists():
        return JsonResponse({"detail": "You are not a participant in this tournament"}, status=403)
    try:
        new_score = (int(str(data.get("score1")).strip()),
                     int(str(data.get("score2")).strip()))
    except:
        return JsonResponse({"detail": "Invalid score"}, status=400)
    old_score = [fixture.score1, fixture.score2]
    if fixture.admin_result:
        return JsonResponse({"detail": "Match settled by an administrator."}, status=409)
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
    if old_score != [fixture.score1, fixture.score2]:
        models.FixtureAudit.objects.create(fixture=fixture, actor=request.user, action='player_result',
            before={'score': old_score}, after={'score': [fixture.score1, fixture.score2], 'confirmed': fixture.is_confirmed})
    return JsonResponse({"detail": "Saved", "is_confirmed": fixture.is_confirmed})


def _serialize_draw(tournament):
    participations = {
        participation.participant_id: participation
        for participation in tournament.participations.select_related("participant__user")
    }
    order = list(tournament.draw_order or [])
    has_draw = set(order) == set(participations) and len(order) == len(participations) and bool(order)
    if not has_draw:
        order = list(participations)
    return {
        "tournament_id": tournament.id,
        "lifecycle_state": tournament.lifecycle_state,
        "participant_count": len(participations),
        "min_players": tournament.min_players,
        "generated_at": tournament.draw_generated_at.isoformat() if tournament.draw_generated_at else None,
        "confirmed_at": tournament.draw_confirmed_at.isoformat() if tournament.draw_confirmed_at else None,
        "has_draw": has_draw,
        "participants": [
            {
                "id": participant_id,
                "name": participations[participant_id].participant.name,
                "user_id": participations[participant_id].participant.user_id,
                "username": (
                    participations[participant_id].participant.user.username
                    if participations[participant_id].participant.user else None
                ),
                "position": index + 1,
            }
            for index, participant_id in enumerate(order)
        ],
    }


@require_http_methods(["POST"])
@transaction.atomic
def api_admin_tournament_close_registration(request, pk):
    err = _require_staff(request)
    if err:
        return err
    tournament = get_object_or_404(models.Tournament.objects.select_for_update(), pk=pk)
    if tournament.state != "open":
        return JsonResponse({"detail": f"Cannot close registration, state={tournament.state}"}, status=412)
    if tournament.registration_closed_at is None:
        tournament.registration_closed_at = timezone.now()
        tournament.registration_closed_reason = 'manual'
        tournament.clear_draw()
        tournament.save(update_fields=[
            "registration_closed_at", "registration_closed_reason", "draw_order", "draw_generated_at", "draw_confirmed_at",
        ])
    return JsonResponse(_serialize_tournament(tournament, request))


@require_http_methods(["POST"])
@transaction.atomic
def api_admin_tournament_reopen_registration(request, pk):
    err = _require_staff(request)
    if err:
        return err
    tournament = get_object_or_404(models.Tournament.objects.select_for_update(), pk=pk)
    if tournament.state != "open" or tournament.registration_closed_at is None:
        return JsonResponse({"detail": f"Cannot reopen registration, lifecycle={tournament.lifecycle_state}"}, status=412)
    tournament.registration_closed_at = None
    tournament.registration_closed_reason = ''
    tournament.clear_draw()
    tournament.save(update_fields=[
        "registration_closed_at", "registration_closed_reason", "draw_order", "draw_generated_at", "draw_confirmed_at",
    ])
    return JsonResponse(_serialize_tournament(tournament, request))


@require_http_methods(["GET", "POST"])
@transaction.atomic
def api_admin_tournament_draw(request, pk):
    err = _require_staff(request)
    if err:
        return err
    queryset = models.Tournament.objects.select_for_update() if request.method == "POST" else models.Tournament.objects.all()
    tournament = get_object_or_404(queryset, pk=pk)
    if request.method == "GET":
        return JsonResponse(_serialize_draw(tournament))
    if tournament.lifecycle_state not in {"registration_closed", "draw_ready"}:
        return JsonResponse({"detail": f"Cannot edit draw, lifecycle={tournament.lifecycle_state}"}, status=412)
    participant_ids = list(tournament.participations.values_list("participant_id", flat=True))
    if len(participant_ids) < tournament.min_players:
        return JsonResponse({
            "detail": f"Need at least {tournament.min_players} attendees (you have {len(participant_ids)})",
        }, status=412)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)
    requested_order = data.get("participant_ids")
    if requested_order is None:
        requested_order = participant_ids[:]
        random.SystemRandom().shuffle(requested_order)
    try:
        requested_order = [int(participant_id) for participant_id in requested_order]
    except (TypeError, ValueError):
        return JsonResponse({"detail": "participant_ids must be a list of participant IDs"}, status=400)
    if len(requested_order) != len(participant_ids) or set(requested_order) != set(participant_ids):
        return JsonResponse({"detail": "The draw must contain every registered player exactly once"}, status=400)
    tournament.draw_order = requested_order
    tournament.draw_generated_at = timezone.now()
    tournament.draw_confirmed_at = None
    tournament.save(update_fields=["draw_order", "draw_generated_at", "draw_confirmed_at"])
    return JsonResponse(_serialize_draw(tournament))


@require_http_methods(["POST"])
@transaction.atomic
def api_admin_tournament_confirm_draw(request, pk):
    err = _require_staff(request)
    if err:
        return err
    tournament = get_object_or_404(models.Tournament.objects.select_for_update(), pk=pk)
    if tournament.lifecycle_state != "draw_ready":
        return JsonResponse({"detail": f"Cannot confirm draw, lifecycle={tournament.lifecycle_state}"}, status=412)
    current_ids = set(tournament.participations.values_list("participant_id", flat=True))
    if len(tournament.draw_order) != len(current_ids) or set(tournament.draw_order) != current_ids:
        return JsonResponse({"detail": "The draw no longer matches the registered players"}, status=412)
    try:
        tournament.test()
    except ValidationError as error:
        return JsonResponse({"detail": "; ".join(error.messages)}, status=400)
    tournament.draw_confirmed_at = timezone.now()
    tournament.save(update_fields=["draw_confirmed_at"])
    return JsonResponse(_serialize_draw(tournament))


@require_http_methods(["POST"])
@transaction.atomic
def api_admin_tournament_start(request, pk):
    err = _require_staff(request)
    if err:
        return err
    t = get_object_or_404(models.Tournament.objects.select_for_update(), pk=pk)
    if t.state != "open":
        return JsonResponse({"detail": f"Cannot start, state={t.state}"}, status=412)
    # if t.creator and t.creator_id != request.user.id:
    #     return JsonResponse({"detail": "Only creator can start"}, status=403)
    required = t.min_players
    participant_ids = list(t.participations.values_list("participant_id", flat=True))
    if len(participant_ids) < required:
        return JsonResponse({"detail": f"Need at least {required} attendees (you have {len(participant_ids)})"}, status=412)
    try:
        t.test()
    except ValidationError as e:
        return JsonResponse({"detail": "; ".join(e.messages) if hasattr(e, "messages") else str(e)}, status=400)
    valid_confirmed_draw = (
        t.draw_confirmed_at is not None
        and len(t.draw_order) == len(participant_ids)
        and set(t.draw_order) == set(participant_ids)
    )
    if not valid_confirmed_draw:
        random.SystemRandom().shuffle(participant_ids)
        t.draw_order = participant_ids
    now = timezone.now()
    t.registration_closed_at = t.registration_closed_at or now
    t.registration_closed_reason = t.registration_closed_reason or 'start'
    t.draw_generated_at = t.draw_generated_at or now
    t.draw_confirmed_at = t.draw_confirmed_at or now
    t.save(update_fields=[
        "registration_closed_at", "registration_closed_reason", "draw_order",
        "draw_generated_at", "draw_confirmed_at",
    ])
    try:
        t.apply_draw_order()
    except ValidationError as error:
        return JsonResponse({"detail": "; ".join(error.messages)}, status=412)
    t.update_state()
    return JsonResponse(_serialize_tournament(t, request))


def _admin_finance_payload(days=30):
    now = timezone.now()
    local_today = timezone.localdate(now)
    finance_kinds = {
        models.WalletTransaction.KIND_TOURNAMENT_ENTRY,
        models.WalletTransaction.KIND_TOURNAMENT_REFUND,
        models.WalletTransaction.KIND_TOURNAMENT_PRIZE,
    }
    transactions = (
        models.WalletTransaction.objects
        .filter(kind__in=finance_kinds)
        .select_related("tournament")
        .order_by("created_at", "id")
    )
    if days:
        start_date = local_today - timedelta(days=days - 1)
        start_at = timezone.make_aware(
            datetime.combine(start_date, time.min),
            timezone.get_current_timezone(),
        )
        transactions = transactions.filter(created_at__gte=start_at)

    revenue = Decimal("0.00")
    refunds = Decimal("0.00")
    prizes = Decimal("0.00")
    ignored_transactions = 0
    daily = {}
    by_tournament = {}

    def empty_bucket():
        return {
            "revenue": Decimal("0.00"),
            "refunds": Decimal("0.00"),
            "prizes": Decimal("0.00"),
        }

    for item in transactions:
        if item.kind == models.WalletTransaction.KIND_TOURNAMENT_ENTRY:
            if item.amount >= 0:
                ignored_transactions += 1
                continue
            value = -item.amount
            bucket_key = "revenue"
            revenue += value
        elif item.kind == models.WalletTransaction.KIND_TOURNAMENT_REFUND:
            if item.amount <= 0:
                ignored_transactions += 1
                continue
            value = item.amount
            bucket_key = "refunds"
            refunds += value
        elif item.kind == models.WalletTransaction.KIND_TOURNAMENT_PRIZE:
            if item.amount <= 0:
                ignored_transactions += 1
                continue
            value = item.amount
            bucket_key = "prizes"
            prizes += value

        local_date = timezone.localtime(item.created_at).date().isoformat()
        daily.setdefault(local_date, empty_bucket())[bucket_key] += value
        if item.tournament_id:
            tournament_bucket = by_tournament.setdefault(item.tournament_id, {
                "id": item.tournament_id,
                "name": item.tournament.name,
                **empty_bucket(),
            })
            tournament_bucket[bucket_key] += value

    unpaid_registrations = list(
        models.TournamentRegistration.objects
        .filter(
            status=models.TournamentRegistration.STATUS_REGISTERED,
            payment_status=models.TournamentRegistration.PAYMENT_UNPAID,
        )
        .select_related("tournament")
    )
    outstanding = sum(
        (registration.tournament.entry_fee for registration in unpaid_registrations),
        Decimal("0.00"),
    )

    if days:
        dates = [
            (local_today - timedelta(days=offset)).isoformat()
            for offset in range(days - 1, -1, -1)
        ]
    else:
        dates = sorted(daily)

    trend = []
    for date in dates:
        bucket = daily.get(date, empty_bucket())
        expenses = bucket["refunds"] + bucket["prizes"]
        trend.append({
            "date": date,
            "revenue": str(bucket["revenue"]),
            "expenses": str(expenses),
            "net": str(bucket["revenue"] - expenses),
        })

    tournaments = []
    for bucket in by_tournament.values():
        expenses = bucket["refunds"] + bucket["prizes"]
        tournaments.append({
            "id": bucket["id"],
            "name": bucket["name"],
            "revenue": str(bucket["revenue"]),
            "refunds": str(bucket["refunds"]),
            "prizes": str(bucket["prizes"]),
            "expenses": str(expenses),
            "net": str(bucket["revenue"] - expenses),
        })
    tournaments.sort(
        key=lambda item: Decimal(item["revenue"]) + Decimal(item["expenses"]),
        reverse=True,
    )

    expenses = refunds + prizes
    return {
        "updated_at": now.isoformat(),
        "range_days": days,
        "currency": "COINS",
        "summary": {
            "revenue": str(revenue),
            "refunds": str(refunds),
            "prizes": str(prizes),
            "expenses": str(expenses),
            "net": str(revenue - expenses),
            "outstanding": str(outstanding),
            "outstanding_count": len(unpaid_registrations),
        },
        "trend": trend,
        "tournaments": tournaments[:12],
        "ignored_transactions": ignored_transactions,
    }


@require_http_methods(["GET"])
def api_admin_finance(request):
    err = _require_staff(request)
    if err:
        return err
    try:
        days = int(request.GET.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    if days not in {0, 7, 30, 90}:
        return JsonResponse({"detail": "Invalid finance range"}, status=400)
    return JsonResponse(_admin_finance_payload(days))


def _admin_tournaments_by_state():
    tournaments = list(
        models.Tournament.objects
        .prefetch_related("participations", "registrations", "stages__fixtures")
        .order_by("starts_at", "-id")
    )
    by_state = {"draft": [], "open": [], "active": [], "finished": []}
    for tournament in tournaments:
        by_state[tournament.state].append(tournament)
    return by_state


def _admin_tournament_summary(tournament, *, include_registration=False):
    participant_count = tournament.participations.count()
    summary = {
        "id": tournament.id,
        "name": tournament.name,
        "state": tournament.state,
        "starts_at": tournament.starts_at.isoformat() if tournament.starts_at else None,
        "participant_count": participant_count,
        "min_players": tournament.min_players,
        "max_players": tournament.max_players,
    }
    if include_registration:
        summary.update({
            "entry_fee": str(tournament.entry_fee),
            "registration_summary": _registration_summary(tournament),
        })
    return summary


def _admin_active_tournament_summaries(tournaments):
    pending_match_count = 0
    summaries = []
    for tournament in tournaments:
        stage = tournament.current_stage
        current_fixture_query = stage.current_fixtures if stage else None
        current_fixtures = list(
            current_fixture_query
            .select_related("player1", "player2")
            .prefetch_related("confirmations")
        ) if current_fixture_query is not None else []
        playable_fixtures = [
            fixture for fixture in current_fixtures
            if fixture.player1_id and fixture.player2_id
        ]
        pending = sum(
            1 for fixture in playable_fixtures
            if fixture.score1 is None
        )
        completed = sum(1 for fixture in playable_fixtures if fixture.is_confirmed)
        total = len(playable_fixtures)
        next_fixture = next(
            (fixture for fixture in playable_fixtures if not fixture.is_confirmed),
            None,
        )
        pending_match_count += pending
        stage_name = stage.name or stage.identifier if stage else "Tournament"
        round_name = stage.get_level_name(stage.current_level) if stage else None
        summary = _admin_tournament_summary(tournament)
        summary.update({
            "stage": stage_name,
            "round": round_name or "Current round",
            "pending_matches": pending,
            "round_completed_matches": completed,
            "round_total_matches": total,
            "round_progress_percent": round((completed / total) * 100) if total else 0,
            "next_match": {
                "id": next_fixture.id,
                "player1": next_fixture.player1.name,
                "player2": next_fixture.player2.name,
            } if next_fixture else None,
        })
        summaries.append(summary)
    return summaries, pending_match_count


def _admin_operational_notifications(*, by_state, active_tournaments, now, draft_limit=None):
    notifications = []
    for tournament in by_state["open"]:
        participant_count = tournament.participations.count()
        missing = max(tournament.min_players - participant_count, 0)
        if tournament.starts_at and tournament.starts_at < now:
            notification = {
                **_admin_tournament_summary(tournament),
                "kind": "overdue",
                "severity": "critical",
                "message": "Start time has passed",
                "action_label": "Review tournament",
                "action_to": f"/tournaments/{tournament.id}/overview",
            }
        elif missing:
            notification = {
                **_admin_tournament_summary(tournament),
                "kind": "waiting_players",
                "severity": "warning",
                "message": f"Needs {missing} more player{'s' if missing != 1 else ''}",
                "action_label": "Manage players",
                "action_to": f"/tournaments/{tournament.id}/players",
            }
        else:
            notification = {
                **_admin_tournament_summary(tournament),
                "kind": "ready_to_start",
                "severity": "info",
                "message": "Minimum player count reached",
                "action_label": "Start tournament",
                "action_to": f"/tournaments/{tournament.id}/overview",
            }
        notification["notification_id"] = f"{notification['kind']}:{tournament.id}"
        notifications.append(notification)

    for tournament in active_tournaments:
        if tournament["pending_matches"]:
            notifications.append({
                **tournament,
                "notification_id": f"pending_matches:{tournament['id']}",
                "kind": "pending_matches",
                "severity": "warning",
                "message": f"{tournament['pending_matches']} match{'es' if tournament['pending_matches'] != 1 else ''} waiting for results",
                "action_label": "Open control room",
                "action_to": f"/tournaments/{tournament['id']}/live",
            })

    drafts = by_state["draft"] if draft_limit is None else by_state["draft"][:draft_limit]
    for tournament in drafts:
        notifications.append({
            **_admin_tournament_summary(tournament),
            "notification_id": f"draft:{tournament.id}",
            "kind": "draft",
            "severity": "info",
            "message": "Draft has not been published",
            "action_label": "Continue editing",
            "action_to": f"/tournaments/{tournament.id}/overview?edit=1",
        })

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    notifications.sort(key=lambda item: (severity_order[item["severity"]], item["id"]))
    return notifications


def _admin_notification_counts(notifications):
    return {
        "critical": sum(1 for item in notifications if item["severity"] == "critical"),
        "warning": sum(1 for item in notifications if item["severity"] == "warning"),
        "info": sum(1 for item in notifications if item["severity"] == "info"),
    }


@require_http_methods(["GET"])
def api_admin_notifications(request):
    err = _require_staff(request)
    if err:
        return err

    now = timezone.now()
    by_state = _admin_tournaments_by_state()
    active_tournaments, _ = _admin_active_tournament_summaries(by_state["active"])
    notifications = _admin_operational_notifications(
        by_state=by_state,
        active_tournaments=active_tournaments,
        now=now,
    )
    return JsonResponse({
        "updated_at": now.isoformat(),
        "total": len(notifications),
        "counts": _admin_notification_counts(notifications),
        "notifications": notifications,
    })


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
    period_end = now + timedelta(days=days)
    by_state = _admin_tournaments_by_state()

    waiting = [
        tournament for tournament in by_state["open"]
        if tournament.participations.count() < tournament.min_players
    ]
    upcoming = [
        tournament for tournament in by_state["open"]
        if tournament.starts_at and now <= tournament.starts_at <= period_end
    ]

    active_tournaments, pending_match_count = _admin_active_tournament_summaries(
        by_state["active"]
    )
    attention = _admin_operational_notifications(
        by_state=by_state,
        active_tournaments=active_tournaments,
        now=now,
        draft_limit=3,
    )

    active_attention = sum(1 for item in attention if item["kind"] == "pending_matches")
    total_missing_players = sum(
        tournament.min_players - tournament.participations.count()
        for tournament in waiting
    )

    activity = []
    fixture_events = (
        models.FixtureAudit.objects
        .select_related(
            "actor", "fixture__player1", "fixture__player2",
            "fixture__mode__tournament",
        )
        .order_by("-created_at", "-id")[:8]
    )
    for event in fixture_events:
        fixture = event.fixture
        tournament = fixture.mode.tournament
        activity.append({
            "id": f"fixture-{event.id}",
            "kind": "fixture",
            "action": event.action,
            "actor": event.actor.username if event.actor else None,
            "subject": " vs ".join([
                fixture.player1.name if fixture.player1 else "—",
                fixture.player2.name if fixture.player2 else "—",
            ]),
            "tournament_name": tournament.name,
            "created_at": event.created_at.isoformat(),
            "to": f"/tournaments/{tournament.id}/live",
            "_occurred_at": event.created_at,
        })

    wallet_events = (
        models.WalletTransaction.objects
        .select_related("actor", "user", "tournament")
        .order_by("-created_at", "-id")[:8]
    )
    for event in wallet_events:
        activity.append({
            "id": f"wallet-{event.id}",
            "kind": "wallet",
            "action": event.kind,
            "actor": event.actor.username if event.actor else None,
            "subject": event.user.username,
            "amount": str(event.amount),
            "tournament_name": event.tournament.name if event.tournament else None,
            "created_at": event.created_at.isoformat(),
            "to": (
                f"/tournaments/{event.tournament_id}/overview"
                if event.tournament_id else f"/users/{event.user_id}/edit"
            ),
            "_occurred_at": event.created_at,
        })

    registration_events = (
        models.TournamentRegistration.objects
        .select_related("participant", "tournament")
        .order_by("-registered_at", "-id")[:8]
    )
    for event in registration_events:
        activity.append({
            "id": f"registration-{event.id}",
            "kind": "registration",
            "action": "registered",
            "actor": None,
            "subject": event.participant.name,
            "tournament_name": event.tournament.name,
            "created_at": event.registered_at.isoformat(),
            "to": f"/tournaments/{event.tournament_id}/players",
            "_occurred_at": event.registered_at,
        })

    activity.sort(key=lambda item: item["_occurred_at"], reverse=True)
    recent_activity = []
    for item in activity[:5]:
        item.pop("_occurred_at")
        recent_activity.append(item)

    return JsonResponse({
        "updated_at": now.isoformat(),
        "range_days": days,
        "kpis": {
            "active": {
                "value": len(by_state["active"]),
                "context": f"{active_attention} require attention",
                "attention_count": active_attention,
            },
            "upcoming": {
                "value": len(upcoming),
                "context": f"In the next {days} day{'s' if days != 1 else ''}",
                "days": days,
            },
            "waiting": {
                "value": len(waiting),
                "context": f"{total_missing_players} players still needed",
                "missing_players": total_missing_players,
            },
            "pending_matches": {"value": pending_match_count, "context": "Waiting for automatic results"},
        },
        "counts": {state: len(items) for state, items in by_state.items()},
        "attention": attention[:8],
        "active_tournaments": active_tournaments[:6],
        "upcoming_tournaments": [
            _admin_tournament_summary(item, include_registration=True)
            for item in upcoming[:6]
        ],
        "recent_activity": recent_activity,
        "finance": _admin_finance_payload(30)["summary"],
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
        return JsonResponse([_serialize_user(u) for u in qs], safe=False)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)
    try:
        initial_balance = _parse_money(data.get("initial_balance", "0"), "initial_balance")
    except ValueError as error:
        return JsonResponse({"errors": {"initial_balance": [str(error)]}}, status=400)
    if initial_balance > Decimal("99999999.99"):
        return JsonResponse({"errors": {"initial_balance": ["initial_balance is too large."]}}, status=400)
    form = AdminUserCreateForm(data)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)
    from .permissions import may_manage_user
    if not may_manage_user(request.user, grant_staff=form.cleaned_data.get('is_staff', False)):
        return JsonResponse({'detail': 'Only a superuser can manage administrator accounts.'}, status=403)
    with transaction.atomic():
        user = form.save()
        if initial_balance:
            models.WalletTransaction.create_entry(
                user=user,
                amount=initial_balance,
                kind=models.WalletTransaction.KIND_DEPOSIT,
                actor=request.user,
                note="Opening balance",
            )
    return JsonResponse(_serialize_user(user), status=201)


@require_http_methods(["GET"])
def api_admin_transfers(request):
    err = _require_staff(request)
    if err:
        return err
    qs = models.WalletTransaction.objects.select_related("user", "actor", "tournament").order_by("-created_at", "-id")
    user_id = request.GET.get("user_id")
    if user_id:
        qs = qs.filter(user_id=user_id)
    return JsonResponse([_serialize_wallet_transaction(item) for item in qs[:200]], safe=False)


@require_http_methods(["GET"])
def api_admin_wallet_transactions(request):
    err = _require_staff(request)
    if err:
        return err

    qs = models.WalletTransaction.objects.select_related(
        "user", "actor", "tournament"
    ).order_by("-created_at", "-id")

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(user__username__icontains=q)
            | Q(user__contact__phone_number__icontains=q)
            | Q(note__icontains=q)
        )

    kind = (request.GET.get("kind") or "").strip()
    valid_kinds = {choice[0] for choice in models.WalletTransaction.KIND_CHOICES}
    if kind:
        if kind not in valid_kinds:
            return JsonResponse({"detail": "Invalid transaction kind"}, status=400)
        qs = qs.filter(kind=kind)

    flow = (request.GET.get("flow") or "").strip()
    if flow == "in":
        qs = qs.filter(amount__gt=0)
    elif flow == "out":
        qs = qs.filter(amount__lt=0)
    elif flow:
        return JsonResponse({"detail": "Invalid flow"}, status=400)

    tournament_id = (request.GET.get("tournament_id") or "").strip()
    if tournament_id:
        try:
            qs = qs.filter(tournament_id=int(tournament_id))
        except (TypeError, ValueError):
            return JsonResponse({"detail": "Invalid tournament_id"}, status=400)

    user_id = (request.GET.get("user_id") or "").strip()
    if user_id:
        try:
            qs = qs.filter(user_id=int(user_id))
        except (TypeError, ValueError):
            return JsonResponse({"detail": "Invalid user_id"}, status=400)

    created_from = (request.GET.get("from") or "").strip()
    if created_from:
        parsed = parse_datetime(created_from)
        if parsed is None:
            return JsonResponse({"detail": "Invalid from date"}, status=400)
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed)
        qs = qs.filter(created_at__gte=parsed)

    created_to = (request.GET.get("to") or "").strip()
    if created_to:
        parsed = parse_datetime(created_to)
        if parsed is None:
            return JsonResponse({"detail": "Invalid to date"}, status=400)
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed)
        qs = qs.filter(created_at__lte=parsed)

    try:
        limit = int(request.GET.get("limit", 100))
    except (TypeError, ValueError):
        limit = 100
    limit = min(max(limit, 1), 500)

    total_count = qs.count()
    try:
        offset = max(0, int(request.GET.get("offset", 0)))
    except (TypeError, ValueError):
        return JsonResponse({"detail": "Invalid offset"}, status=400)
    items = list(qs[offset:offset + limit])
    incoming = sum(item.amount for item in items if item.amount > 0)
    outgoing = sum(item.amount for item in items if item.amount < 0)

    return JsonResponse({
        "count": total_count,
        "limit": limit,
        "offset": offset,
        "incoming": str(incoming),
        "outgoing": str(outgoing),
        "net": str(incoming + outgoing),
        "items": [_serialize_wallet_transaction(item) for item in items],
        "kinds": [
            {"value": value, "label": label}
            for value, label in models.WalletTransaction.KIND_CHOICES
        ],
    })


@require_http_methods(["GET", "PUT", "DELETE"])
def api_admin_user_detail(request, pk):
    err = _require_staff(request)
    if err:
        return err
    u = get_object_or_404(User, pk=pk)
    if request.method == "GET":
        data = _serialize_user(u)
        data["transactions"] = [
            _serialize_wallet_transaction(item)
            for item in u.wallet_transactions.select_related("user", "actor", "tournament")[:50]
        ]
        return JsonResponse(data)
    from .permissions import may_manage_user
    if not may_manage_user(request.user, u):
        return JsonResponse({'detail': 'Only a superuser can manage administrator accounts.'}, status=403)
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
    if 'is_staff' in data and not isinstance(data['is_staff'], bool):
        return JsonResponse({'detail': 'is_staff must be a boolean.'}, status=400)
    if not may_manage_user(request.user, u, grant_staff=data.get('is_staff', False)):
        return JsonResponse({'detail': 'Only a superuser can manage administrator accounts.'}, status=403)
    if "username" in data:
        try:
            u.username = validate_admin_username(data["username"])
        except ValidationError as validation_error:
            return JsonResponse({"errors": {"username": validation_error.messages}}, status=400)
    phone_number = None
    if "phone_number" in data:
        try:
            phone_number = require_phone_number(data["phone_number"])
        except ValidationError as validation_error:
            return JsonResponse({"errors": {"phone_number": validation_error.messages}}, status=400)
    elif not models.UserContact.objects.filter(user=u).exclude(phone_number='').exists():
        return JsonResponse({"errors": {"phone_number": ["Phone number is required."]}}, status=400)
    if "is_staff" in data:
        u.is_staff = bool(data["is_staff"])
    if "is_active" in data:
        u.is_active = bool(data["is_active"])
    if data.get("new_password"):
        try:
            validate_password(data["new_password"], user=u)
        except ValidationError as validation_error:
            return JsonResponse(
                {"errors": {"new_password": validation_error.messages}},
                status=400,
            )
        u.set_password(data["new_password"])
    try:
        u.full_clean()
        with transaction.atomic():
            u.save()
            if phone_number is not None:
                models.UserContact.objects.update_or_create(
                    user=u,
                    defaults={"phone_number": phone_number},
                )
    except ValidationError as validation_error:
        errors = getattr(validation_error, "message_dict", None)
        if errors is None:
            errors = {"__all__": validation_error.messages}
        return JsonResponse({"errors": errors}, status=400)
    except Exception as e:
        return JsonResponse({"detail": str(e)}, status=400)
    return JsonResponse(_serialize_user(u))


@require_http_methods(["POST"])
def api_admin_user_wallet(request, pk):
    err = _require_staff(request)
    if err:
        return err
    u = get_object_or_404(User, pk=pk)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"detail": "Expected an object"}, status=400)
    note = data.get("note")
    if not isinstance(note, str) or not note.strip() or len(note.strip()) > 255:
        return JsonResponse({"errors": {"note": ["A note of 1–255 characters is required."]}}, status=400)
    try:
        amount = _parse_money(data.get("amount"), "amount")
    except ValueError as error:
        return JsonResponse({"detail": str(error)}, status=400)
    action = data.get("action")
    if action == "withdraw":
        amount = -amount
        kind = models.WalletTransaction.KIND_WITHDRAWAL
    elif action == "deposit":
        kind = models.WalletTransaction.KIND_DEPOSIT
    else:
        return JsonResponse({"detail": "action must be deposit or withdraw"}, status=400)
    try:
        models.WalletTransaction.create_entry(
            user=u,
            amount=amount,
            kind=kind,
            actor=request.user,
            note=note.strip(),
        )
    except Exception as error:
        return JsonResponse({"detail": str(error)}, status=400)
    detail = _serialize_user(u)
    detail["transactions"] = [
        _serialize_wallet_transaction(item)
        for item in u.wallet_transactions.select_related("user", "actor", "tournament")[:50]
    ]
    return JsonResponse(detail)
