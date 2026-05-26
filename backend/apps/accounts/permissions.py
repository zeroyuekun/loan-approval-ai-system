from django.conf import settings
from rest_framework.permissions import BasePermission


def _staff_2fa_satisfied(user) -> bool:
    """When ENFORCE_2FA_FOR_STAFF is on, admin/officer/superuser users
    must have a confirmed TOTP device. When off (default), this check
    is a no-op — endpoints behave as they did before PR-4.

    Customers are never gated by 2FA. Per the security gap-closure spec,
    2FA is only for privileged accounts.
    """
    if not getattr(settings, "ENFORCE_2FA_FOR_STAFF", False):
        return True
    return user.has_confirmed_totp()


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        if not (request.user.is_authenticated and (request.user.role == "admin" or request.user.is_superuser)):
            return False
        return _staff_2fa_satisfied(request.user)


class IsLoanOfficer(BasePermission):
    def has_permission(self, request, view):
        if not (request.user.is_authenticated and request.user.role == "officer"):
            return False
        return _staff_2fa_satisfied(request.user)


class IsCustomer(BasePermission):
    def has_permission(self, request, view):
        # Customers don't require 2FA — they're not privileged accounts.
        return request.user.is_authenticated and request.user.role == "customer"


class IsAdminOrOfficer(BasePermission):
    def has_permission(self, request, view):
        if not (request.user.is_authenticated and request.user.role in ("admin", "officer")):
            return False
        return _staff_2fa_satisfied(request.user)
