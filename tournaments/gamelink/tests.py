import datetime
import hashlib
import json
import logging
import time
import uuid
from io import StringIO
from urllib.parse import unquote

from django.contrib.auth.models import AnonymousUser, User
from django.core import signing
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from tournaments.models import Fixture, Knockout, Participant, Participation, Tournament

from gamelink import checks
from gamelink.housekeeping import minimum_nonce_retention, purge_expired
from gamelink.models import GameLink, IssuedTicket, LinkedAccount, SeenNonce
from gamelink.signing import (
    TICKET_SALT,
    issue_ticket,
    redact,
    result_signature_base,
    sign_result_body,
    verify_result_signature,
    verify_ticket,
)
from gamelink.views import playable_seat

# Fake, obviously non-production secrets. Long enough to satisfy `gamelink.checks`.
TICKET_SECRET = 'test-ticket-secret-not-a-real-one-0123456789'
OTHER_SECRET  = 'test-other-secret-not-a-real-one-9876543210'
RESULT_SECRET = 'test-result-secret-not-a-real-one-0123456789'
ROTATED_SECRET = 'test-rotated-secret-not-a-real-one-0123456789'

gamelink_settings = override_settings(
    GAMELINK_ENABLED = True,
    GAMELINK_TICKET_SECRET = TICKET_SECRET,
    GAMELINK_RESULT_SECRETS = [RESULT_SECRET],
)


class GameLinkTestBase(TestCase):

    def setUp(self):
        self.tournament = Tournament.objects.create(name = 'Test', podium_spec = list())
        self.knockout   = Knockout.objects.create(tournament = self.tournament)
        self.users      = [
            User.objects.create_user(
                id = user_idx + 1,
                username = f'user-{user_idx + 1}',
                password = 'password')
            for user_idx in range(2)
        ]
        self.fixture = Fixture.objects.create(
            mode = self.knockout,
            level = 0,
            player1 = Participant.create_for_user(self.users[0]),
            player2 = Participant.create_for_user(self.users[1]),
        )
        self.game_link = GameLink.objects.create(
            fixture = self.fixture,
            target_points = 1,
            expires_at = timezone.now() + datetime.timedelta(minutes = 10),
        )


@gamelink_settings
class TicketTest(GameLinkTestBase):

    def test_round_trip(self):
        token, jti = issue_ticket(self.users[0], self.fixture, 'p1', self.game_link)
        payload = verify_ticket(token)

        self.assertEqual(payload['v'], 1)
        self.assertEqual(payload['iss'], 'tournaments')
        self.assertEqual(payload['aud'], 'backgammon')
        self.assertEqual(payload['jti'], str(jti))
        self.assertEqual(payload['sub'], str(LinkedAccount.objects.get(user = self.users[0]).external_id))
        self.assertEqual(payload['name'], self.fixture.player1.name)
        self.assertEqual(payload['opp'], self.fixture.player2.name)
        self.assertEqual(payload['trn'], self.tournament.pk)
        self.assertEqual(payload['fix'], self.fixture.pk)
        self.assertEqual(payload['seat'], 'p1')
        self.assertEqual(payload['tp'], 1)
        self.assertEqual(payload['tc'], 'normal')
        self.assertEqual(payload['exp'], payload['iat'] + 120)

    def test_seat_p2_sees_itself_as_own(self):
        token, _ = issue_ticket(self.users[1], self.fixture, 'p2', self.game_link)
        payload = verify_ticket(token)

        self.assertEqual(payload['seat'], 'p2')
        self.assertEqual(payload['name'], self.fixture.player2.name)
        self.assertEqual(payload['opp'], self.fixture.player1.name)

    def test_subject_is_opaque_and_stable(self):
        # The subject must not be the user's primary key, or the ticket would enumerate the
        # tournaments user table (plan §2, threat 10).
        first, _  = issue_ticket(self.users[0], self.fixture, 'p1', self.game_link)
        second, _ = issue_ticket(self.users[0], self.fixture, 'p1', self.game_link)

        subject = verify_ticket(first)['sub']
        self.assertEqual(verify_ticket(second)['sub'], subject)
        self.assertNotEqual(subject, str(self.users[0].pk))
        self.assertEqual(LinkedAccount.objects.filter(user = self.users[0]).count(), 1)

    def test_jti_is_unique_per_ticket(self):
        _, first  = issue_ticket(self.users[0], self.fixture, 'p1', self.game_link)
        _, second = issue_ticket(self.users[0], self.fixture, 'p1', self.game_link)
        self.assertNotEqual(first, second)

    def test_unknown_seat_is_refused(self):
        with self.assertRaises(ValueError):
            issue_ticket(self.users[0], self.fixture, 'p3', self.game_link)

    def test_tampered_payload_is_rejected(self):
        token, _ = issue_ticket(self.users[0], self.fixture, 'p1', self.game_link)
        payload, _, signature = token.rpartition(':')

        # Re-signing a mutated payload with the wrong key is the best a party without the secret
        # can do, and it must not be good enough.
        mutated = signing.dumps(
            dict(verify_ticket(token), seat = 'p2'),
            key = OTHER_SECRET,
            salt = 'gamelink.ticket.v1',
            compress = False)
        flipped = signature[:-1] + ('A' if signature[-1] != 'A' else 'B')
        for candidate in (payload + ':' + flipped, mutated, token[:-1], token + 'x'):
            with self.assertRaises(signing.BadSignature):
                verify_ticket(candidate)

    def test_wrong_secret_is_rejected(self):
        token, _ = issue_ticket(self.users[0], self.fixture, 'p1', self.game_link)
        with override_settings(GAMELINK_TICKET_SECRET = OTHER_SECRET):
            with self.assertRaises(signing.BadSignature):
                verify_ticket(token)

    def test_wrong_salt_is_rejected(self):
        # A signature made with the same key under a different salt must not verify, which is what
        # keeps this channel separate from any other use of `django.core.signing` in the project.
        token = signing.dumps({'v': 1}, key = TICKET_SECRET, salt = 'gamelink.ticket.v0', compress = False)
        with self.assertRaises(signing.BadSignature):
            verify_ticket(token)

    def test_expired_ticket_is_rejected(self):
        token, _ = issue_ticket(self.users[0], self.fixture, 'p1', self.game_link)
        with self.assertRaises(signing.SignatureExpired):
            verify_ticket(token, max_age = -1)

    def test_expired_exp_claim_is_rejected_even_when_the_signature_is_young(self):
        # Belt and braces: `max_age` and the `exp` claim are enforced independently, so neither can
        # be removed by accident.
        with override_settings(GAMELINK_TICKET_TTL = -10):
            token, _ = issue_ticket(self.users[0], self.fixture, 'p1', self.game_link)
        with self.assertRaises(signing.SignatureExpired):
            verify_ticket(token, max_age = 3600)

    def test_audience_mismatch_is_rejected(self):
        token, _ = issue_ticket(self.users[0], self.fixture, 'p1', self.game_link)
        with override_settings(GAMELINK_AUDIENCE = 'other-game-server'):
            with self.assertRaises(signing.BadSignature):
                verify_ticket(token)

    def test_issuer_mismatch_is_rejected(self):
        token, _ = issue_ticket(self.users[0], self.fixture, 'p1', self.game_link)
        with override_settings(GAMELINK_ISSUER = 'somebody-else'):
            with self.assertRaises(signing.BadSignature):
                verify_ticket(token)

    def test_unsupported_version_is_rejected(self):
        token = signing.dumps(
            {'v': 2, 'iss': 'tournaments', 'aud': 'backgammon', 'seat': 'p1', 'exp': int(time.time()) + 120},
            key = TICKET_SECRET,
            salt = 'gamelink.ticket.v1',
            compress = False)
        with self.assertRaises(signing.BadSignature):
            verify_ticket(token)

    def test_missing_expiry_is_rejected(self):
        token = signing.dumps(
            {'v': 1, 'iss': 'tournaments', 'aud': 'backgammon', 'seat': 'p1'},
            key = TICKET_SECRET,
            salt = 'gamelink.ticket.v1',
            compress = False)
        with self.assertRaises(signing.BadSignature):
            verify_ticket(token)

    def test_missing_secret_refuses_to_sign(self):
        with override_settings(GAMELINK_TICKET_SECRET = ''):
            with self.assertRaises(ImproperlyConfigured):
                issue_ticket(self.users[0], self.fixture, 'p1', self.game_link)


