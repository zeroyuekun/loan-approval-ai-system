"""Custom JWT authentication that reads tokens from HttpOnly cookies.

Falls back to the standard Authorization header for API clients / tests.
"""

from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication


class CookieJWTAuthentication(JWTAuthentication):
    """Authenticate using HttpOnly cookie first, then fall back to header."""

    def authenticate(self, request):
        # Try cookie-based auth first
        cookie_name = getattr(settings, 'JWT_ACCESS_COOKIE_NAME', 'access_token')
        raw_token = request.COOKIES.get(cookie_name)

        if raw_token is not None:
            validated_token = self.get_validated_token(raw_token)
            return self.get_user(validated_token), validated_token

        # Fall back to standard header-based auth (for API clients, tests, etc.)
        return super().authenticate(request)
