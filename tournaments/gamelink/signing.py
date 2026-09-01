"""
Cryptography for the game link.

Two independent channels, two independent secrets (plan §1):

* **Tickets** (tournaments → backgammon) travel in a URL and are signed with
  ``GAMELINK_TICKET_SECRET`` using :mod:`django.core.signing`, which gives HMAC-SHA256 with salted
  key derivation and built-in age enforcement without adding a dependency to either repo.
* **Results** (backgammon → tournaments) are authenticated by a *detached* HMAC over the raw
  request body, keyed with ``GAMELINK_RESULT_SECRET(S)``, so the receiver verifies exactly the
  bytes it is about to parse.

Verifiers accept a *list* of secrets and signers use the *first*, which is what makes zero-downtime
rotation possible (plan §5).

Nothing in here logs, and nothing in here ever returns a secret. Use :func:`redact` before putting
anything that may carry a ticket or a signature into a log record.
"""

import hashlib
import hmac
import re
import time
import uuid

from django.conf import settings
from django.core import signing
from django.core.exceptions import ImproperlyConfigured

TICKET_VERSION = 1
TICKET_SALT = 'gamelink.ticket.v1'

RESULT_SIGNATURE_VERSION = 'v1'

SEATS = ('p1', 'p2')

_SIGNATURE_HEADER_PATTERN = re.compile(r'\Av1=([0-9a-fA-F]{64})\Z')

_REDACTION_PATTERNS = (
    re.compile(r'(X-Gamelink-Signature\s*[:=]\s*)\S+', re.IGNORECASE),
    re.compile(r'(ticket=)[^&\s\'"]+', re.IGNORECASE),
    re.compile(r'(v1=)[0-9a-fA-F]+'),
)


# Tickets (tournaments -> backgammon)
# -----------------------------------


def issue_ticket(user, fixture, seat, game_link):
    """
    Mint a single-use ticket authorizing `user` to play `fixture` from `seat`.

    Returns the ``(token, jti)`` pair. The caller is responsible for recording the `jti` in
    :class:`~gamelink.models.IssuedTicket` and for having checked that `user` is actually entitled
    to that seat — this function performs no authorization of its own, and in particular the seat
    must never be derived from anything the requester supplied.
    """
    if seat not in SEATS:
        raise ValueError(f'unknown seat: "{seat}"')

    from .models import LinkedAccount

    own, opponent = (fixture.player1, fixture.player2) if seat == 'p1' else (fixture.player2, fixture.player1)

    issued_at = int(time.time())
    jti = uuid.uuid4()
    payload = {
        'v'   : TICKET_VERSION,
        'iss' : settings.GAMELINK_ISSUER,
        'aud' : settings.GAMELINK_AUDIENCE,
        'jti' : str(jti),
        'iat' : issued_at,
        'exp' : issued_at + settings.GAMELINK_TICKET_TTL,
        'sub' : LinkedAccount.external_id_for(user),
        'name': own.name if own else '',
        'trn' : fixture.mode.tournament_id,
        'fix' : fixture.pk,
        'seat': seat,
        'opp' : opponent.name if opponent else '',
        'tp'  : game_link.target_points,
        'dbl' : game_link.doubling_enabled,
    }
    token = signing.dumps(payload, key = _ticket_secret(), salt = TICKET_SALT, compress = False)
    return token, jti