@gamelink_settings
class ResultSignatureTest(TestCase):

    def setUp(self):
        self.body = json.dumps({
            'v': 1, 'tournament_id': 17, 'fixture_id': 482, 'status': 'completed',
            'score': {'p1': 1, 'p2': 0}, 'winner_seat': 'p1',
        }).encode()
        self.timestamp = 1756300940
        self.nonce = 'b31c4f8e-0000-4000-8000-000000000000'

    def sign(self, body = None, timestamp = None, nonce = None):
        return sign_result_body(
            self.body if body is None else body,
            self.timestamp if timestamp is None else timestamp,
            self.nonce if nonce is None else nonce)

    def verify(self, header, body = None, timestamp = None, nonce = None):
        return verify_result_signature(
            self.body if body is None else body,
            self.timestamp if timestamp is None else timestamp,
            self.nonce if nonce is None else nonce,
            header)

    def test_round_trip(self):
        header = self.sign()
        self.assertTrue(header.startswith('v1='))
        self.assertTrue(self.verify(header))

    def test_signature_base_matches_the_documented_form(self):
        # This is the wire contract with the backgammon signer (plan §3.2). If this assertion has
        # to change, the other repo changes in the same breath or results stop verifying.
        expected = f'v1:{self.timestamp}:{self.nonce}:{hashlib.sha256(self.body).hexdigest()}'.encode()
        self.assertEqual(result_signature_base(self.body, self.timestamp, self.nonce), expected)

    def test_mutated_body_is_rejected(self):
        header = self.sign()
        mutated = self.body.replace(b'"p1": 1', b'"p1": 7')
        self.assertNotEqual(mutated, self.body)
        self.assertFalse(self.verify(header, body = mutated))

    def test_body_whitespace_is_significant(self):
        # The signature commits to raw bytes, not to the parsed object, so there is no gap between
        # what was signed and what gets deserialized.
        header = self.sign()
        self.assertFalse(self.verify(header, body = self.body + b' '))

    def test_replayed_signature_under_a_different_timestamp_or_nonce_is_rejected(self):
        header = self.sign()
        self.assertFalse(self.verify(header, timestamp = self.timestamp + 1))
        self.assertFalse(self.verify(header, nonce = 'c42d0000-0000-4000-8000-000000000000'))

    def test_wrong_secret_is_rejected(self):
        header = self.sign()
        with override_settings(GAMELINK_RESULT_SECRETS = [OTHER_SECRET]):
            self.assertFalse(self.verify(header))

    def test_rotation_accepts_the_old_secret_while_signing_with_the_new_one(self):
        old_header = self.sign()

        # Step one of the rotation in plan §5: the new secret joins the verifier list.
        with override_settings(GAMELINK_RESULT_SECRETS = [RESULT_SECRET, ROTATED_SECRET]):
            self.assertTrue(self.verify(old_header))

        # Step two: the new secret moves to the front, so it signs while the old one still verifies.
        with override_settings(GAMELINK_RESULT_SECRETS = [ROTATED_SECRET, RESULT_SECRET]):
            new_header = self.sign()
            self.assertNotEqual(new_header, old_header)
            self.assertTrue(self.verify(new_header))
            self.assertTrue(self.verify(old_header))

        # Step three: the old secret is dropped and stops verifying.
        with override_settings(GAMELINK_RESULT_SECRETS = [ROTATED_SECRET]):
            self.assertFalse(self.verify(old_header))

    def test_malformed_headers_are_rejected_without_raising(self):
        good = self.sign()
        digest = good[len('v1='):]
        for header in (
            None,
            b'',
            b'v1=' + digest.encode(),
            42,
            list(),
            '',
            'v1=',
            digest,                       # bare digest, no version prefix
            'v2=' + digest,               # unknown version
            good[:-1],                    # truncated
            good + '0',                   # over-long
            'v1=' + 'z' * 64,             # right length, not hex
            'v1=' + digest + ',v1=' + digest,
            'garbage',
            'v1=%s' % ('0' * 64),
        ):
            self.assertFalse(self.verify(header), repr(header))

    def test_case_insensitive_digest_and_surrounding_whitespace_are_tolerated(self):
        header = self.sign()
        self.assertTrue(self.verify(header.upper().replace('V1=', 'v1=')))
        self.assertTrue(self.verify(f'  {header}\n'))

    def test_string_and_bytes_bodies_sign_identically(self):
        self.assertEqual(self.sign(body = self.body), self.sign(body = self.body.decode()))

    def test_no_secret_configured_refuses_to_sign_and_verifies_nothing(self):
        header = self.sign()
        with override_settings(GAMELINK_RESULT_SECRETS = list()):
            with self.assertRaises(ImproperlyConfigured):
                self.sign()
            self.assertFalse(self.verify(header))

    def test_empty_secrets_in_the_list_are_ignored(self):
        # A half-set environment variable must not become an accepted key.
        header = self.sign()
        with override_settings(GAMELINK_RESULT_SECRETS = ['', RESULT_SECRET, '']):
            self.assertTrue(self.verify(header))
        with override_settings(GAMELINK_RESULT_SECRETS = ['', '']):
            self.assertFalse(self.verify(header))


class RedactTest(TestCase):

    def test_ticket_in_a_url_is_redacted(self):
        text = redact('GET https://bg.example/api/link/enter/?ticket=eyJhbGci.abc123.def456 HTTP/1.1')
        self.assertNotIn('eyJhbGci', text)
        self.assertIn('ticket=[redacted]', text)

    def test_query_parameters_after_the_ticket_survive(self):
        self.assertEqual(
            redact('/api/link/enter/?ticket=abc.def&next=/lobby'),
            '/api/link/enter/?ticket=[redacted]&next=/lobby')

    def test_signature_header_is_redacted(self):
        text = redact('X-Gamelink-Signature: v1=' + 'a' * 64)
        self.assertNotIn('a' * 64, text)
        self.assertIn('[redacted]', text)

    def test_bare_signature_value_is_redacted(self):
        self.assertEqual(redact('v1=' + 'f' * 64), 'v1=[redacted]')

    def test_none_and_non_strings_are_tolerated(self):
        self.assertIsNone(redact(None))
        self.assertEqual(redact(42), '42')

    def test_text_without_anything_secret_is_untouched(self):
        text = 'fixture 482 room 7c9e status completed'
        self.assertEqual(redact(text), text)


@gamelink_settings
class ModelTest(GameLinkTestBase):

    def test_external_id_for_is_idempotent(self):
        first = LinkedAccount.external_id_for(self.users[0])
        self.assertEqual(LinkedAccount.external_id_for(self.users[0]), first)
        self.assertEqual(LinkedAccount.objects.count(), 1)

    def test_external_ids_differ_between_users(self):
        self.assertNotEqual(
            LinkedAccount.external_id_for(self.users[0]),
            LinkedAccount.external_id_for(self.users[1]))

    def test_game_link_defaults(self):
        self.assertEqual(self.game_link.status, 'pending')
        self.assertEqual(self.game_link.provider, 'backgammon')
        self.assertEqual(self.game_link.external_room_id, '')
        self.assertIsNone(self.game_link.completed_at)
        self.assertIsNone(self.game_link.raw_result)

    def test_issued_ticket_records_the_jti_and_not_the_token(self):
        token, jti = issue_ticket(self.users[0], self.fixture, 'p1', self.game_link)
        ticket = IssuedTicket.objects.create(
            jti = jti,
            game_link = self.game_link,
            user = self.users[0],
            seat = 'p1',
            expires_at = timezone.now() + datetime.timedelta(seconds = 120))

        self.assertEqual(str(ticket.jti), str(jti))
        self.assertNotIn(token, [str(field) for field in ticket.__dict__.values()])

    def test_issue_ticket_does_not_record_anything_itself(self):
        # Recording the audit row is the caller's job (session 2), so that minting and recording
        # can share one transaction.
        issue_ticket(self.users[0], self.fixture, 'p1', self.game_link)
        self.assertEqual(IssuedTicket.objects.count(), 0)


class AutoConfirmedFixtureTest(GameLinkTestBase):
    """
    `Fixture.is_confirmed` is load-bearing for stage progression, level display and tournament
    state, so the short-circuit added for machine-reported results is tested directly.
    """

    def test_unscored_fixture_is_never_confirmed(self):
        self.fixture.auto_confirmed = True
        self.fixture.save()
        self.assertFalse(self.fixture.is_confirmed)

    def test_scored_fixture_needs_confirmations_by_default(self):
        self.fixture.score = (1, 0)
        self.fixture.save()
        self.assertFalse(self.fixture.auto_confirmed)
        self.assertFalse(self.fixture.is_confirmed)

    def test_auto_confirmed_scored_fixture_needs_no_confirmations(self):
        self.fixture.score = (1, 0)
        self.fixture.auto_confirmed = True
        self.fixture.save()

        self.assertTrue(self.fixture.is_confirmed)
        self.assertEqual(self.fixture.confirmations.count(), 0)

    def test_auto_confirmed_defaults_to_false(self):
        self.assertFalse(Fixture.objects.get(pk = self.fixture.pk).auto_confirmed)


class ChecksTest(TestCase):

    def run_checks(self, **overrides):
        settings = dict(
            GAMELINK_ENABLED = True,
            DEBUG = False,
            GAMELINK_TICKET_SECRET = TICKET_SECRET,
            GAMELINK_RESULT_SECRETS = [RESULT_SECRET],
            GAMELINK_BACKGAMMON_URL = 'https://backgammon.example',
        )
        settings.update(overrides)
        with override_settings(**settings):
            return [error.id for error in checks.check_gamelink_settings(None)]

    def test_a_sound_configuration_passes(self):
        self.assertEqual(self.run_checks(), list())

    def test_disabled_feature_is_not_checked(self):
        self.assertEqual(self.run_checks(GAMELINK_ENABLED = False, GAMELINK_TICKET_SECRET = ''), list())

    def test_debug_is_not_checked(self):
        self.assertEqual(self.run_checks(DEBUG = True, GAMELINK_TICKET_SECRET = ''), list())

    def test_missing_ticket_secret(self):
        self.assertIn('gamelink.E001', self.run_checks(GAMELINK_TICKET_SECRET = ''))

    def test_short_ticket_secret(self):
        self.assertIn('gamelink.E001', self.run_checks(GAMELINK_TICKET_SECRET = 'short'))

    def test_missing_result_secrets(self):
        self.assertIn('gamelink.E002', self.run_checks(GAMELINK_RESULT_SECRETS = list()))

    def test_short_result_secret(self):
        self.assertIn('gamelink.E002', self.run_checks(GAMELINK_RESULT_SECRETS = [RESULT_SECRET, 'short']))

    def test_channels_must_not_share_a_secret(self):
        self.assertIn('gamelink.E003', self.run_checks(GAMELINK_RESULT_SECRETS = [TICKET_SECRET]))

    def test_ticket_secret_must_not_be_the_django_secret_key(self):
        errors = self.run_checks(SECRET_KEY = TICKET_SECRET)
        self.assertIn('gamelink.E004', errors)

    def test_plain_http_backgammon_url(self):
        self.assertIn('gamelink.E005', self.run_checks(GAMELINK_BACKGAMMON_URL = 'http://backgammon.example'))

    def test_empty_backgammon_url(self):
        self.assertIn('gamelink.E005', self.run_checks(GAMELINK_BACKGAMMON_URL = ''))


class SettingsTest(TestCase):

    def test_the_feature_is_off_and_unconfigured_by_default(self):
        # Nothing committed may enable the link or carry a secret (plan §8, and the project rules
        # in PROGRESS.md).
        from django.conf import settings

        self.assertFalse(settings.GAMELINK_ENABLED)
        self.assertEqual(settings.GAMELINK_TICKET_SECRET, '')
        self.assertEqual(settings.GAMELINK_RESULT_SECRETS, list())
        self.assertEqual(settings.GAMELINK_BACKGAMMON_URL, '')


# Session 2 — the "Go to game" button and ticket issuance
# -------------------------------------------------------

BACKGAMMON_URL = 'https://backgammon.example'

start_game_settings = override_settings(
    GAMELINK_ENABLED = True,
    GAMELINK_TICKET_SECRET = TICKET_SECRET,
    GAMELINK_RESULT_SECRETS = [RESULT_SECRET],
    GAMELINK_BACKGAMMON_URL = BACKGAMMON_URL,
)


