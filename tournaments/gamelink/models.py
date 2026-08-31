import uuid

from django.db import models


class LinkedAccount(models.Model):
    """
    Stable, opaque identity of a tournaments user, as seen by the game server.

    The game server maps ``external_id`` to one of its own users. Identity is *never* matched by
    username, so a local backgammon account and a linked account which happen to share a username
    stay distinct (plan §2, threat 9).
    """

    user        = models.OneToOneField('auth.User', on_delete = models.CASCADE, related_name = 'gamelink_account')
    external_id = models.UUIDField(default = uuid.uuid4, unique = True, editable = False)
    created_at  = models.DateTimeField(auto_now_add = True)

    def __str__(self):
        return f'{self.user} ({self.external_id})'

    @classmethod
    def external_id_for(cls, user):
        """
        Return the opaque external identity of `user`, creating it on first use.
        """
        return str(cls.objects.get_or_create(user = user)[0].external_id)


class GameLink(models.Model):
    """
    One externally played game per fixture.
    """

    STATUS = [
        ('pending'  , 'Pending'  ),
        ('playing'  , 'Playing'  ),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('failed'   , 'Failed'   ),
    ]

    fixture          = models.OneToOneField('tournaments.Fixture', on_delete = models.CASCADE, related_name = 'game_link')
    provider         = models.CharField(max_length = 32, default = 'backgammon')
    external_room_id = models.CharField(max_length = 64, blank = True)
    status           = models.CharField(max_length = 16, choices = STATUS, default = 'pending')
    target_points    = models.PositiveSmallIntegerField(default = 1)
    created_at       = models.DateTimeField(auto_now_add = True)
    expires_at       = models.DateTimeField()
    completed_at     = models.DateTimeField(null = True, blank = True)
    raw_result       = models.JSONField(null = True, blank = True)  # audit trail behind the auto-confirmation

    def __str__(self):
        return f'{self.provider} game for fixture {self.fixture_id} ({self.status})'


class IssuedTicket(models.Model):
    """
    Audit log of minted tickets. This is *not* the single-use gate — single use can only be
    enforced where redemption is observed, which is the verifier on the game server (plan §4).
    """

    jti        = models.UUIDField(unique = True)
    game_link  = models.ForeignKey(GameLink, on_delete = models.CASCADE, related_name = 'tickets')
    user       = models.ForeignKey('auth.User', on_delete = models.CASCADE)
    seat       = models.CharField(max_length = 2)
    issued_at  = models.DateTimeField(auto_now_add = True)
    expires_at = models.DateTimeField()

    def __str__(self):
        return f'ticket {self.jti} for fixture {self.game_link.fixture_id} seat {self.seat}'


class SeenNonce(models.Model):
    """
    Nonces of inbound result messages, for replay protection. Purged on a schedule (plan §8).
    """

    nonce   = models.CharField(max_length = 64, unique = True)
    seen_at = models.DateTimeField(auto_now_add = True)

    def __str__(self):
        return self.nonce
