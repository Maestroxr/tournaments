"""
Scheduled cleanup for the game link (plan §8).

Three kinds of row accumulate here and each stops being useful at a different moment:

* a **seen nonce** is only needed for as long as a message carrying it could still be inside the
  timestamp window. After that it is dead weight — but deleting it *early* silently re-opens the
  replay it existed to stop, so the retention is checked against ``GAMELINK_CLOCK_SKEW`` rather
  than trusted;
* an **issued ticket** is an audit record of a credential that has since expired. The ticket itself
  was never stored, only its `jti` (plan §2, threat 13);
* a **game link** that is still `pending` past its own expiry describes a game nobody ever played.
  Closing it as `cancelled` is what hands the fixture back to manual scoring.

Nothing in here deletes anything a human might still want to read about a game that *happened*: a
`completed` or `cancelled` link is left exactly where it is, along with its `raw_result`.
"""

import datetime

from django.conf import settings
from django.utils import timezone

from .models import GameLink, IssuedTicket, SeenNonce

DEFAULT_NONCE_RETENTION = datetime.timedelta(hours = 1)


def minimum_nonce_retention():
    """
    Return the shortest nonce retention that does not weaken replay protection.

    A result is accepted while its timestamp is within ``GAMELINK_CLOCK_SKEW`` of now, in *either*
    direction, so a captured message stays replayable for up to twice that window. Forgetting its
    nonce any sooner would let the same message through a second time.
    """
    return datetime.timedelta(seconds = 2 * settings.GAMELINK_CLOCK_SKEW)


def purge_expired(nonce_retention = None, now = None):
    """
    Delete what has aged out, close what was never used, and return the counts as a dict.

    Raises :class:`ValueError` if `nonce_retention` is short enough to weaken replay protection —
    refusing to run is the right answer there, because a purge that quietly makes the system less
    safe is worse than one that does not happen.
    """
    now = now or timezone.now()
    nonce_retention = nonce_retention if nonce_retention is not None else DEFAULT_NONCE_RETENTION

    minimum = minimum_nonce_retention()
    if nonce_retention < minimum:
        raise ValueError(
            f'nonce retention of {nonce_retention} is shorter than the {minimum} required by '
            f'GAMELINK_CLOCK_SKEW={settings.GAMELINK_CLOCK_SKEW}s; purging that early would let a '
            f'captured result be replayed')

    nonces  = SeenNonce.objects.filter(seen_at__lt = now - nonce_retention).delete()[0]
    tickets = IssuedTicket.objects.filter(expires_at__lt = now).delete()[0]

    # Only `pending`. A link that reached `completed` or `cancelled` has said what it had to say,
    # and re-closing one would overwrite a real outcome with a housekeeping guess.
    links = GameLink.objects.filter(status = 'pending', expires_at__lt = now).update(status = 'cancelled')

    return dict(nonces = nonces, tickets = tickets, links = links)
