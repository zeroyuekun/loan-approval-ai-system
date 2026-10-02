from rest_framework.permissions import BasePermission

from apps.accounts.policy import is_staff_role


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and (request.user.role == "admin" or request.user.is_superuser)


class IsLoanOfficer(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "officer"


class IsCustomer(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "customer"


class IsAdminOrOfficer(BasePermission):
    def has_permission(self, request, view):
        return is_staff_role(request.user)