def verify_ticket(token, max_age = None):
    """
    Verify `token` and return its payload.

    This is the reference implementation of the check the backgammon server performs (plan §3.1);
    it lives here so that both ends of the contract can be exercised from one test module. Raises
    :class:`django.core.signing.BadSignature` — of which
    :class:`~django.core.signing.SignatureExpired` is a subclass — if the token is not acceptable.

    Single use is *not* checked here. It cannot be: only the verifier that actually redeems a
    ticket observes redemption, and that is the backgammon server.
    """
    if max_age is None:
        max_age = settings.GAMELINK_TICKET_TTL

    payload = signing.loads(token, key = _ticket_secret(), salt = TICKET_SALT, max_age = max_age)

    if not isinstance(payload, dict):
        raise signing.BadSignature('ticket payload is not an object')

    if payload.get('v') != TICKET_VERSION:
        raise signing.BadSignature('unsupported ticket version')

    if payload.get('iss') != settings.GAMELINK_ISSUER:
        raise signing.BadSignature('issuer mismatch')

    if payload.get('aud') != settings.GAMELINK_AUDIENCE:
        raise signing.BadSignature('audience mismatch')

    if payload.get('seat') not in SEATS:
        raise signing.BadSignature('unknown seat')

    # `max_age` above already enforces the age of the signature. The `exp` claim is enforced
    # separately and deliberately redundantly, so that changing one does not silently remove the
    # other (plan §3.1).
    expires_at = payload.get('exp')
    if isinstance(expires_at, bool) or not isinstance(expires_at, int):
        raise signing.BadSignature('missing expiry')
    if expires_at <= int(time.time()):
        raise signing.SignatureExpired('ticket has expired')

    return payload


def _ticket_secret():
    secret = getattr(settings, 'GAMELINK_TICKET_SECRET', '')
    if not secret:
        raise ImproperlyConfigured('GAMELINK_TICKET_SECRET is not configured')
    return secret


# Results (backgammon -> tournaments)
# -----------------------------------


def result_signature_base(raw_body, timestamp, nonce):
    """
    Return the bytes that a result signature commits to.

    The body enters as its SHA-256 digest rather than verbatim, so the base string stays short and
    binary-safe while still binding the signature to the exact bytes that will be parsed.
    """
    digest = hashlib.sha256(_as_bytes(raw_body)).hexdigest()
    return f'{RESULT_SIGNATURE_VERSION}:{timestamp}:{nonce}:{digest}'.encode()


def sign_result_body(raw_body, timestamp, nonce):
    """
    Return the ``X-Gamelink-Signature`` header value for a result message.

    Signs with the *first* configured result secret. In production the signer is the backgammon
    server and tournaments only ever verifies; this exists so that the two implementations can be
    asserted byte-for-byte identical from a single test module (plan §7).
    """
    secrets = _result_secrets()
    if not secrets:
        raise ImproperlyConfigured('GAMELINK_RESULT_SECRETS is not configured')
    signature = hmac.new(secrets[0].encode(), result_signature_base(raw_body, timestamp, nonce), hashlib.sha256)
    return f'{RESULT_SIGNATURE_VERSION}={signature.hexdigest()}'


def verify_result_signature(raw_body, timestamp, nonce, header):
    """
    Return whether `header` is a valid signature of `raw_body` under any configured result secret.

    Never raises: a malformed, truncated, absent or otherwise hostile header is simply a `False`.
    This runs before any database query on the public callback endpoint (plan §2, threat 16), so it
    has to be both cheap and total.
    """
    try:
        if not isinstance(header, str):
            return False
        match = _SIGNATURE_HEADER_PATTERN.match(header.strip())
        if match is None:
            return False
        offered = match.group(1).lower()
        base = result_signature_base(raw_body, timestamp, nonce)
    except (AttributeError, TypeError, ValueError):
        return False

    verified = False
    for secret in _result_secrets():
        expected = hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
        # Deliberately no early exit: every configured secret is tried on every call, so the time
        # taken reveals neither which secret matched nor how many are configured.
        verified |= hmac.compare_digest(expected, offered)
    return verified


def _result_secrets():
    return [secret for secret in getattr(settings, 'GAMELINK_RESULT_SECRETS', list()) if secret]


def _as_bytes(value):
    return value if isinstance(value, bytes) else str(value).encode()


# Logging hygiene
# ---------------


def redact(text):
    """
    Blank out ticket tokens and signatures in `text` so that it is safe to log (plan §2,
    threat 13).
    """
    if text is None:
        return text
    text = str(text)
    for pattern in _REDACTION_PATTERNS:
        text = pattern.sub(r'\1[redacted]', text)
    return text