class StartGameTestBase(TestCase):
    """
    A published, running tournament whose current level holds a fixture between `user1` and `user2`.

    Unlike :class:`GameLinkTestBase` this registers real `Participation` rows. They are load-bearing
    twice over: `required_confirmations_count` counts participations rather than participants (so
    without them every fixture needs exactly one confirmation, which is not the arrangement a real
    tournament is ever in), and `TournamentProgressView` renders the action row — and therefore the
    button — only for a user who has one.

    `user3` participates in the tournament but plays no fixture in it, which makes them the
    interesting non-participant: the action row *is* rendered for them, so only the play predicate
    can keep the button away.
    """

    def setUp(self):
        self.tournament = Tournament.objects.create(
            name = 'Test', podium_spec = list(), published = True, target_points = 7,
            doubling_enabled = False)
        self.knockout   = Knockout.objects.create(tournament = self.tournament)

        self.user1, self.user2, self.user3 = [
            User.objects.create_user(username = f'player-{user_idx + 1}', password = 'password')
            for user_idx in range(3)
        ]
        self.participants = {
            user.username: Participant.create_for_user(user)
            for user in (self.user1, self.user2, self.user3)
        }
        for slot_id, participant in enumerate(self.participants.values()):
            Participation.objects.create(
                tournament = self.tournament,
                participant = participant,
                slot_id = slot_id)

        self.fixture = Fixture.objects.create(
            mode = self.knockout,
            level = 0,
            player1 = self.participants['player-1'],
            player2 = self.participants['player-2'],
            # A knockout fixture built by hand needs a dict here: the field defaults to a *list*
            # and `Knockout.propagate` reads it as a mapping, so the first `update_state` after
            # this fixture confirms would die on an AttributeError six frames down (**G23**).
            extras = dict(),
        )

    def login(self, user):
        self.assertTrue(self.client.login(username = user.username, password = 'password'))

    def play_url(self, fixture = None):
        return reverse('gamelink-start', kwargs = dict(pk = (fixture or self.fixture).pk))

    def progress_url(self):
        return reverse('tournament-progress', kwargs = dict(pk = self.tournament.pk))

    def add_level_1_fixture(self):
        return Fixture.objects.create(
            mode = self.knockout,
            level = 1,
            player1 = self.participants['player-1'],
            player2 = self.participants['player-2'],
        )

    def confirm_fixture(self):
        self.fixture.score = (1, 0)
        self.fixture.save()
        for user in (self.user1, self.user2):
            self.fixture.confirmations.add(user)
        self.assertTrue(Fixture.objects.get(pk = self.fixture.pk).is_confirmed)


@start_game_settings
class StartGameViewTest(StartGameTestBase):

    def assertNothingIssued(self):
        self.assertEqual(GameLink.objects.count(), 0)
        self.assertEqual(IssuedTicket.objects.count(), 0)

    def test_a_valid_post_redirects_to_the_game_server(self):
        self.login(self.user1)
        response = self.client.post(self.play_url())

        self.assertEqual(response.status_code, 302)
        prefix = f'{BACKGAMMON_URL}/api/link/enter/?ticket='
        self.assertTrue(response['Location'].startswith(prefix), response['Location'])
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        self.assertEqual(response['Cache-Control'], 'no-store')

        self.assertEqual(GameLink.objects.count(), 1)
        self.assertEqual(IssuedTicket.objects.count(), 1)

        game_link = GameLink.objects.get()
        self.assertEqual(game_link.fixture_id, self.fixture.pk)
        self.assertEqual(game_link.status, 'pending')
        self.assertEqual(game_link.target_points, 7)
        self.assertFalse(game_link.doubling_enabled)
        self.assertGreater(game_link.expires_at, timezone.now())

        payload = verify_ticket(unquote(response['Location'][len(prefix):]))
        self.assertEqual(payload['seat'], 'p1')
        self.assertEqual(payload['fix'], self.fixture.pk)
        self.assertEqual(payload['trn'], self.tournament.pk)
        self.assertEqual(payload['tp'], 7)
        self.assertFalse(payload['dbl'])
        self.assertEqual(payload['sub'], str(LinkedAccount.objects.get(user = self.user1).external_id))

        ticket = IssuedTicket.objects.get()
        self.assertEqual(str(ticket.jti), payload['jti'])
        self.assertEqual(ticket.user_id, self.user1.pk)
        self.assertEqual(ticket.seat, 'p1')
        self.assertEqual(ticket.game_link_id, game_link.pk)

    def test_the_ticket_itself_is_never_stored(self):
        self.login(self.user1)
        response = self.client.post(self.play_url())

        token = unquote(response['Location'].split('ticket=', 1)[1])
        self.assertNotIn(token, str(list(IssuedTicket.objects.values())))

    def test_the_seat_comes_from_the_fixture_and_not_from_the_request(self):
        # A player posting somebody else's seat still gets their own (plan §2, threat 4).
        self.login(self.user2)
        response = self.client.post(self.play_url(), dict(seat = 'p1'))

        payload = verify_ticket(unquote(response['Location'].split('ticket=', 1)[1]))
        self.assertEqual(payload['seat'], 'p2')
        self.assertEqual(payload['name'], self.fixture.player2.name)
        self.assertEqual(payload['opp'], self.fixture.player1.name)
        self.assertEqual(IssuedTicket.objects.get().seat, 'p2')

    def test_both_players_share_one_game_link(self):
        for user in (self.user1, self.user2):
            self.login(user)
            self.assertEqual(self.client.post(self.play_url()).status_code, 302)

        self.assertEqual(GameLink.objects.count(), 1)
        self.assertEqual(IssuedTicket.objects.count(), 2)
        self.assertEqual(len({ticket.jti for ticket in IssuedTicket.objects.all()}), 2)
        self.assertEqual({ticket.seat for ticket in IssuedTicket.objects.all()}, {'p1', 'p2'})

    def test_a_second_post_mints_a_fresh_ticket(self):
        self.login(self.user1)
        first  = self.client.post(self.play_url())['Location']
        second = self.client.post(self.play_url())['Location']

        self.assertNotEqual(first, second)
        self.assertEqual(GameLink.objects.count(), 1)
        self.assertEqual(IssuedTicket.objects.count(), 2)

    def test_an_expired_game_link_is_refreshed(self):
        stale = timezone.now() - datetime.timedelta(minutes = 5)
        GameLink.objects.create(fixture = self.fixture, target_points = 1, expires_at = stale)

        self.login(self.user1)
        self.assertEqual(self.client.post(self.play_url()).status_code, 302)

        self.assertEqual(GameLink.objects.count(), 1)
        self.assertGreater(GameLink.objects.get().expires_at, timezone.now())

    def test_get_is_not_allowed(self):
        self.login(self.user1)
        response = self.client.get(self.play_url())

        self.assertEqual(response.status_code, 405)
        self.assertNothingIssued()

    def test_an_anonymous_post_is_sent_to_the_login_page(self):
        response = self.client.post(self.play_url())

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])
        self.assertNothingIssued()

    def test_a_post_without_a_csrf_token_is_forbidden(self):
        # The endpoint mints a bearer credential, so it must not be triggerable cross-site or by a
        # link prefetch (plan §2, threat 14).
        client = Client(enforce_csrf_checks = True)
        self.assertTrue(client.login(username = self.user1.username, password = 'password'))

        self.assertEqual(client.post(self.play_url()).status_code, 403)
        self.assertNothingIssued()

    def test_a_post_with_a_csrf_token_is_accepted(self):
        # The counterpart of the test above: without it, an endpoint that refused *everything*
        # would still look secure.
        client = Client(enforce_csrf_checks = True)
        self.assertTrue(client.login(username = self.user1.username, password = 'password'))
        client.get(self.progress_url())

        response = client.post(self.play_url(), dict(csrfmiddlewaretoken = client.cookies['csrftoken'].value))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(IssuedTicket.objects.count(), 1)

    def test_a_post_by_someone_who_is_not_in_the_fixture_is_forbidden(self):
        self.login(self.user3)
        self.assertEqual(self.client.post(self.play_url()).status_code, 403)
        self.assertNothingIssued()

    def test_a_post_for_an_unknown_fixture_is_refused(self):
        self.login(self.user1)
        url = reverse('gamelink-start', kwargs = dict(pk = self.fixture.pk + 1000))

        self.assertEqual(self.client.post(url).status_code, 412)
        self.assertNothingIssued()

    def test_a_post_is_refused_while_the_feature_is_disabled(self):
        self.login(self.user1)
        with override_settings(GAMELINK_ENABLED = False):
            self.assertEqual(self.client.post(self.play_url()).status_code, 412)
        self.assertNothingIssued()

    def test_a_post_is_refused_without_a_configured_game_server(self):
        self.login(self.user1)
        with override_settings(GAMELINK_BACKGAMMON_URL = ''):
            self.assertEqual(self.client.post(self.play_url()).status_code, 412)

        # Refused *before* anything is minted: a ticket that cannot be delivered anywhere must not
        # exist at all.
        self.assertNothingIssued()

    def test_a_post_is_refused_while_the_tournament_is_not_active(self):
        self.tournament.published = False
        self.tournament.save()

        self.login(self.user1)
        self.assertEqual(self.client.post(self.play_url()).status_code, 412)
        self.assertNothingIssued()

    def test_a_post_is_refused_for_a_fixture_outside_the_current_level(self):
        later = self.add_level_1_fixture()

        self.login(self.user1)
        self.assertEqual(self.client.post(self.play_url(later)).status_code, 412)
        self.assertNothingIssued()

    def test_a_post_is_refused_for_a_confirmed_fixture(self):
        self.confirm_fixture()

        self.login(self.user1)
        self.assertEqual(self.client.post(self.play_url()).status_code, 412)
        self.assertNothingIssued()

    def test_a_post_is_refused_for_an_auto_confirmed_fixture(self):
        self.fixture.score = (1, 0)
        self.fixture.auto_confirmed = True
        self.fixture.save()

        self.login(self.user1)
        self.assertEqual(self.client.post(self.play_url()).status_code, 412)
        self.assertNothingIssued()

    def test_a_post_is_refused_when_the_opponent_is_offline(self):
        self.fixture.player2.user = None
        self.fixture.player2.save()

        self.login(self.user1)
        self.assertEqual(self.client.post(self.play_url()).status_code, 412)
        self.assertNothingIssued()

    def test_a_post_is_refused_once_the_game_has_been_played(self):
        GameLink.objects.create(
            fixture = self.fixture,
            target_points = 1,
            status = 'completed',
            expires_at = timezone.now() + datetime.timedelta(minutes = 10))

        self.login(self.user1)
        self.assertEqual(self.client.post(self.play_url()).status_code, 412)
        self.assertEqual(IssuedTicket.objects.count(), 0)


