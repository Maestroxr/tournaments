"""Invalidate shared lobby reads after committed, visible data changes."""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save

from gamelink.models import GameLink
from tournaments.models import (
    DirectPlaySettings,
    Fixture,
    HeadToHeadTable,
    Participation,
    Tournament,
    TournamentRegistration,
)

logger = logging.getLogger(__name__)
TOURNAMENT_GROUP = 'club_tournaments'
TABLE_GROUP = 'club_public_tables'


def user_group(user_id):
    return f'club_user_{user_id}'


def invalidate_tournaments(using='default'):
    """Bulk writes bypass signals and explicitly invalidate once after commit."""
    from .lobby_revisions import advance
    advance({TOURNAMENT_GROUP}, 'tournaments', using)
    transaction.on_commit(lambda: _send({TOURNAMENT_GROUP}, 'tournaments'), using=using)


# Presence and live board snapshots are not changes to a lobby card. Explicit
# update_fields containing only these fields do not even need a comparison read.
IGNORED_FIELDS = {
    Tournament: {'created_at', 'definition', 'draw_order', 'draw_generated_at'},
    TournamentRegistration: {'registered_at', 'updated_at', 'internal_note', 'checked_in_at'},
    Participation: {'slot_id'},
    Fixture: {'created_at', 'extras'},
    GameLink: {
        'created_at', 'expires_at', 'raw_result', 'live_snapshot', 'live_updated_at',
        'p1_ready_at', 'p2_ready_at',
    },
    HeadToHeadTable: {
        'created_at', 'updated_at', 'live_snapshot', 'live_updated_at',
        'host_ready_at', 'guest_ready_at',
    },
    DirectPlaySettings: {
        'updated_at', 'coin_grant_enabled', 'coin_grant_amount', 'coin_grant_interval_hours',
        'ai_game_fee', 'tournament_fee_percent',
    },
}


def _card_value(field, value):
    if field == 'settlement' and isinstance(value, dict):
        return {key: item for key, item in value.items() if key != 'search_seen_at'}
    return value


def _is_public_table(values):
    return (values.get('mode') == 'match' and values.get('game_format') in ('match', 'money')
            and values.get('status') == 'open' and values.get('guest_id') is None)


def _remember_change(sender, instance, using, update_fields=None, raw=False, **kwargs):
    instance._lobby_changed = False
    instance._lobby_previous = {}
    if raw:
        return
    fields = [field.attname for field in sender._meta.concrete_fields
              if not field.primary_key and field.name not in IGNORED_FIELDS[sender]
              and (update_fields is None or field.name in update_fields or field.attname in update_fields)]
    if not fields:
        return
    # Only comparisons for fields actually being persisted affect invalidation.
    previous_fields = set(fields)
    if sender is HeadToHeadTable:
        previous_fields.update(('mode', 'game_format', 'status', 'host_id', 'guest_id'))
    previous = None if instance._state.adding else sender.objects.using(using).filter(
        pk=instance.pk).values(*previous_fields).first()
    instance._lobby_previous = previous or {}
    instance._lobby_changed = previous is None or any(
        _card_value(field, previous[field]) != _card_value(field, getattr(instance, field))
        for field in fields
    )


def _send(groups, resource):
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        for group in groups:
            async_to_sync(layer.group_send)(group, {
                'type': 'club.invalidate', 'resource': resource,
            })
    except Exception:
        # A broker failure must never turn a committed registration/payment
        # into an HTTP failure. Reconnection refreshes both shared snapshots.
        logger.exception('event=club_invalidation_failed resource=%s', resource)


def _invalidate(sender, instance, using, **kwargs):
    if sender is HeadToHeadTable:
        previous = getattr(instance, '_lobby_previous', {})
        current = {field: getattr(instance, field) for field in (
            'mode', 'game_format', 'status', 'host_id', 'guest_id')}
        users = {current['host_id'], current['guest_id'], previous.get('host_id'), previous.get('guest_id')}
        groups = {user_group(user_id) for user_id in users if user_id is not None}
        if _is_public_table(previous) or _is_public_table(current):
            # Every authenticated viewer can see additions/removals of public
            # searches. Private and playing tables only invalidate their owners.
            groups = {TABLE_GROUP}
        resource = 'tables'
    elif sender is DirectPlaySettings:
        groups, resource = {TABLE_GROUP}, 'tables'
    else:
        groups, resource = {TOURNAMENT_GROUP}, 'tournaments'
    from .lobby_revisions import advance
    advance(groups, resource, using)
    transaction.on_commit(lambda: _send(groups, resource), using=using)
    if sender in (Fixture, GameLink):
        from gamelink.entry_presence import notify_fixture
        fixture_id = instance.pk if sender is Fixture else instance.fixture_id
        transaction.on_commit(lambda: notify_fixture(fixture_id), using=using)


def _saved(sender, instance, using, raw=False, **kwargs):
    if not raw and getattr(instance, '_lobby_changed', False):
        _invalidate(sender, instance, using)


def _confirmations_changed(sender, instance, action, using, **kwargs):
    if action in ('post_add', 'post_remove', 'post_clear'):
        invalidate_tournaments(using)


for model in IGNORED_FIELDS:
    identity = model._meta.label_lower
    pre_save.connect(_remember_change, sender=model, dispatch_uid=f'club.before.{identity}')
    post_save.connect(_saved, sender=model, dispatch_uid=f'club.saved.{identity}')
    post_delete.connect(_invalidate, sender=model, dispatch_uid=f'club.deleted.{identity}')

m2m_changed.connect(_confirmations_changed, sender=Fixture.confirmations.through,
                    dispatch_uid='club.fixture_confirmations')
