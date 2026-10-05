"""The two receivers share durable event ordering, separate from action sequence."""
import copy
import uuid

from django.db import transaction

from tournaments.models import FixtureAudit, HeadToHeadTable

from . import tests as contract_tests


class StatusEventCases:
    def event_body(self, *, revision=1, event_type='started', sequence=8, **overrides):
        occurred_at = '2026-10-05T10:01:00+00:00'
        body = self.live_body(
            sequence=sequence,
            event_id=str(uuid.uuid4()), event_type=event_type, event_revision=revision,
            occurred_at=occurred_at,
            started_at=occurred_at if event_type == 'started' else '2026-10-05T10:00:00+00:00',
            state={'phase': 'moving', 'presence': {
                'needsAdminAdjudication': event_type == 'admin_required',
                'absentSince': {'white': 10, 'black': 11} if event_type == 'admin_required' else {},
            }},
        )
        body.update(overrides)
        return body

    def test_duplicate_event_with_fresh_nonce_does_not_write_or_broadcast_again(self):
        body = self.event_body()
        with self.captureOnCommitCallbacks(execute=False) as first_callbacks:
            response = self.deliver_live(body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['event_id'], body['event_id'])
        self.target.refresh_from_db()
        updated_at = self.target.live_updated_at
        audit_count = FixtureAudit.objects.count()
        with self.captureOnCommitCallbacks(execute=False) as retry_callbacks:
            response = self.deliver_live(body)
        self.assertEqual(response.json(), {'status': 'already_recorded', 'event_id': body['event_id']})
        self.target.refresh_from_db()
        self.assertEqual(self.target.live_updated_at, updated_at)
        self.assertEqual(FixtureAudit.objects.count(), audit_count)
        self.assertEqual(retry_callbacks, [])
        if self.target is self.game_link:
            self.assertTrue(first_callbacks)

    def test_new_admin_revision_at_same_action_sequence_is_recorded(self):
        self.deliver_live(self.event_body())
        body = self.event_body(revision=2, event_type='admin_required')
        self.assertEqual(self.deliver_live(body).status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.live_snapshot, body)
        self.assertEqual(self.target.status, 'playing')
        self.fixture.refresh_from_db()
        self.assertIsNone(self.fixture.score1)
        self.assertIsNone(self.fixture.score2)

    def test_reversed_start_and_admin_events_preserve_latest_admin_state(self):
        start = self.event_body(sequence=1)
        admin = self.event_body(revision=2, event_type='admin_required', sequence=1)
        self.assertEqual(self.deliver_live(admin).status_code, 200)
        self.assertEqual(self.deliver_live(start).json()['status'], 'already_recorded')
        self.target.refresh_from_db()
        self.assertEqual(self.target.live_snapshot, admin)

    def test_delayed_admin_requirement_cannot_overwrite_admin_cleared(self):
        required = self.event_body(revision=2, event_type='admin_required')
        cleared = self.event_body(revision=3, event_type='admin_cleared')
        self.deliver_live(cleared)
        self.deliver_live(required)
        self.target.refresh_from_db()
        self.assertEqual(self.target.live_snapshot, cleared)

    def test_legacy_snapshot_after_status_event_cannot_replace_it(self):
        event = self.event_body(revision=2, event_type='admin_required')
        self.deliver_live(event)
        self.deliver_live(self.live_body(sequence=100))
        self.target.refresh_from_db()
        self.assertEqual(self.target.live_snapshot, event)

    def test_status_event_can_follow_a_legacy_sender(self):
        self.deliver_live(self.live_body(sequence=20))
        event = self.event_body()
        self.deliver_live(event)
        self.target.refresh_from_db()
        self.assertEqual(self.target.live_snapshot, event)

    def test_event_cannot_reopen_a_terminal_target(self):
        self.target.status = 'completed'
        self.target.save(update_fields=['status'])
        event = self.event_body()
        response = self.deliver_live(event)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'already_recorded', 'event_id': event['event_id']})
        self.target.refresh_from_db()
        self.assertEqual(self.target.status, 'completed')
        self.assertIsNone(self.target.live_snapshot)

    def test_invalid_event_metadata_is_rejected_before_recording(self):
        invalid = [
            {'event_id': 'invalid'}, {'event_revision': True}, {'event_revision': 0},
            {'event_type': 'unknown'}, {'occurred_at': '2026-10-05T10:00:00'},
            {'started_at': '2026-10-05T11:00:00+00:00'},
            {'event_type': 'admin_required', 'state': {'presence': {'needsAdminAdjudication': False}}},
        ]
        for overrides in invalid:
            with self.subTest(overrides=overrides):
                response = self.deliver_live(self.event_body(**overrides))
                self.assertEqual(response.status_code, 400)
        body = self.event_body()
        body.pop('event_revision')
        self.assertEqual(self.deliver_live(body).status_code, 400)
        self.target.refresh_from_db()
        self.assertIsNone(self.target.live_snapshot)

    def test_receiver_rollback_allows_retry_of_same_event_and_nonce(self):
        body = self.event_body()
        nonce = uuid.uuid4().hex
        with self.assertRaisesMessage(RuntimeError, 'rollback'):
            with transaction.atomic():
                self.assertEqual(self.deliver_live(body, nonce=nonce).status_code, 200)
                raise RuntimeError('rollback')
        self.target.refresh_from_db()
        self.assertIsNone(self.target.live_snapshot)
        self.assertEqual(self.deliver_live(copy.deepcopy(body), nonce=nonce).status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.live_snapshot, body)


@contract_tests.gamelink_settings
class TournamentStatusEventTests(StatusEventCases, contract_tests.ResultCallbackTestBase):
    def setUp(self):
        super().setUp()
        self.target = self.game_link

    def live_body(self, **overrides):
        return super().live_body(**overrides)

    def test_duplicate_admin_transition_creates_only_one_audit_entry(self):
        event = self.event_body(revision=2, event_type='admin_required')
        self.deliver_live(event)
        self.deliver_live(event)
        self.assertEqual(FixtureAudit.objects.filter(fixture=self.fixture, action='live_admin_required').count(), 1)


@contract_tests.gamelink_settings
class DirectPlayStatusEventTests(StatusEventCases, contract_tests.ResultCallbackTestBase):
    def setUp(self):
        super().setUp()
        self.target = HeadToHeadTable.objects.create(
            code='EVENT1', mode='match', host=self.user1, guest=self.user2,
            amount=10, fee_percent=0, fee_per_player=0, status='ready',
        )

    def live_body(self, **overrides):
        return super().live_body(**{
            'tournament_id': 0, 'fixture_id': -self.target.pk, **overrides,
        })
