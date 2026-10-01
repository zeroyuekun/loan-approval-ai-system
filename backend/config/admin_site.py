"""Django admin honours ENFORCE_2FA_FOR_STAFF.

The admin is a staff write path with its own session login, so the API-level
enrolment gate (apps.accounts.policy) never sees it. With enforcement on, the
admin uses django_otp's OTPAdminSite behaviour: the login form asks for a TOTP
code and only an OTP-verified session has permission. With enforcement off it
behaves like the stock AdminSite. The setting is read per request.
"""

from django.conf import settings
from django.contrib.admin import AdminSite
from django.contrib.admin.forms import AdminAuthenticationForm
from django_otp.admin import OTPAdminAuthenticationForm, OTPAdminSite


def _enforced() -> bool:
    return bool(getattr(settings, "ENFORCE_2FA_FOR_STAFF", False))


class StaffOTPAdminSite(OTPAdminSite):
    @property
    def login_form(self):
        return OTPAdminAuthenticationForm if _enforced() else AdminAuthenticationForm

    @property
    def login_template(self):
        return OTPAdminSite.login_template if _enforced() else None

    def has_permission(self, request):
        if _enforced():
            return super().has_permission(request)  # active staff AND is_verified()
        return AdminSite.has_permission(self, request)
