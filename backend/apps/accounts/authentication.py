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


class _CSRFCheck(CsrfViewMiddleware):
    """Expose CSRF failure reasons rather than returning a 403 response."""

    def _reject(self, request, reason):
        return reason


class CookieJWTAuthentication(JWTAuthentication):
    """Authenticate using HttpOnly cookie first, then fall back to header."""

    def authenticate(self, request):
        cookie_name = getattr(settings, "JWT_ACCESS_COOKIE_NAME", "access_token")
        raw_token = request.COOKIES.get(cookie_name)

        if raw_token is not None:
            validated_token = self.get_validated_token(raw_token)
            user = self.get_user(validated_token)
            self._enforce_csrf(request)
            return user, validated_token

        return super().authenticate(request)

    def _enforce_csrf(self, request):
        check = _CSRFCheck(lambda r: None)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            raise exceptions.PermissionDenied(f"CSRF Failed: {reason}")
