"""Who counts as staff, and the staff 2FA rule — one place for both.

Staff access used to be decided in four places (DRF permission classes,
role-string compares in querysets, ``check_loan_access`` and
``TaskStatusView``), and ENFORCE_2FA_FOR_STAFF only reached the first. The
enrolment rule is now enforced once, at authentication (see
``CookieJWTAuthentication``), so it covers every DRF view that authenticates
a user, whatever its permission or queryset logic. Views a not-yet-enrolled
staff member must still reach (2FA setup/verify/status, ``/auth/me/``,
logout) set ``allow_unenrolled_staff = True``.
"""

from django.conf import settings
from rest_framework.exceptions import PermissionDenied

STAFF_ROLES = ("admin", "officer")


def is_staff_role(user) -> bool:
    """Admin or officer role, or a Django superuser (whose role may be the
    ``customer`` default that ``createsuperuser`` leaves)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return getattr(user, "role", None) in STAFF_ROLES or bool(getattr(user, "is_superuser", False))


def staff_2fa_satisfied(user) -> bool:
    """True unless enforcement is on and this staff user has no confirmed TOTP
    device. Customers are never gated: 2FA is for privileged accounts only."""
    if not getattr(settings, "ENFORCE_2FA_FOR_STAFF", False):
        return True
    if not is_staff_role(user):
        return True
    return user.has_confirmed_totp()


class StaffEnrolmentRequired(PermissionDenied):
    default_detail = (
        "Two-factor authentication must be set up before this staff account can use the API. "
        "Enrol via /api/v1/auth/2fa/setup/ and /api/v1/auth/2fa/verify/."
    )
    default_code = "2fa_enrolment_required"

    def __init__(self):
        super().__init__()
        # Expose the code in the body so the frontend can route to enrolment.
        self.detail = {"detail": self.default_detail, "code": self.default_code}


def enforce_staff_2fa(user, view) -> None:
    """Raise StaffEnrolmentRequired for an un-enrolled staff user, unless the
    view is one enrolment itself needs."""
    if getattr(view, "allow_unenrolled_staff", False):
        return
    if not staff_2fa_satisfied(user):
        raise StaffEnrolmentRequired()
