"""Operators manage players; only superusers manage administrator credentials/roles."""
def may_manage_user(actor, target=None, *, grant_staff=False):
    if actor.is_superuser:
        return True
    return bool(actor.is_staff and not grant_staff
                and (target is None or not (target.is_staff or target.is_superuser)))