@start_game_settings
class GoToGameButtonTest(StartGameTestBase):
    """
    The button on the tournament progress page. What matters here is that it is *absent* exactly
    where :class:`StartGameViewTest` shows that a POST would be refused.
    """

    BUTTON = 'Go to game'

    def progress_page(self):
        response = self.client.get(self.progress_url())
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_the_button_is_shown_to_a_player(self):
        self.login(self.user1)
        page = self.progress_page()

        self.assertIn(self.BUTTON, page)
        self.assertIn(f'id="gamelink-play-{self.fixture.pk}"', page)
        self.assertIn(f'action="{self.play_url()}"', page)

        # The play form is a sibling of the score form rather than nested inside it, and the button
        # reaches it through its `form` attribute.
        self.assertIn(f'form="gamelink-play-{self.fixture.pk}"', page)
        self.assertLess(page.index('id="gamelink-play-'), page.index(f'class="fixture-{self.fixture.pk}"'))

    def test_the_button_is_shown_to_both_players(self):
        self.login(self.user2)
        self.assertIn(self.BUTTON, self.progress_page())

    def test_the_button_is_hidden_from_anonymous_users(self):
        self.assertNotIn(self.BUTTON, self.progress_page())

    def test_the_button_is_hidden_from_someone_who_is_not_in_the_fixture(self):
        self.login(self.user3)
        page = self.progress_page()

        # `user3` participates in the tournament, so the action row is rendered for them — only the
        # play predicate keeps the button away.
        self.assertIn('Submit', page)
        self.assertNotIn(self.BUTTON, page)

    def test_the_button_is_hidden_while_the_feature_is_disabled(self):
        self.login(self.user1)
        with override_settings(GAMELINK_ENABLED = False):
            self.assertNotIn(self.BUTTON, self.progress_page())

    def test_the_button_is_hidden_on_a_level_that_is_not_current(self):
        later = self.add_level_1_fixture()

        self.login(self.user1)
        page = self.progress_page()

        self.assertEqual(page.count(self.BUTTON), 1)
        self.assertNotIn(f'id="gamelink-play-{later.pk}"', page)

    def test_the_button_is_hidden_for_a_confirmed_fixture(self):
        self.confirm_fixture()

        self.login(self.user1)
        self.assertNotIn(self.BUTTON, self.progress_page())

    def test_the_button_is_hidden_when_the_opponent_is_offline(self):
        self.fixture.player2.user = None
        self.fixture.player2.save()

        self.login(self.user1)
        self.assertNotIn(self.BUTTON, self.progress_page())

    def test_an_auto_confirmed_fixture_explains_itself(self):
        self.fixture.score = (1, 0)
        self.fixture.auto_confirmed = True
        self.fixture.save()

        self.login(self.user1)
        page = self.progress_page()

        self.assertIn('Result reported by the game server', page)
        self.assertNotIn(self.BUTTON, page)
        # Not the bare class name: the page's own JavaScript mentions `.btn-confirm` regardless.
        self.assertNotIn('btn-outline-success btn-confirm', page)
        self.assertNotIn('Confirmations:', page)


@start_game_settings
class PlayableSeatTest(StartGameTestBase):
    """
    The predicate itself. The button and the endpoint both go through it, which is what stops the
    two from ever disagreeing about who may play what.
    """

    def test_each_player_gets_their_own_seat(self):
        self.assertEqual(playable_seat(self.user1, self.fixture), ('p1', None))
        self.assertEqual(playable_seat(self.user2, self.fixture), ('p2', None))

    def test_a_stranger_is_refused_with_403(self):
        self.assertEqual(playable_seat(self.user3, self.fixture), (None, 403))

    def test_an_anonymous_user_is_refused_with_403(self):
        self.assertEqual(playable_seat(AnonymousUser(), self.fixture), (None, 403))
        self.assertEqual(playable_seat(None, self.fixture), (None, 403))

    def test_a_disabled_feature_is_refused_before_anything_else(self):
        # Checked first and without a query, so that a deployment which does not use the link pays
        # nothing for the button on every fixture of every progress page it renders.
        with override_settings(GAMELINK_ENABLED = False):
            with self.assertNumQueries(0):
                self.assertEqual(playable_seat(self.user1, self.fixture), (None, 412))

    def test_a_state_problem_is_refused_with_412(self):
        self.tournament.published = False
        self.tournament.save()

        self.assertEqual(playable_seat(self.user1, Fixture.objects.get(pk = self.fixture.pk)), (None, 412))


# The result callback (session 6)
# -------------------------------

RESULT_URL = '/api/gamelink/result/'
LIVE_URL = '/api/gamelink/live/'


class ResultCallbackTestBase(TestCase):
    """
    A published, running knockout whose current level holds one linked fixture.

    Two `Participation` rows are registered deliberately, so that
    `required_confirmations_count` is 2 rather than the 1 a fixture built from bare `Participant`
    rows would need (gotcha **G10**). Without them "auto-confirmed with no confirmations" would be
    indistinguishable from "confirmed by nobody, and one was enough anyway".
    """

    ROOM_ID  = '7c9e6679-7425-40de-944b-e07fc1f90ae7'
    MATCH_ID = '3a1f0c2b-4d5e-4a6b-8c7d-9e0f1a2b3c4d'

    def setUp(self):
        self.tournament = Tournament.objects.create(name = 'Test', podium_spec = list(), published = True)
        self.knockout   = Knockout.objects.create(tournament = self.tournament)

        self.user1, self.user2 = [
            User.objects.create_user(username = f'player-{user_idx + 1}', password = 'password')
            for user_idx in range(2)
        ]
        self.participants = {
            user.username: Participant.create_for_user(user)
            for user in (self.user1, self.user2)
        }
        for slot_id, participant in enumerate(self.participants.values()):
            Participation.objects.create(
                tournament = self.tournament,
                participant = participant,
                slot_id = slot_id)

        self.fixture = Fixture.objects.create(
            mode = self.knockout,
            level = 0,
            player1 = self.participants['player-1'],
            player2 = self.participants['player-2'],
            # `Fixture.extras` defaults to a *list*, but `Knockout.propagate` reads it as a dict,
            # so a hand-built knockout fixture crashes `update_state` the moment it is confirmed.
            # Real brackets come out of `Knockout.create_fixtures`, which always writes a dict.
            extras = dict(),
        )
        self.game_link = GameLink.objects.create(
            fixture = self.fixture,
            target_points = 1,
            expires_at = timezone.now() + datetime.timedelta(hours = 2),
        )

        # Every refusal is logged at WARNING and most tests below provoke one on purpose, which
        # would otherwise bury the test output. `assertRejectionLogs` turns it back on for the two
        # tests that pin the logging contract itself.
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def assertRejectionLogs(self):
        logging.disable(logging.NOTSET)
        return self.assertLogs('gamelink.views', level = 'WARNING')

    def result_body(self, **overrides):
        """
        The plan §3.2 body for this fixture, as `game.link.outbox.build_result_body` produces it.
        """
        body = {
            'v'            : 1,
            'tournament_id': self.tournament.pk,
            'fixture_id'   : self.fixture.pk,
            'room_id'      : self.ROOM_ID,
            'match_id'     : self.MATCH_ID,
            'status'       : 'completed',
            'target_points': 1,
            'seats'        : {'p1': 'white', 'p2': 'black'},
            'score'        : {'p1': 1, 'p2': 0},
            'winner_seat'  : 'p1',
            'end_reason'   : 'bear_off',
            'finished_at'  : '2026-08-27T12:02:20Z',
        }
        body.update(overrides)
        return body

    def serialize(self, body):
        # Byte for byte what `deliver_result` puts on the wire: compact separators, sorted keys.
        return json.dumps(body, separators = (',', ':'), sort_keys = True).encode()

    def live_body(self, **overrides):
        body = {
            'v': 1,
            'tournament_id': self.tournament.pk,
            'fixture_id': self.fixture.pk,
            'room_id': self.ROOM_ID,
            'sequence': 3,
            'status': 'playing',
            'state': {
                'phase': 'playing',
                'turn': 'white',
                'dice': [3, 4],
                'cube': 2,
            },
            'match_score': {'white': 0, 'black': 0},
        }
        body.update(overrides)
        return body

    def deliver(self, body = None, raw = None, timestamp = None, nonce = None, signature = None,
                client = None, drop = (), sign_over = None, issuer = 'backgammon'):
        """
        POST a result the way the backgammon server does.

        `sign_over` signs a *different* payload than the one sent, which is how a body mutated
        after signing is simulated.
        """
        if raw is None:
            raw = self.serialize(self.result_body() if body is None else body)
        if timestamp is None:
            timestamp = str(int(time.time()))
        if nonce is None:
            nonce = uuid.uuid4().hex
        if signature is None:
            signature = sign_result_body(raw if sign_over is None else sign_over, timestamp, nonce)

        headers = {
            'HTTP_X_GAMELINK_TIMESTAMP': timestamp,
            'HTTP_X_GAMELINK_NONCE'    : nonce,
            'HTTP_X_GAMELINK_SIGNATURE': signature,
            'HTTP_X_GAMELINK_ISSUER'   : issuer,
        }
        for name in drop:
            headers.pop(name)

        return (client or self.client).post(
            RESULT_URL, data = raw, content_type = 'application/json', **headers)

    def deliver_live(self, body = None, raw = None, timestamp = None, nonce = None, signature = None,
                     client = None):
        if raw is None:
            raw = self.serialize(self.live_body() if body is None else body)
        if timestamp is None:
            timestamp = str(int(time.time()))
        if nonce is None:
            nonce = uuid.uuid4().hex
        if signature is None:
            signature = sign_result_body(raw, timestamp, nonce)

        return (client or self.client).post(
            LIVE_URL,
            data = raw,
            content_type = 'application/json',
            HTTP_X_GAMELINK_TIMESTAMP = timestamp,
            HTTP_X_GAMELINK_NONCE = nonce,
            HTTP_X_GAMELINK_SIGNATURE = signature,
            HTTP_X_GAMELINK_ISSUER = 'backgammon',
        )

    def assertNothingRecorded(self):
        self.fixture.refresh_from_db()
        self.game_link.refresh_from_db()
        self.assertIsNone(self.fixture.score1)
        self.assertIsNone(self.fixture.score2)
        self.assertFalse(self.fixture.auto_confirmed)
        self.assertEqual(self.game_link.status, 'pending')
        self.assertIsNone(self.game_link.raw_result)


@gamelink_settings
class LiveSnapshotCallbackViewTest(ResultCallbackTestBase):
    def test_a_signed_live_snapshot_is_saved_on_the_game_link(self):
        response = self.deliver_live()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {'status': 'recorded'})

        self.game_link.refresh_from_db()
        self.assertEqual(self.game_link.status, 'playing')
        self.assertEqual(self.game_link.external_room_id, self.ROOM_ID)
        self.assertEqual(self.game_link.live_snapshot['sequence'], 3)
        self.assertEqual(self.game_link.live_snapshot['state']['turn'], 'white')
        self.assertIsNotNone(self.game_link.live_updated_at)

    def test_an_older_live_snapshot_does_not_overwrite_a_newer_one(self):
        self.deliver_live(self.live_body(sequence = 5, state = {'phase': 'playing', 'turn': 'white'}))
        response = self.deliver_live(self.live_body(sequence = 4, state = {'phase': 'playing', 'turn': 'black'}))

        self.assertEqual(response.status_code, 200)
        self.game_link.refresh_from_db()
        self.assertEqual(self.game_link.live_snapshot['sequence'], 5)
        self.assertEqual(self.game_link.live_snapshot['state']['turn'], 'white')


