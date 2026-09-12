from django.db.models import Case, F, IntegerField, Value, When
from django.utils import timezone

from .models import Payment, TIER_CHOICES


# Product labels are working names. This catalog describes eligibility only; it
# does not claim that an engine, course, lesson, or VIP benefit is implemented.
TIER_PARENTS = {
    'FREE': None,
    'GOLD': 'FREE',
    'PREMIUM': 'GOLD',
    'VIP': 'PREMIUM',
}
TIER_FEATURES = {
    'FREE': {
        'online_play': True,
        'tournaments': True,
        'weekly_cup': True,
        'monthly_cup': True,
        'grand_championship': True,
        'rating': 'basic',
        'pr': 'none',
        'analysis': 'none',
        'courses': 'none',
        'live_lessons': False,
        'ai': 'limited',
        'vip_benefits': False,
    },
    'GOLD': {
        'rating': 'full',
        'pr': 'basic',
        'analysis': 'basic',
        'courses': 'partial',
        'ai': 'more',
    },
    'PREMIUM': {
        'pr': 'advanced',
        'analysis': 'full',
        'courses': 'full',
        'live_lessons': True,
        'ai': 'unlimited',
    },
    'VIP': {
        'pr': 'full',
        'vip_benefits': True,
    },
}
KNOWN_TIERS = frozenset(choice for choice, _ in TIER_CHOICES)
PAID_TIERS = frozenset(('GOLD', 'PREMIUM', 'VIP'))


def capabilities_for(tier):
    """Return the cumulative product catalog for a known tier."""
    if tier not in KNOWN_TIERS:
        tier = 'FREE'
    lineage = []
    while tier:
        lineage.append(tier)
        tier = TIER_PARENTS[tier]
    capabilities = {}
    for item in reversed(lineage):
        capabilities.update(TIER_FEATURES[item])
    # Stored permissions are a complete, explicit set for this tier. Disabling
    # sale of a plan does not remove rights from members who already paid.
    from .models import StoreProduct
    configured = StoreProduct.objects.filter(kind='subscription', tier=lineage[0]).first()
    if configured:
        capabilities.update(configured.capabilities)
    return capabilities


def paid_access(user):
    """Single server-side entitlement predicate, including expiry and refunds."""
    return Payment.objects.filter(
        subscription__user=user, paid_at__lte=timezone.now(), period_end__gt=timezone.now(),
        refunded_amount__lt=F('amount'), reversed=False,
    )


def has_membership(user):
    return user.is_authenticated and (paid_access(user).exists() or tranzila_access(user).exists())


def tranzila_access(user):
    from .models import CheckoutRequest
    return CheckoutRequest.objects.filter(user=user, product='subscription', environment='live',
        status='paid', paid_at__lte=timezone.now(), valid_until__gt=timezone.now())


def entitlement_for(user):
    """Highest active paid tier wins; lower tiers keep their original expiry.

    Within a tier choose the longest period, then latest payment and PK.
    Unknown legacy tiers retain membership but only FREE capabilities.
    """
    ranks = {'FREE': 0, 'GOLD': 1, 'PREMIUM': 2, 'VIP': 3}
    def rank(field):
        return Case(*(When(**{field: tier}, then=Value(value)) for tier, value in ranks.items()),
                    default=Value(0), output_field=IntegerField())
    access = paid_access(user).select_related('subscription').annotate(
        tier_rank=rank('subscription__tier')).order_by('-tier_rank', '-period_end', '-paid_at', '-pk').first()
    direct = tranzila_access(user).annotate(tier_rank=rank('tier')).order_by(
        '-tier_rank', '-valid_until', '-paid_at', '-pk').first()
    if direct and (not access or (direct.tier_rank, direct.valid_until, direct.paid_at) >
                  (access.tier_rank, access.period_end, access.paid_at)):
        return {'membership': True, 'tier': direct.tier, 'valid_until': direct.valid_until,
                'capabilities': capabilities_for(direct.tier)}
    tier = access.subscription.tier if access and access.subscription.tier in KNOWN_TIERS else 'FREE'
    return {
        'membership': bool(access),
        'tier': tier,
        'valid_until': access.period_end if access else None,
        'capabilities': capabilities_for(tier),
    }
