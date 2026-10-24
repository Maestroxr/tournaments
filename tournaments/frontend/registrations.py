"""Shared registration writes. Lock order is tournament, registration, wallet."""

from django.db import transaction
from django.http import Http404
from django.utils import timezone

from tournaments import models


class RegistrationClosed(Exception):
    pass


def ensure_registration(tournament, participant, *, status=None, payment_status=None):
    defaults = {
        'status': status or models.TournamentRegistration.STATUS_REGISTERED,
        'payment_status': payment_status or (
            models.TournamentRegistration.PAYMENT_PAID
            if tournament.entry_fee <= 0 or participant.user_id
            else models.TournamentRegistration.PAYMENT_UNPAID
        ),
    }
    registration, created = models.TournamentRegistration.objects.get_or_create(
        tournament=tournament, participant=participant, defaults=defaults,
    )
    if not created:
        changed = []
        for field, value in (('status', status), ('payment_status', payment_status)):
            if value is not None and getattr(registration, field) != value:
                setattr(registration, field, value)
                changed.append(field)
        if changed:
            registration.save(update_fields=[*changed, 'updated_at'])
    return registration


def refund_registration(tournament, registration, actor):
    participant = registration.participant
    if (
        participant.user_id is not None
        and registration.payment_status == models.TournamentRegistration.PAYMENT_PAID
    ):
        # The ledger, not today's entry fee, determines the remaining reserve.
        models.WalletTransaction.refund_entry_fees(
            user=participant.user, tournament=tournament, actor=actor,
            note=f"Refund for {tournament.name}",
        )
        registration.payment_status = models.TournamentRegistration.PAYMENT_REFUNDED


@transaction.atomic
def withdraw_registration(*, tournament_id, user):
    try:
        tournament = models.Tournament.objects.select_for_update().get(pk=tournament_id)
    except models.Tournament.DoesNotExist as error:
        raise Http404 from error
    if not tournament.published or models.Fixture.objects.filter(mode__tournament=tournament).exists():
        raise RegistrationClosed
    participant = models.Participant.objects.filter(user=user).first()
    participation = tournament.participations.filter(participant=participant).first() if participant else None
    registration = tournament.registrations.select_for_update().filter(participant=participant).first() if participant else None
    if not (participation or registration):
        return tournament
    if participation and (
        tournament.registration_closed_at is not None
        and tournament.registration_closed_reason != 'capacity'
    ):
        raise RegistrationClosed
    if registration is None:
        registration = ensure_registration(tournament, participant)
    if participation:
        refund_registration(tournament, registration, user)
        participation.delete()
    registration.status = models.TournamentRegistration.STATUS_WITHDRAWN
    registration.checked_in_at = None
    registration.withdrawn_at = timezone.now()
    registration.save(update_fields=[
        'status', 'payment_status', 'checked_in_at', 'withdrawn_at', 'updated_at',
    ])
    if tournament.registration_closed_reason == 'capacity':
        tournament.registration_closed_at = None
        tournament.registration_closed_reason = ''
        tournament.clear_draw()
        tournament.save(update_fields=[
            'registration_closed_at', 'registration_closed_reason', 'draw_order',
            'draw_generated_at', 'draw_confirmed_at',
        ])
    return tournament