@gamelink_settings
class ResultCallbackViewTest(ResultCallbackTestBase):

    # The happy path
    # --------------

    def test_a_signed_result_scores_the_fixture_and_confirms_it(self):
        response = self.deliver()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {'status': 'recorded'})

        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.score, (1, 0))
        self.assertTrue(self.fixture.auto_confirmed)
        self.assertTrue(self.fixture.is_confirmed)

        # The whole point of `auto_confirmed`: nobody voted, and the fixture is settled anyway.
        self.assertEqual(self.fixture.confirmations.count(), 0)
        self.assertEqual(self.fixture.required_confirmations_count, 2)

    def test_the_game_link_records_what_was_reported(self):
        body = self.result_body()
        self.deliver(body)

        self.game_link.refresh_from_db()
        self.assertEqual(self.game_link.status, 'completed')
        self.assertIsNotNone(self.game_link.completed_at)
        self.assertEqual(self.game_link.external_room_id, self.ROOM_ID)

        # The audit record behind a fixture that confirmed itself is the message verbatim.
        self.assertEqual(self.game_link.raw_result, body)

    def test_the_level_closes_and_the_tournament_advances(self):
        Fixture.objects.create(
            mode = self.knockout,
            level = 1,
            player1 = self.participants['player-1'],
            player2 = self.participants['player-2'],
            extras = dict())
        self.assertEqual(self.knockout.current_level, 0)

        self.deliver()

        self.assertEqual(Knockout.objects.get(pk = self.knockout.pk).current_level, 1)

    def test_confirmations_recorded_before_the_result_are_cleared(self):
        self.fixture.confirmations.add(self.user1)

        self.deliver()

        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.confirmations.count(), 0)

    def test_a_score_of_zero_is_a_score(self):
        # `if score:` would drop this one, and 0 is the losing half of every 1-0 result.
        self.deliver(self.result_body(score = {'p1': 0, 'p2': 1}, winner_seat = 'p2'))

        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.score, (0, 1))

    def test_the_seats_map_onto_this_side_s_players(self):
        # p1 is `fixture.player1` because that is the seat the ticket gave them, and the sender has
        # already mapped colours onto seats. Getting this backwards would award every game to the
        # wrong player while every signature still verified.
        self.deliver(self.result_body(score = {'p1': 1, 'p2': 0}))

        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.winner, self.participants['player-1'])

    # Idempotency
    # -----------

    def test_a_second_delivery_of_the_same_result_changes_nothing(self):
        body = self.result_body()
        self.assertEqual(self.deliver(body).status_code, 200)

        self.game_link.refresh_from_db()
        completed_at = self.game_link.completed_at

        # A retry mints a fresh nonce — the receiver rejects a replayed one outright — so this is
        # what a re-delivery actually looks like on the wire.
        response = self.deliver(body)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {'status': 'already_recorded'})

        self.fixture.refresh_from_db()
        self.game_link.refresh_from_db()
        self.assertEqual(self.fixture.score, (1, 0))
        self.assertEqual(self.game_link.completed_at, completed_at)

    def test_a_different_result_for_a_completed_fixture_is_ignored_rather_than_applied(self):
        self.deliver()
        self.deliver(self.result_body(score = {'p1': 0, 'p2': 1}, winner_seat = 'p2'))

        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.score, (1, 0))

    # Authentication
    # --------------

    def test_a_bad_signature_is_refused(self):
        response = self.deliver(signature = 'v1=' + '0' * 64)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(json.loads(response.content), {'error': 'unauthorized'})
        self.assertNothingRecorded()

    def test_a_signature_from_the_wrong_secret_is_refused(self):
        raw = self.serialize(self.result_body())
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        with override_settings(GAMELINK_RESULT_SECRETS = [OTHER_SECRET]):
            forged = sign_result_body(raw, timestamp, nonce)

        response = self.deliver(raw = raw, timestamp = timestamp, nonce = nonce, signature = forged)

        self.assertEqual(response.status_code, 401)
        self.assertNothingRecorded()

    def test_a_body_mutated_after_signing_is_refused(self):
        honest = self.serialize(self.result_body())
        tampered = self.serialize(self.result_body(score = {'p1': 7, 'p2': 0}))
        self.assertNotEqual(honest, tampered)

        response = self.deliver(raw = tampered, sign_over = honest)

        self.assertEqual(response.status_code, 401)
        self.assertNothingRecorded()

    def test_a_replayed_nonce_is_refused(self):
        nonce = uuid.uuid4().hex
        self.assertEqual(self.deliver(nonce = nonce).status_code, 200)

        # Same nonce, freshly signed, and a body that would otherwise be perfectly acceptable.
        response = self.deliver(nonce = nonce)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(SeenNonce.objects.filter(nonce = nonce).count(), 1)

    def test_a_stale_or_futuristic_timestamp_is_refused(self):
        now = int(time.time())
        for offset in (-301, -3600, 301, 3600):
            with self.subTest(offset = offset):
                response = self.deliver(timestamp = str(now + offset))
                self.assertEqual(response.status_code, 401)
        self.assertNothingRecorded()
        self.assertEqual(SeenNonce.objects.count(), 0)

    def test_a_timestamp_inside_the_window_is_accepted(self):
        response = self.deliver(timestamp = str(int(time.time()) - 299))
        self.assertEqual(response.status_code, 200)

    def test_a_missing_header_is_refused(self):
        for name in ('HTTP_X_GAMELINK_TIMESTAMP', 'HTTP_X_GAMELINK_NONCE', 'HTTP_X_GAMELINK_SIGNATURE'):
            with self.subTest(header = name):
                response = self.deliver(drop = [name])
                self.assertEqual(response.status_code, 401)
        self.assertNothingRecorded()

    def test_a_malformed_timestamp_or_nonce_is_refused(self):
        for kwargs in (
            dict(timestamp = 'now'),
            dict(timestamp = '-1756300940'),
            dict(timestamp = ' 1756300940'),
            dict(timestamp = '9' * 21),
            dict(nonce = 'a nonce with spaces'),
            dict(nonce = 'x' * 65),          # longer than SeenNonce.nonce can hold
            dict(nonce = ''),
        ):
            with self.subTest(**kwargs):
                self.assertEqual(self.deliver(**kwargs).status_code, 401)
        self.assertEqual(SeenNonce.objects.count(), 0)

    def test_the_issuer_header_is_not_a_gate(self):
        # It rides outside the signed material, so anyone can write anything in it. Refusing on it
        # would only give a false sense of a check; the secret is what separates environments, and
        # this test exists so that nobody adds one later believing it buys something.
        response = self.deliver(issuer = 'not-backgammon')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {'status': 'recorded'})

    def test_the_issuer_header_may_be_absent_altogether(self):
        response = self.deliver(drop = ['HTTP_X_GAMELINK_ISSUER'])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {'status': 'recorded'})

    def test_a_rotated_secret_still_verifies(self):
        raw = self.serialize(self.result_body())
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        with override_settings(GAMELINK_RESULT_SECRETS = [ROTATED_SECRET]):
            signature = sign_result_body(raw, timestamp, nonce)

        # Step one of the rotation in plan §5: the new secret is in the verifier list but is not
        # the one this server signs with. A result signed with it has to be accepted anyway.
        with override_settings(GAMELINK_RESULT_SECRETS = [RESULT_SECRET, ROTATED_SECRET]):
            response = self.deliver(raw = raw, timestamp = timestamp, nonce = nonce, signature = signature)

        self.assertEqual(response.status_code, 200)

    def test_the_signature_is_checked_before_any_database_query(self):
        # Plan §2, threat 16: a flood of forged results must not become a flood of queries.
        with self.assertNumQueries(0):
            self.deliver(signature = 'v1=' + 'f' * 64)

    # No session authority
    # --------------------

    def test_a_session_cookie_changes_nothing(self):
        self.assertTrue(self.client.login(username = self.user1.username, password = 'password'))

        self.assertEqual(self.deliver().status_code, 200)

    def test_a_session_cookie_does_not_stand_in_for_a_signature(self):
        self.assertTrue(self.client.login(username = self.user1.username, password = 'password'))

        response = self.deliver(signature = 'v1=' + '0' * 64)

        self.assertEqual(response.status_code, 401)
        self.assertNothingRecorded()

    def test_a_post_without_a_csrf_token_is_accepted(self):
        # `self.client` never enforces CSRF (gotcha **G12**), so the exemption is only actually
        # exercised by a client that does. Without this, `@csrf_exempt` could be removed and every
        # other test here would still pass.
        client = Client(enforce_csrf_checks = True)

        self.assertEqual(self.deliver(client = client).status_code, 200)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(RESULT_URL).status_code, 405)

    def test_a_disabled_feature_does_not_admit_the_endpoint_exists(self):
        with override_settings(GAMELINK_ENABLED = False):
            with self.assertNumQueries(0):
                response = self.deliver()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(json.loads(response.content), {'error': 'not_found'})
        self.assertNothingRecorded()

    # Malformed messages
    # ------------------

    def test_an_oversized_body_is_refused(self):
        body = self.result_body(end_reason = 'x' * (64 * 1024))
        raw = self.serialize(body)
        self.assertGreater(len(raw), 64 * 1024)

        response = self.deliver(raw = raw)

        self.assertEqual(response.status_code, 413)
        self.assertEqual(json.loads(response.content), {'error': 'payload_too_large'})
        # Refused on the declared length, so nothing downstream ran at all.
        self.assertEqual(SeenNonce.objects.count(), 0)
        self.assertNothingRecorded()

    def test_a_body_that_is_not_json_is_refused(self):
        response = self.deliver(raw = b'{"v": 1, ')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content), {'error': 'bad_request'})
        self.assertNothingRecorded()

    def test_a_body_that_is_not_an_object_is_refused(self):
        for raw in (b'[]', b'"result"', b'null', b'7'):
            with self.subTest(raw = raw):
                self.assertEqual(self.deliver(raw = raw).status_code, 400)

    def test_an_unsupported_version_is_refused(self):
        for version in (2, '1', None, True):
            with self.subTest(version = version):
                self.assertEqual(self.deliver(self.result_body(v = version)).status_code, 400)
        self.assertNothingRecorded()

    def test_a_field_of_the_wrong_type_is_refused(self):
        for overrides in (
            dict(tournament_id = '17'),
            dict(fixture_id = None),
            dict(fixture_id = 4.0),
            dict(room_id = ''),
            dict(room_id = 12345),
            dict(room_id = 'r' * 65),
            dict(status = 'finished'),
            dict(status = None),
            dict(score = None),
            dict(score = [1, 0]),
            dict(score = {'p1': 1}),
            dict(score = {'p1': '1', 'p2': 0}),
            dict(score = {'p1': -1, 'p2': 0}),
            dict(score = {'p1': 32768, 'p2': 0}),
        ):
            with self.subTest(**overrides):
                self.assertEqual(self.deliver(self.result_body(**overrides)).status_code, 400)
        self.assertNothingRecorded()

    def test_a_boolean_is_not_an_integer(self):
        # `isinstance(True, int)` is `True` in Python, so this needs its own guard and therefore
        # its own test.
        for overrides in (dict(fixture_id = True), dict(score = {'p1': True, 'p2': 0})):
            with self.subTest(**overrides):
                self.assertEqual(self.deliver(self.result_body(**overrides)).status_code, 400)

    def test_a_message_carrying_unknown_fields_is_still_accepted(self):
        # The sender may grow the message; a receiver that refused every field it did not know
        # would turn an additive change on the other side into an outage on this one.
        response = self.deliver(self.result_body(doubling_cube = 4))

        self.assertEqual(response.status_code, 200)
        self.game_link.refresh_from_db()
        self.assertEqual(self.game_link.raw_result['doubling_cube'], 4)

    # Conflicts with the tournament's own state
    # -----------------------------------------

    def test_a_result_for_an_unknown_fixture_is_not_found(self):
        response = self.deliver(self.result_body(fixture_id = self.fixture.pk + 1000))

        self.assertEqual(response.status_code, 404)
        self.assertNothingRecorded()

    def test_a_result_for_a_fixture_with_no_game_link_is_not_found(self):
        orphan = Fixture.objects.create(
            mode = self.knockout,
            level = 0,
            player1 = self.participants['player-2'],
            player2 = self.participants['player-1'],
            extras = dict())

        response = self.deliver(self.result_body(fixture_id = orphan.pk))

        self.assertEqual(response.status_code, 404)

    def test_a_result_naming_the_wrong_tournament_is_a_conflict(self):
        response = self.deliver(self.result_body(tournament_id = self.tournament.pk + 1))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(response.content), {'error': 'conflict'})
        self.assertNothingRecorded()

    def test_the_room_is_pinned_on_first_contact(self):
        # Nothing on this side knows the room id until the game server names it, so the first
        # message that arrives is what fixes it — and every later one is checked against it.
        self.assertEqual(self.game_link.external_room_id, '')

        self.deliver(self.result_body(status = 'cancelled', winner_seat = None))

        self.game_link.refresh_from_db()
        self.assertEqual(self.game_link.external_room_id, self.ROOM_ID)

    def test_a_result_from_a_different_room_is_a_conflict(self):
        self.game_link.external_room_id = 'a-different-room'
        self.game_link.save(update_fields = ['external_room_id'])

        response = self.deliver()

        self.assertEqual(response.status_code, 409)
        self.fixture.refresh_from_db()
        self.assertIsNone(self.fixture.score1)

    def test_a_knockout_draw_is_refused_and_the_fixture_stays_unscored(self):
        # `Knockout.check_fixture` cannot propagate a draw, so writing one would leave the bracket
        # with a level that can never close.
        response = self.deliver(self.result_body(score = {'p1': 1, 'p2': 1}, winner_seat = None))

        self.assertEqual(response.status_code, 409)
        self.assertNothingRecorded()

    # Cancellation
    # ------------

    def test_a_cancelled_result_releases_the_fixture_for_manual_scoring(self):
        body = self.result_body(status = 'cancelled', winner_seat = None, score = {'p1': 0, 'p2': 0},
                                end_reason = 'abandoned', match_id = None)

        response = self.deliver(body)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {'status': 'recorded'})

        self.game_link.refresh_from_db()
        self.assertEqual(self.game_link.status, 'cancelled')
        self.assertEqual(self.game_link.raw_result, body)
        self.assertIsNone(self.game_link.completed_at)

        # The fixture is exactly as it was, which is what "still manually scorable" means.
        self.fixture.refresh_from_db()
        self.assertIsNone(self.fixture.score1)
        self.assertFalse(self.fixture.auto_confirmed)
        self.assertFalse(self.fixture.is_confirmed)

    def test_a_cancelled_result_carries_no_score_requirement(self):
        # A cancellation has nothing to score, so the sender is not obliged to invent one.
        body = self.result_body(status = 'cancelled', winner_seat = None)
        body.pop('score')

        self.assertEqual(self.deliver(body).status_code, 200)

    def test_a_cancelled_fixture_can_still_be_scored_by_hand(self):
        self.deliver(self.result_body(status = 'cancelled', winner_seat = None))

        self.fixture.refresh_from_db()
        self.fixture.score = (1, 0)
        self.fixture.full_clean()
        self.fixture.save()
        self.fixture.confirmations.add(self.user1, self.user2)

        self.assertTrue(Fixture.objects.get(pk = self.fixture.pk).is_confirmed)

    def test_a_repeated_cancellation_is_already_recorded(self):
        body = self.result_body(status = 'cancelled', winner_seat = None)
        self.assertEqual(self.deliver(body).status_code, 200)

        response = self.deliver(body)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {'status': 'already_recorded'})

    def test_a_completion_after_a_cancellation_is_a_conflict(self):
        self.deliver(self.result_body(status = 'cancelled', winner_seat = None))

        response = self.deliver()

        self.assertEqual(response.status_code, 409)
        self.fixture.refresh_from_db()
        self.assertIsNone(self.fixture.score1)

    def test_a_cancellation_after_a_completion_leaves_the_result_standing(self):
        self.deliver()

        response = self.deliver(self.result_body(status = 'cancelled', winner_seat = None))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {'status': 'already_recorded'})
        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.score, (1, 0))
        self.assertTrue(self.fixture.is_confirmed)

    def test_a_failed_link_takes_no_result(self):
        self.game_link.status = 'failed'
        self.game_link.save(update_fields = ['status'])

        response = self.deliver()

        self.assertEqual(response.status_code, 409)
        self.fixture.refresh_from_db()
        self.assertIsNone(self.fixture.score1)

    # Logging
    # -------

    def test_a_refusal_is_logged_with_its_reason_and_a_redacted_signature(self):
        signature = 'v1=' + 'a' * 64

        with self.assertRejectionLogs() as logs:
            self.deliver(signature = signature)

        record = '\n'.join(logs.output)
        self.assertIn('401', record)
        self.assertIn('signature does not verify', record)
        self.assertIn('v1=[redacted]', record)
        self.assertNotIn('a' * 64, record)

    def test_a_refusal_names_the_fixture_it_was_about(self):
        with self.assertRejectionLogs() as logs:
            self.deliver(self.result_body(tournament_id = self.tournament.pk + 1))

        self.assertIn(f'fixture={self.fixture.pk}', '\n'.join(logs.output))


