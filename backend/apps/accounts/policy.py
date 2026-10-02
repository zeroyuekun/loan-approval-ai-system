"""Who counts as staff — one place for the rule.

Staff access used to be decided in four places (DRF permission classes,
role-string compares in querysets, ``check_loan_access`` and
``TaskStatusView``); they all ask ``is_staff_role`` now.
"""

STAFF_ROLES = ("admin", "officer")


def is_staff_role(user) -> bool:
    """Admin or officer role, or a Django superuser (whose role may be the
    ``customer`` default that ``createsuperuser`` leaves)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return getattr(user, "role", None) in STAFF_ROLES or bool(getattr(user, "is_superuser", False))
