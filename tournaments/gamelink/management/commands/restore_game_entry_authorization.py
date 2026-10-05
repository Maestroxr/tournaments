"""Explicit recovery for pre-migration rooms, after checking both verifier seats."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from gamelink.models import GameLink
from gamelink.views import _check_playability
from tournaments.models import Fixture, FixtureAudit, Tournament


class Command(BaseCommand):
    help = (
        'Restore paired admission for one legacy room after verifying the game server '
        'maps both assigned users to this exact fixture and room. Dry run by default.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--tournament-id', type=int, required=True)
        parser.add_argument('--fixture-id', type=int, required=True)
        parser.add_argument('--p1-user-id', type=int, required=True)
        parser.add_argument('--p2-user-id', type=int, required=True)
        parser.add_argument('--room-id', required=True)
        parser.add_argument('--reason', required=True)
        parser.add_argument('--verified-game-server-seats', action='store_true')
        parser.add_argument('--execute', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            Tournament.objects.select_for_update().get(pk=options['tournament_id'])
            # The optional participant/user joins are read for validation;
            # PostgreSQL cannot lock the nullable side of an outer join.
            fixture = Fixture.objects.select_for_update(of=('self',)).select_related(
                'mode__tournament', 'player1__user', 'player2__user',
            ).get(pk=options['fixture_id'], mode__tournament_id=options['tournament_id'])
            link = GameLink.objects.select_for_update().get(fixture=fixture)
        except (Tournament.DoesNotExist, Fixture.DoesNotExist, GameLink.DoesNotExist) as exc:
            raise CommandError('Tournament, fixture or game link does not match.') from exc
        if not options['reason'].strip():
            raise CommandError('A recovery reason is required for the audit trail.')
        if not fixture.player1_id or not fixture.player2_id:
            raise CommandError('Both assigned participants are required.')
        pair = (fixture.player1.user_id, fixture.player2.user_id)
        if pair != (options['p1_user_id'], options['p2_user_id']) or None in pair:
            raise CommandError('Requested users do not match the current ordered pair.')
        for player in (fixture.player1, fixture.player2):
            if _check_playability(player.user, fixture)[1] is not None:
                raise CommandError('Fixture is not currently playable for both assigned users.')
        snapshot = link.live_snapshot or {}
        if (link.status not in ('pending', 'playing') or link.completed_at or link.raw_result
                or not link.external_room_id or link.external_room_id != options['room_id']
                or snapshot.get('room_id') != link.external_room_id
                or snapshot.get('fixture_id') != fixture.pk
                or snapshot.get('tournament_id') != options['tournament_id']
                or snapshot.get('status') not in ('waiting', 'playing')):
            raise CommandError('A matching, nonterminal authenticated room snapshot is required.')
        if link.entry_authorized_at:
            if not link.entry_authorized_for(fixture):
                raise CommandError('Existing grant belongs to a different pair; resolve the room first.')
            self.stdout.write('Already authorized for this pair; nothing changed.')
            return
        self.stdout.write(
            f'fixture={fixture.pk} room={link.external_room_id} '
            f'p1_user={pair[0]} p2_user={pair[1]} status={link.status}'
        )
        if not options['execute']:
            self.stdout.write('Dry run only. Verify both game-server seat mappings before execution.')
            return
        if not options['verified_game_server_seats']:
            raise CommandError('Execution requires --verified-game-server-seats after verifier inspection.')
        link.entry_authorized_at = timezone.now()
        link.entry_player1_id, link.entry_player2_id = pair
        fields = ['entry_authorized_at', 'entry_player1', 'entry_player2']
        # Older releases labelled a waiting-room snapshot as playing. Preserve
        # actual start semantics when recovering that specific legacy state.
        if snapshot['status'] == 'waiting' and link.status == 'playing':
            link.status = 'pending'
            fields.append('status')
        link.save(update_fields=fields)
        FixtureAudit.objects.create(
            fixture=fixture, action='entry_authorized_recovery', reason=options['reason'],
            before={'entry_authorized_at': None},
            after={'room_id': link.external_room_id, 'p1_user_id': pair[0], 'p2_user_id': pair[1]},
        )
        self.stdout.write('Entry authorization restored for the verified pair.')