@gamelink_settings
class ResultContractTest(ResultCallbackTestBase):
    """
    The result half of the cross-repo contract (plan §7, tracker **P13**).

    The two repos share no code, no virtualenv and no parent git repository, so a contract test
    here can only take one shape: a **golden vector pinned identically on both sides**. Every
    constant below was produced by the backgammon signer and is pinned character for character in
    ``game/link/tests.py::ResultSignatureContractTests``. If either side drifts, one of the two
    suites turns red — which is the entire point, because drift otherwise leaves both suites green
    and the link broken in production.
    """

    # Produced by `game.link.signing.sign_result_body` under RESULT_SECRET.
    VECTOR_BODY = (
        b'{"end_reason":"bear_off","finished_at":"2026-08-27T12:02:20Z","fixture_id":482,'
        b'"match_id":"3a1f0c2b-4d5e-4a6b-8c7d-9e0f1a2b3c4d",'
        b'"room_id":"7c9e6679-7425-40de-944b-e07fc1f90ae7","score":{"p1":1,"p2":0},'
        b'"seats":{"p1":"white","p2":"black"},"status":"completed","target_points":1,'
        b'"tournament_id":17,"v":1,"winner_seat":"p1"}'
    )
    VECTOR_TIMESTAMP = '1756300940'
    VECTOR_NONCE     = 'b31c4f0e9a7d4c1eb2f38a6d5c091e77'
    VECTOR_BASE      = ('v1:1756300940:b31c4f0e9a7d4c1eb2f38a6d5c091e77:'
                        'f0a9545b5208bd6e742413ff1c5848364b05180801624918c67242f708573b7f')
    VECTOR_SIGNATURE = 'v1=0350ccb82111f47d231e2c1e4f04ac852f5b2d803d4333343d8d0c2c3bbf2dca'

    def verify(self, body = None, timestamp = None, nonce = None, signature = None):
        return verify_result_signature(
            self.VECTOR_BODY if body is None else body,
            self.VECTOR_TIMESTAMP if timestamp is None else timestamp,
            self.VECTOR_NONCE if nonce is None else nonce,
            self.VECTOR_SIGNATURE if signature is None else signature)

    def test_the_base_string_matches_the_one_the_sender_built(self):
        base = result_signature_base(self.VECTOR_BODY, self.VECTOR_TIMESTAMP, self.VECTOR_NONCE)
        self.assertEqual(base.decode(), self.VECTOR_BASE)

    def test_a_signature_produced_by_the_backgammon_signer_verifies_here(self):
        self.assertTrue(self.verify())

    def test_this_server_would_have_produced_the_same_signature(self):
        signature = sign_result_body(self.VECTOR_BODY, self.VECTOR_TIMESTAMP, self.VECTOR_NONCE)
        self.assertEqual(signature, self.VECTOR_SIGNATURE)

    def test_the_pinned_signature_is_refused_under_any_change(self):
        self.assertFalse(self.verify(body = self.VECTOR_BODY.replace(b'"p1":1', b'"p1":7')))
        self.assertFalse(self.verify(nonce = 'c42d4f0e9a7d4c1eb2f38a6d5c091e77'))
        self.assertFalse(self.verify(timestamp = '1756300941'))
        with override_settings(GAMELINK_RESULT_SECRETS = [OTHER_SECRET]):
            self.assertFalse(self.verify())

    def test_the_pinned_body_is_exactly_what_this_receiver_reserialises(self):
        # If these ever differ, the sender and this test disagree about JSON, and a body signed
        # over there would fail here for a reason that has nothing to do with the secret.
        reserialised = self.serialize(json.loads(self.VECTOR_BODY.decode()))
        self.assertEqual(reserialised, self.VECTOR_BODY)

    def test_the_senders_own_bytes_are_understood_and_not_merely_authenticated(self):
        """
        Post the frozen body verbatim and check that the *fixture* ends up right.

        The golden vector above pins the crypto. It cannot catch this receiver reading `score.p1`
        as the wrong player, which would award every game to the loser while every signature still
        verified — so the vector's own body, byte for byte, is run through the real endpoint here.
        The timestamp and nonce are fresh because the receiver rejects a stale one, which is
        exactly what a retry does.
        """
        tournament = Tournament.objects.create(id = 17, name = 'Vector', podium_spec = list(), published = True)
        knockout = Knockout.objects.create(tournament = tournament)
        alice, bob = [
            User.objects.create_user(username = name, password = 'password')
            for name in ('alice', 'bob')
        ]
        participants = [Participant.create_for_user(user) for user in (alice, bob)]
        for slot_id, participant in enumerate(participants):
            Participation.objects.create(tournament = tournament, participant = participant, slot_id = slot_id)

        fixture = Fixture.objects.create(
            id = 482, mode = knockout, level = 0,
            player1 = participants[0], player2 = participants[1], extras = dict())
        GameLink.objects.create(
            fixture = fixture, target_points = 1, expires_at = timezone.now() + datetime.timedelta(hours = 2))

        response = self.deliver(raw = self.VECTOR_BODY)

        self.assertEqual(response.status_code, 200)
        fixture.refresh_from_db()
        self.assertEqual(fixture.score, (1, 0))
        self.assertEqual(fixture.winner, participants[0])
        self.assertTrue(fixture.is_confirmed)
        self.assertEqual(GameLink.objects.get(fixture = fixture).external_room_id,
                         '7c9e6679-7425-40de-944b-e07fc1f90ae7')


