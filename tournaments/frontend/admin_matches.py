"""Staff-only match rulings, private notes and wallet refunds."""
import hashlib
import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from gamelink.models import GameLink
from gamelink.commands import deliver_admin_command_safely, queue_admin_command
from tournaments.models import (Fixture, FixtureAdminState, FixtureAudit, Knockout,
                                Participation, Tournament, TournamentRegistration,
                                User, WalletTransaction)


def snapshot(fixture):
    return {'players': [fixture.player1_id, fixture.player2_id], 'score': [fixture.score1, fixture.score2],
            'confirmed': fixture.is_confirmed, 'winner_id': fixture.winner.pk if fixture.winner else None,
            'resolution': fixture.admin_result}


def refundable(tournament, participant):
    if not participant.user_id:
        return Decimal('0.00')
    ledger = WalletTransaction.objects.filter(user_id=participant.user_id, tournament=tournament,
        kind__in=[WalletTransaction.KIND_TOURNAMENT_ENTRY, WalletTransaction.KIND_TOURNAMENT_REFUND])
    return max(Decimal('0.00'), -(ledger.aggregate(total=Sum('amount'))['total'] or Decimal('0.00'))).quantize(Decimal('0.01'))


def rule_allowed(fixture):
    tournament = fixture.mode.tournament
    return (tournament.state == 'active' and tournament.stages.count() == 1
            and isinstance(fixture.mode, Knockout) and not fixture.mode.double_elimination
            and fixture.level == fixture.mode.current_level and not fixture.is_confirmed
            and fixture.player1_id is not None and fixture.player2_id is not None
            and not tournament.participations.filter(participant_id__in=[fixture.player1_id, fixture.player2_id],
                                                       disqualified_at__isnull=False).exists())


def details(fixture):
    state = FixtureAdminState.objects.filter(fixture=fixture).first()
    link = GameLink.objects.filter(fixture=fixture).first()
    live_presence = (((link.live_snapshot or {}).get('state') or {}).get('presence') or {}) if link else {}
    start = fixture.audit_events.filter(action='live_started').order_by('created_at').first()
    version_data = {**snapshot(fixture), 'revision': state.revision if state else 0,
                    'link_status': link.status if link else None}
    players = []
    for player in [fixture.player1, fixture.player2]:
        if player is None:
            continue
        participation = Participation.objects.get(tournament=fixture.mode.tournament, participant=player)
        players.append({'id': player.id, 'name': player.name, 'disqualified': participation.disqualified_at is not None,
                        'refundable': str(refundable(fixture.mode.tournament, player))})
    return {'fixture_id': fixture.id, 'version': hashlib.sha256(json.dumps(version_data, sort_keys=True).encode()).hexdigest(),
            'note': state.note if state else '', 'result': snapshot(fixture), 'can_rule': bool(rule_allowed(fixture)),
            'players': players, 'target_points': fixture.mode.tournament.target_points,
            'needs_admin_adjudication': bool(live_presence.get('needsAdminAdjudication')),
            'absent_since': live_presence.get('absentSince') or {},
            'times': {'connection_created_at': link.created_at.isoformat() if link else None,
                      'live_started_at': start.created_at.isoformat() if start else None,
                      'ended_at': (fixture.admin_resolved_at or (link.completed_at if link else None)).isoformat()
                        if fixture.admin_resolved_at or (link and link.completed_at) else None},
            'history': [{'id': event.id, 'action': event.action, 'actor': event.actor.username if event.actor else None,
                         'at': event.created_at.isoformat(), 'reason': event.reason,
                         'before': event.before, 'after': event.after}
                        for event in fixture.audit_events.select_related('actor').all()]}


def refund(tournament, player, actor, reason):
    if not player.user_id:
        raise ValidationError('This participant has no wallet.')
    User.objects.select_for_update().get(pk=player.user_id)
    amount = refundable(tournament, player)
    if amount <= 0:
        raise ValidationError('There are no unrefunded entry fees for this player.')
    entry = WalletTransaction.create_entry(user=player.user, amount=amount,
        kind=WalletTransaction.KIND_TOURNAMENT_REFUND, tournament=tournament, actor=actor,
        note=f'Disqualification refund: {reason}'[:255])
    registration, _ = TournamentRegistration.objects.get_or_create(
        tournament=tournament,
        participant=player,
        defaults={'status': TournamentRegistration.STATUS_DISQUALIFIED},
    )
    registration.payment_status = TournamentRegistration.PAYMENT_REFUNDED
    registration.save(update_fields=['payment_status', 'updated_at'])
    return {'participant_id': player.pk, 'amount': str(amount), 'transaction_id': entry.pk}


