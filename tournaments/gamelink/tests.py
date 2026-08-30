import datetime
import hashlib
import json
import time
from urllib.parse import unquote

from django.contrib.auth.models import AnonymousUser, User
from django.core import signing
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from tournaments.models import Fixture, Knockout, Participant, Participation, Tournament

from gamelink import checks
from gamelink.models import GameLink, IssuedTicket, LinkedAccount
from gamelink.signing import (
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
        self.tournament = Tournament.objects.create(name = 'Test', podium_spec = list(), published = True)
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
        self.assertEqual(game_link.target_points, 1)
        self.assertGreater(game_link.expires_at, timezone.now())

        payload = verify_ticket(unquote(response['Location'][len(prefix):]))
        self.assertEqual(payload['seat'], 'p1')
        self.assertEqual(payload['fix'], self.fixture.pk)
        self.assertEqual(payload['trn'], self.tournament.pk)
        self.assertEqual(payload['tp'], 1)
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