@gamelink_settings
class TicketContractTest(TestCase):
    """
    The ticket half of the cross-repo contract (plan §7, tracker **P13**).

    Same shape as the result half, in the other direction: this token was minted here and is
    pinned character for character in ``game/link/tests.py::TicketContractTests``, where the
    backgammon verifier has to accept it. Session 3 checked this by hand against the real signer
    and the real endpoint; that script is gone, and this is what replaces it.

    Note it is decoded with ``max_age = None``. A pinned token is expired by construction — that is
    what makes it reproducible — and the age is not the part of the format that can drift.
    """

    VECTOR_TOKEN = (
        'eyJ2IjoxLCJpc3MiOiJ0b3VybmFtZW50cyIsImF1ZCI6ImJhY2tnYW1tb24iLCJqdGkiOiI1ZjNjMWQyZS04YTRi'
        'LTRjNmQtOWUwZi0xYTJiM2M0ZDVlNmYiLCJpYXQiOjE3NTYzMDAwMDAsImV4cCI6MTc1NjMwMDEyMCwic3ViIjoi'
        'MGYyYTdiNmMtM2Q0ZS00ZjVhLThiOWMtMGQxZTJmM2E0YjVjIiwibmFtZSI6ImFsaWNlIiwidHJuIjoxNywiZml4'
        'Ijo0ODIsInNlYXQiOiJwMSIsIm9wcCI6ImJvYiIsInRwIjoxLCJkYmwiOnRydWUsInRjIjoibm9ybWFsIn0:1x1hs5:'
        'dMOvm_vHiAACg1_LE07AU5JhYfpoyCSYWVF6U_kpaMc'
    )
    VECTOR_PAYLOAD = {
        'v'   : 1,
        'iss' : 'tournaments',
        'aud' : 'backgammon',
        'jti' : '5f3c1d2e-8a4b-4c6d-9e0f-1a2b3c4d5e6f',
        'iat' : 1756300000,
        'exp' : 1756300120,
        'sub' : '0f2a7b6c-3d4e-4f5a-8b9c-0d1e2f3a4b5c',
        'name': 'alice',
        'trn' : 17,
        'fix' : 482,
        'seat': 'p1',
        'opp' : 'bob',
        'tp'  : 1,
        'dbl' : True,
        'tc'  : 'normal',
    }

    def load(self, token = None, key = TICKET_SECRET):
        return signing.loads(
            self.VECTOR_TOKEN if token is None else token,
            key = key, salt = TICKET_SALT, max_age = None)

    def test_the_pinned_ticket_decodes_to_the_documented_payload(self):
        # Pins the salt, the key derivation, the serializer, the encoding and every claim name in
        # plan §3.1 at once — everything the backgammon verifier has to agree with.
        self.assertEqual(self.load(), self.VECTOR_PAYLOAD)

    def test_the_pinned_ticket_is_refused_under_the_wrong_secret(self):
        with self.assertRaises(signing.BadSignature):
            self.load(key = OTHER_SECRET)

    def test_the_pinned_ticket_is_refused_under_the_wrong_salt(self):
        with self.assertRaises(signing.BadSignature):
            signing.loads(self.VECTOR_TOKEN, key = TICKET_SECRET, salt = 'gamelink.ticket.v2', max_age = None)

    def test_a_tampered_claim_breaks_the_signature(self):
        _, timestamp, signature = self.VECTOR_TOKEN.split(':')
        forged = signing.b64_encode(
            json.dumps(dict(self.VECTOR_PAYLOAD, fix = 999), separators = (',', ':')).encode()).decode()

        with self.assertRaises(signing.BadSignature):
            self.load(f'{forged}:{timestamp}:{signature}')

    def test_the_issuer_still_mints_this_shape(self):
        # The pinned token is a snapshot; this is the check that `issue_ticket` has not since moved
        # away from it. Claim *names* and types are the contract — `jti`, `iat` and `exp` are
        # minted fresh and are not comparable.
        tournament = Tournament.objects.create(name = 'Test', podium_spec = list())
        knockout = Knockout.objects.create(tournament = tournament)
        user = User.objects.create_user(username = 'alice', password = 'password')
        fixture = Fixture.objects.create(
            mode = knockout,
            level = 0,
            player1 = Participant.create_for_user(user),
            player2 = Participant.create_for_user(User.objects.create_user(username = 'bob', password = 'x')))
        game_link = GameLink.objects.create(
            fixture = fixture, target_points = 1, expires_at = timezone.now() + datetime.timedelta(hours = 2))

        token, _ = issue_ticket(user, fixture, 'p1', game_link)
        minted = signing.loads(token, key = TICKET_SECRET, salt = TICKET_SALT, max_age = None)

        self.assertEqual(sorted(minted.keys()), sorted(self.VECTOR_PAYLOAD.keys()))
        for claim in ('v', 'iss', 'aud', 'seat', 'tp', 'tc'):
            self.assertEqual(minted[claim], self.VECTOR_PAYLOAD[claim], claim)
        for claim, value in minted.items():
            self.assertIsInstance(value, type(self.VECTOR_PAYLOAD[claim]), claim)


@gamelink_settings
class LinkedRoundEndToEndTest(TestCase):
    """
    A real knockout round advanced entirely through the callback, with zero human confirmations.

    This is plan §7's end-to-end row. The bracket is built by the project's own
    `Tournament.load` + `update_state`, so the propagation wiring is the real thing rather than
    hand-assembled `extras`.
    """

    DEFINITION = """
    stages:
    -
      id: main_round
      mode: knockout

    podium:
    - main_round.placements[0]
    """

    def setUp(self):
        self.tournament = Tournament.load(self.DEFINITION, 'Cup', published = True)
        self.users = [
            User.objects.create_user(username = f'player-{idx}', password = 'password')
            for idx in range(4)
        ]
        for slot_id, user in enumerate(self.users):
            Participation.objects.create(
                tournament = self.tournament,
                participant = Participant.create_for_user(user),
                slot_id = slot_id)
        self.tournament.update_state()
        self.stage = self.tournament.stages.all()[0]

        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def report(self, fixture):
        """Report `fixture` as a 1-0 win for its `player1`, the way the game server would."""
        game_link = GameLink.objects.create(
            fixture = fixture,
            target_points = 1,
            expires_at = timezone.now() + datetime.timedelta(hours = 2))
        body = {
            'v'            : 1,
            'tournament_id': self.tournament.pk,
            'fixture_id'   : fixture.pk,
            'room_id'      : f'room-for-fixture-{fixture.pk}',
            'match_id'     : str(uuid.uuid4()),
            'status'       : 'completed',
            'target_points': 1,
            'seats'        : {'p1': 'white', 'p2': 'black'},
            'score'        : {'p1': 1, 'p2': 0},
            'winner_seat'  : 'p1',
            'end_reason'   : 'bear_off',
            'finished_at'  : '2026-08-27T12:02:20Z',
        }
        raw = json.dumps(body, separators = (',', ':'), sort_keys = True).encode()
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        response = self.client.post(
            RESULT_URL,
            data = raw,
            content_type = 'application/json',
            HTTP_X_GAMELINK_TIMESTAMP = timestamp,
            HTTP_X_GAMELINK_NONCE     = nonce,
            HTTP_X_GAMELINK_SIGNATURE = sign_result_body(raw, timestamp, nonce),
            HTTP_X_GAMELINK_ISSUER    = 'backgammon')
        self.assertEqual(response.status_code, 200, response.content)
        return game_link

    def test_a_full_round_advances_without_a_single_human_confirmation(self):
        semifinals = list(self.stage.fixtures.filter(level = 0).order_by('pk'))
        final = self.stage.fixtures.get(level = 1)

        self.assertEqual(len(semifinals), 2)
        self.assertEqual(self.stage.current_level, 0)
        self.assertIsNone(final.player1)
        self.assertIsNone(final.player2)

        winners = [fixture.player1 for fixture in semifinals]
        for fixture in semifinals:
            self.report(fixture)

        # The level closed, and it closed because the game server said so.
        self.assertEqual(Knockout.objects.get(pk = self.stage.pk).current_level, 1)

        final.refresh_from_db()
        self.assertEqual({final.player1, final.player2}, set(winners))

        for fixture in semifinals:
            fixture.refresh_from_db()
            self.assertEqual(fixture.score, (1, 0))
            self.assertTrue(fixture.auto_confirmed)
            self.assertEqual(fixture.confirmations.count(), 0)

        self.assertEqual(self.tournament.state, 'active')

    def test_the_tournament_finishes_when_the_last_fixture_is_reported(self):
        for fixture in self.stage.fixtures.filter(level = 0):
            self.report(fixture)
        self.report(self.stage.fixtures.get(level = 1))

        self.assertEqual(self.tournament.state, 'finished')


# Housekeeping and the manual path (session 7)
# --------------------------------------------


