"""PostgreSQL must lock writable rows without locking nullable joined accounts."""
import json
from datetime import timedelta
from threading import Thread
from unittest import skipUnless

from django.contrib.auth.models import User
from django.db import connection, connections, transaction
from django.test import RequestFactory, TransactionTestCase
from django.utils import timezone

from frontend.api import api_admin_tournament_progress
from tournaments.models import Fixture, HeadToHeadTable, Knockout, Participant, Participation, Tournament

from . import tests as contracts
from .views import _resolve_current_fixture


@skipUnless(connection.vendor == 'postgresql', 'Requires real PostgreSQL row locks')
@contracts.gamelink_settings
class FixtureLockScopeTests(TransactionTestCase):
    def setUp(self):
        now = timezone.now()
        self.users = [User.objects.create_user(username=f'pg-player-{n}') for n in (1, 2)]
        self.tournament = Tournament.objects.create(
            name='PostgreSQL locking', starts_at=now - timedelta(minutes=1),
            published=True, podium_spec=[], target_points=5, creator=None,
        )
        stage = Knockout.objects.create(tournament=self.tournament)
        self.players = [Participant.create_for_user(user) for user in self.users]
        for slot, player in enumerate(self.players):
            Participation.objects.create(tournament=self.tournament, participant=player, slot_id=slot)
        self.fixture = Fixture.objects.create(
            mode=stage, level=0, player1=self.players[0], player2=self.players[1],
            extras={}, playable_at=now,
        )

    def test_resolving_fixture_does_not_lock_joined_player_accounts(self):
        results, errors = [], []

        def resolve():
            database = connections['default']
            try:
                request = RequestFactory().post('/unused/')
                request.user = self.users[0]
                with transaction.atomic():
                    with database.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout TO '2s'")
                    _, fixture, seat, refusal = _resolve_current_fixture(request, self.tournament.pk)
                    results.append((fixture.pk if fixture else None, seat, refusal))
            except Exception as error:
                errors.append(error)
            finally:
                database.close()

        thread = Thread(target=resolve, daemon=True)
        try:
            with transaction.atomic():
                Participant.objects.select_for_update().get(pk=self.players[0].pk)
                User.objects.select_for_update().get(pk=self.users[0].pk)
                thread.start()
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive(), 'Resolving a fixture waited for joined player rows')
                self.assertEqual(errors, [])
        finally:
            if thread.ident is not None:
                thread.join(timeout=5)
        self.assertEqual(results, [(self.fixture.pk, 'p1', None)])

    def test_score_submission_accepts_a_tournament_without_a_creator(self):
        request = RequestFactory().post(
            '/unused/',
            json.dumps({'fixture_id': self.fixture.pk, 'score1': 5, 'score2': 2}),
            content_type='application/json',
        )
        request.user = self.users[0]
        response = api_admin_tournament_progress(request, self.tournament.pk)
        self.assertEqual(response.status_code, 200, response.content)
        self.fixture.refresh_from_db()
        self.assertEqual((self.fixture.score1, self.fixture.score2), (5, 2))


@contracts.gamelink_settings
class NullableDirectPlayGuestTests(contracts.ResultCallbackTestBase):
    def test_retry_for_completed_table_without_guest_is_acknowledged(self):
        table = HeadToHeadTable.objects.create(
            code='PGNULL', mode='match', host=self.user1, guest=None,
            amount=10, fee_percent=0, fee_per_player=0, status='completed',
        )
        response = self.deliver(self.result_body(tournament_id=0, fixture_id=-table.pk))
        self.assertEqual(response.status_code, 200, response.content)
        table.refresh_from_db()
        self.assertEqual(table.status, 'completed')
        self.assertNothingRecorded()
