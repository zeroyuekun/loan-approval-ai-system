from rest_framework.permissions import BasePermission

from apps.accounts.policy import is_staff_role
from apps.accounts.policy import staff_2fa_satisfied as _staff_2fa_satisfied

# The 2FA rule itself is enforced at authentication for every DRF view
# (apps.accounts.policy); the permission classes keep the check so a view
# that opts out of that gate with allow_unenrolled_staff is still covered.


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
        if not is_staff_role(request.user):
            return False
        return _staff_2fa_satisfied(request.user)