@gamelink_settings
class PurgeExpiredTest(GameLinkTestBase):
    """
    `gamelink.housekeeping.purge_expired` and the management command wrapping it.

    The base class supplies one `GameLink` expiring in ten minutes, which is the "leave this alone"
    case for every test here.
    """

    def setUp(self):
        super().setUp()
        self.now = timezone.now()

    def add_nonce(self, nonce, age):
        seen = SeenNonce.objects.create(nonce = nonce)
        # `seen_at` is auto_now_add, so it has to be written back rather than passed in.
        SeenNonce.objects.filter(pk = seen.pk).update(seen_at = self.now - age)
        return seen

    def add_ticket(self, jti, expires_in):
        return IssuedTicket.objects.create(
            jti        = jti,
            game_link  = self.game_link,
            user       = self.users[0],
            seat       = 'p1',
            expires_at = self.now + expires_in)

    def test_a_nonce_older_than_the_retention_is_forgotten(self):
        self.add_nonce('old', datetime.timedelta(hours = 2))
        self.add_nonce('recent', datetime.timedelta(minutes = 5))

        counts = purge_expired(now = self.now)

        self.assertEqual(counts['nonces'], 1)
        self.assertEqual(list(SeenNonce.objects.values_list('nonce', flat = True)), ['recent'])

    def test_a_nonce_is_kept_for_the_whole_retention(self):
        # Exactly on the boundary, and one second inside it. Neither may be forgotten: the window
        # is what stops the replay, so an off-by-one here is a security bug, not a tidiness one.
        self.add_nonce('boundary', datetime.timedelta(hours = 1))
        self.add_nonce('just-inside', datetime.timedelta(minutes = 59, seconds = 59))

        counts = purge_expired(now = self.now)

        self.assertEqual(counts['nonces'], 0)
        self.assertEqual(SeenNonce.objects.count(), 2)

    def test_a_retention_shorter_than_the_clock_skew_window_is_refused(self):
        self.add_nonce('old', datetime.timedelta(hours = 2))

        # `GAMELINK_CLOCK_SKEW` is 300 s, so a captured result stays replayable for 600 s.
        with self.assertRaises(ValueError) as refusal:
            purge_expired(nonce_retention = datetime.timedelta(seconds = 599), now = self.now)

        self.assertIn('replayed', str(refusal.exception))

        # And it refused *before* deleting anything, rather than partway through.
        self.assertEqual(SeenNonce.objects.count(), 1)

    def test_the_minimum_retention_follows_the_configured_skew(self):
        with override_settings(GAMELINK_CLOCK_SKEW = 900):
            self.assertEqual(minimum_nonce_retention(), datetime.timedelta(seconds = 1800))
            purge_expired(nonce_retention = datetime.timedelta(seconds = 1800), now = self.now)
            with self.assertRaises(ValueError):
                purge_expired(nonce_retention = datetime.timedelta(seconds = 1799), now = self.now)

    def test_an_expired_ticket_is_deleted_and_a_live_one_is_kept(self):
        self.add_ticket(uuid.uuid4(), -datetime.timedelta(minutes = 1))
        live = self.add_ticket(uuid.uuid4(), datetime.timedelta(minutes = 1))

        counts = purge_expired(now = self.now)

        self.assertEqual(counts['tickets'], 1)
        self.assertEqual(list(IssuedTicket.objects.values_list('jti', flat = True)), [live.jti])

    def test_deleting_a_ticket_does_not_take_its_game_link_with_it(self):
        # `IssuedTicket.game_link` cascades one way only; purging the audit row must not remove the
        # record of the game it was minted for.
        self.add_ticket(uuid.uuid4(), -datetime.timedelta(minutes = 1))

        purge_expired(now = self.now)

        self.assertTrue(GameLink.objects.filter(pk = self.game_link.pk).exists())

    def test_a_pending_link_past_its_expiry_is_cancelled(self):
        GameLink.objects.filter(pk = self.game_link.pk).update(
            expires_at = self.now - datetime.timedelta(minutes = 1))

        counts = purge_expired(now = self.now)

        self.assertEqual(counts['links'], 1)
        self.game_link.refresh_from_db()
        self.assertEqual(self.game_link.status, 'cancelled')

    def test_a_link_that_has_not_expired_is_left_alone(self):
        counts = purge_expired(now = self.now)

        self.assertEqual(counts['links'], 0)
        self.game_link.refresh_from_db()
        self.assertEqual(self.game_link.status, 'pending')

    def test_a_link_that_reached_an_outcome_is_never_reopened(self):
        # Re-closing a settled link would overwrite a real result with a housekeeping guess.
        for status in ('completed', 'cancelled', 'playing', 'failed'):
            with self.subTest(status = status):
                GameLink.objects.filter(pk = self.game_link.pk).update(
                    status = status, expires_at = self.now - datetime.timedelta(days = 1))

                counts = purge_expired(now = self.now)

                self.assertEqual(counts['links'], 0)
                self.game_link.refresh_from_db()
                self.assertEqual(self.game_link.status, status)

    def test_a_cancelled_fixture_is_still_manually_scorable_afterwards(self):
        # This is the whole point of closing a stuck link: the fixture goes back to the humans.
        GameLink.objects.filter(pk = self.game_link.pk).update(
            expires_at = self.now - datetime.timedelta(minutes = 1))

        purge_expired(now = self.now)

        self.fixture.refresh_from_db()
        self.assertIsNone(self.fixture.score1)
        self.assertFalse(self.fixture.auto_confirmed)
        self.assertFalse(self.fixture.is_confirmed)

    def test_a_second_run_finds_nothing_left_to_do(self):
        self.add_nonce('old', datetime.timedelta(hours = 2))
        self.add_ticket(uuid.uuid4(), -datetime.timedelta(minutes = 1))
        GameLink.objects.filter(pk = self.game_link.pk).update(
            expires_at = self.now - datetime.timedelta(minutes = 1))

        first = purge_expired(now = self.now)
        second = purge_expired(now = self.now)

        self.assertEqual(first, dict(nonces = 1, tickets = 1, links = 1))
        self.assertEqual(second, dict(nonces = 0, tickets = 0, links = 0))

    def test_the_command_runs_and_says_what_it_did(self):
        self.add_nonce('old', datetime.timedelta(hours = 2))

        out = StringIO()
        call_command('purge_expired', stdout = out)

        self.assertIn('Purged 1 seen nonces', out.getvalue())
        self.assertEqual(SeenNonce.objects.count(), 0)

    def test_the_command_refuses_an_unsafe_retention_without_a_traceback(self):
        self.add_nonce('old', datetime.timedelta(hours = 2))

        with self.assertRaises(CommandError):
            call_command('purge_expired', '--nonce-hours', '0.1')

        self.assertEqual(SeenNonce.objects.count(), 1)


@start_game_settings
class ManualScoreGuardTest(StartGameTestBase):
    """
    The manual scoring path must refuse to overwrite a result the game server reported.

    `TournamentProgressView.post` already refuses a confirmed fixture, and `auto_confirmed` makes
    `is_confirmed` true, so the guard covers this by construction. That is exactly why it needs an
    explicit test: nothing in the manual path mentions `auto_confirmed`, so a future refactor of
    `is_confirmed` could reopen the hole without a single test going red.
    """

    def setUp(self):
        super().setUp()
        # A second, deliberately unscored fixture at the same level. Without it the auto-confirmed
        # fixture closes the level and finishes the tournament, and the POST is then refused by the
        # *state* check long before the confirmation guard is reached — a test that passes for
        # entirely the wrong reason (gotcha **G26**). The pairing does not matter; only that it is
        # unconfirmed and at level 0.
        self.sibling = Fixture.objects.create(
            mode = self.knockout,
            level = 0,
            player1 = self.participants['player-3'],
            player2 = self.participants['player-2'],
            extras = dict())

    def post_score(self, fixture, score1, score2):
        return self.client.post(self.progress_url(), dict(
            fixture_id = fixture.pk,
            score1 = str(score1),
            score2 = str(score2)))

    def auto_confirm(self, score1 = 1, score2 = 0):
        """Put the fixture in the state `ResultCallbackView` leaves it in."""
        self.fixture.score = (score1, score2)
        self.fixture.auto_confirmed = True
        self.fixture.save()

    def test_the_manual_path_still_works_on_an_ordinary_fixture(self):
        # The control. Without it, a 412 from any unrelated guard would look like proof that the
        # confirmation check is doing its job (the lesson of **G12**).
        self.login(self.user1)

        response = self.post_score(self.fixture, 1, 0)

        self.assertEqual(response.status_code, 302)
        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.score, (1, 0))

    def test_an_auto_confirmed_fixture_refuses_a_manual_score_edit(self):
        self.auto_confirm()
        self.login(self.user1)

        response = self.post_score(self.fixture, 0, 1)

        self.assertEqual(response.status_code, 412)
        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.score, (1, 0))
        self.assertTrue(self.fixture.auto_confirmed)

    def test_the_refusal_reaches_the_confirmation_guard_and_not_an_earlier_one(self):
        # Pins the arrangement the previous test depends on: the tournament is still running and
        # the fixture is still in the current level, so a 412 can only have come from
        # `is_confirmed`.
        self.auto_confirm()

        self.assertEqual(self.tournament.state, 'active')
        self.assertEqual(self.knockout.current_level, 0)
        self.assertEqual(self.fixture.level, 0)
        self.assertTrue(Fixture.objects.get(pk = self.fixture.pk).is_confirmed)

    def test_a_vote_confirmed_fixture_refuses_an_edit_too(self):
        # The behaviour that predates this work, pinned alongside so that the two cannot drift.
        self.fixture.score = (1, 0)
        self.fixture.save()
        self.fixture.confirmations.add(self.user1, self.user2)
        self.login(self.user1)

        response = self.post_score(self.fixture, 0, 1)

        self.assertEqual(response.status_code, 412)
        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.score, (1, 0))

    def test_an_auto_confirmed_fixture_refuses_every_player(self):
        self.auto_confirm()

        for user in (self.user1, self.user2):
            with self.subTest(user = user.username):
                self.login(user)
                self.assertEqual(self.post_score(self.fixture, 0, 1).status_code, 412)

    def test_resubmitting_the_reported_score_changes_nothing(self):
        # The score guard only runs when the score differs, so an identical resubmission falls
        # through to the confirmation branch. It must not alter the result either way — see
        # **P18**, which records that it does still add a human confirmation to a fixture that was
        # settled by machine.
        self.auto_confirm()
        self.login(self.user1)

        response = self.post_score(self.fixture, 1, 0)

        self.assertEqual(response.status_code, 302)
        self.fixture.refresh_from_db()
        self.assertEqual(self.fixture.score, (1, 0))
        self.assertTrue(self.fixture.auto_confirmed)
        self.assertTrue(self.fixture.is_confirmed)
