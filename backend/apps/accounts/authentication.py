"""Custom JWT authentication that reads tokens from HttpOnly cookies.

Falls back to the standard Authorization header for API clients / tests.
Enforces Django CSRF validation on the cookie path so that cookie-authenticated
mutating requests cannot be replayed cross-site. The header fallback (bearer
tokens) is exempt because the explicit Authorization header itself is proof of
intent and is not sent automatically by browsers.
"""

from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware
from rest_framework import exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.accounts.policy import enforce_staff_2fa


class _CSRFCheck(CsrfViewMiddleware):
    """Expose CSRF failure reasons rather than returning a 403 response."""

    def _reject(self, request, reason):
        return reason


class CookieJWTAuthentication(JWTAuthentication):
    """Authenticate using HttpOnly cookie first, then fall back to header.

    Also the single enforcement point for ENFORCE_2FA_FOR_STAFF: every DRF
    view authenticates through here, so an un-enrolled staff user is refused
    (403, code ``2fa_enrolment_required``) on every path, not only on views
    whose permission class remembers to check. Views enrolment needs opt out
    with ``allow_unenrolled_staff = True``.
    """

    def authenticate(self, request):
        cookie_name = getattr(settings, "JWT_ACCESS_COOKIE_NAME", "access_token")
        raw_token = request.COOKIES.get(cookie_name)

        if raw_token is not None:
            validated_token = self.get_validated_token(raw_token)
            user = self.get_user(validated_token)
            self._enforce_csrf(request)
            result = (user, validated_token)
        else:
            result = super().authenticate(request)

        if result is not None:
            view = (getattr(request, "parser_context", None) or {}).get("view")
            enforce_staff_2fa(result[0], view)
        return result

    def _enforce_csrf(self, request):
        check = _CSRFCheck(lambda r: None)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            raise exceptions.PermissionDenied(f"CSRF Failed: {reason}")