@require_http_methods(['GET', 'POST'])
def admin_match(request, pk, fixture_id):
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'detail': 'Staff access required.'}, status=403)
    if request.method == 'GET':
        fixture = get_object_or_404(Fixture, pk=fixture_id, mode__tournament_id=pk)
        return JsonResponse(details(fixture))
    try:
        body = json.loads(request.body or '{}')
        if not isinstance(body, dict):
            raise ValueError()
    except (ValueError, TypeError):
        return JsonResponse({'detail': 'Invalid JSON.'}, status=400)
    try:
        with transaction.atomic():
            tournament = get_object_or_404(Tournament.objects.select_for_update(), pk=pk)
            fixture = get_object_or_404(Fixture.objects.select_for_update(), pk=fixture_id, mode__tournament=tournament)
            current = details(fixture)
            if body.get('version') != current['version']:
                return JsonResponse({'detail': 'Match changed. Refresh its details before trying again.'}, status=409)
            action = body.get('action')
            if action not in ('note', 'score', 'finish', 'advance', 'disqualify', 'refund'):
                raise ValidationError('Unknown action.')
            reason = body.get('reason', '')
            if not isinstance(reason, str) or len(reason) > 1000 or (action != 'note' and not reason.strip()):
                raise ValidationError('A reason of up to 1000 characters is required.')
            state, _ = FixtureAdminState.objects.get_or_create(fixture=fixture)
            before = snapshot(fixture)
            extra = {}
            if action == 'note':
                note = body.get('note')
                if not isinstance(note, str) or len(note) > 5000:
                    raise ValidationError('The note must be at most 5000 characters.')
                before = {'note': state.note}
                state.note = note.strip()
                extra = {'note': state.note}
            elif action == 'refund':
                if body.get('confirm') is not True:
                    raise ValidationError('Explicit confirmation is required.')
                player = next((p for p in [fixture.player1, fixture.player2] if p and p.pk == body.get('participant_id')), None)
                if player is None or not tournament.participations.filter(participant=player, disqualified_at__isnull=False).exists():
                    raise ValidationError('Refunds here are only available for a disqualified player in this match.')
                extra = {'refund': refund(tournament, player, request.user, reason.strip())}
            else:
                if not current['can_rule']:
                    return JsonResponse({'detail': 'Only unsettled current-round matches with both players in a single-stage knockout can be ruled on. Confirmed results are locked.'}, status=409)
                if body.get('confirm') is not True:
                    raise ValidationError('Explicit confirmation is required.')
                terminal = action in ('finish', 'advance', 'disqualify')
                if action in ('score', 'finish'):
                    scores = [body.get('score1'), body.get('score2')]
                    if any(type(score) is not int or score < 0 or score > 32767 for score in scores):
                        raise ValidationError('Enter two non-negative integer scores.')
                    fixture.score1, fixture.score2 = scores
                    terminal = terminal or max(scores) >= tournament.target_points
                    if terminal and scores[0] == scores[1]:
                        raise ValidationError('A final score must have a winner.')
                    fixture.admin_winner = None
                else:
                    player = next((p for p in [fixture.player1, fixture.player2] if p.pk == body.get('participant_id')), None)
                    if player is None:
                        raise ValidationError('Select a player in this match.')
                    fixture.score1 = fixture.score2 = None
                    fixture.admin_winner = player if action == 'advance' else (
                        fixture.player2 if player.pk == fixture.player1_id else fixture.player1)
                    extra = {'participant_id': player.pk}
                    if action == 'disqualify':
                        tournament.participations.filter(participant=player).update(disqualified_at=timezone.now())
                        registration, _ = TournamentRegistration.objects.get_or_create(
                            tournament=tournament,
                            participant=player,
                        )
                        registration.status = TournamentRegistration.STATUS_DISQUALIFIED
                        registration.checked_in_at = None
                        registration.save(update_fields=['status', 'checked_in_at', 'updated_at'])
                        if body.get('refund') is True:
                            extra['refund'] = refund(tournament, player, request.user, reason.strip())
                fixture.admin_result = action if terminal else ''
                fixture.admin_resolved_at = timezone.now() if terminal else None
                # The legacy score fields allow SQL NULL but not blank form values.
                # Administrative walkovers deliberately carry no invented score.
                if terminal or action not in ('score', 'finish'):
                    fixture.full_clean(exclude=['score1', 'score2'] if action not in ('score', 'finish') else None)
                fixture.save()
                fixture.confirmations.clear()
                link = GameLink.objects.select_for_update().filter(fixture=fixture).first()
                if link is not None:
                    winner = fixture.winner if terminal else None
                    winner_seat = ('p1' if winner and winner.pk == fixture.player1_id else
                                   'p2' if winner and winner.pk == fixture.player2_id else None)
                    command = queue_admin_command(link, {
                        'v': 1,
                        'command_revision': state.revision + 1,
                        'action': 'finish' if terminal else 'score_update',
                        'score': [fixture.score1, fixture.score2],
                        'winner_seat': winner_seat,
                        'reason': reason.strip() if terminal else '',
                    })
                    if terminal:
                        link.status = 'completed'
                        link.completed_at = timezone.now()
                        link.save(update_fields=['status', 'completed_at'])
                    if command is not None:
                        transaction.on_commit(
                            lambda command_id=command.pk: deliver_admin_command_safely(command_id))
                if terminal:
                    tournament.update_state()
            state.revision += 1
            state.save()
            FixtureAudit.objects.create(fixture=fixture, actor=request.user, action=action,
                reason=reason.strip(), before=before, after={**snapshot(fixture), **extra})
            return JsonResponse(details(fixture))
    except ValidationError as error:
        return JsonResponse({'detail': error.messages}, status=400)
