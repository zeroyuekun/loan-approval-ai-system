"""Shared helpers and throttles used across accounts views."""

from django.conf import settings as django_settings
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


def set_jwt_cookies(response, access_token, refresh_token):
    """Set JWT tokens as HttpOnly cookies on the response."""
    secure = getattr(django_settings, "JWT_COOKIE_SECURE", True)
    samesite = getattr(django_settings, "JWT_COOKIE_SAMESITE", "Lax")
    access_name = getattr(django_settings, "JWT_ACCESS_COOKIE_NAME", "access_token")
    refresh_name = getattr(django_settings, "JWT_REFRESH_COOKIE_NAME", "refresh_token")

    access_max_age = int(django_settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds())
    refresh_max_age = int(django_settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds())

    response.set_cookie(
        access_name,
        str(access_token),
        max_age=access_max_age,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
    )
    response.set_cookie(
        refresh_name,
        str(refresh_token),
        max_age=refresh_max_age,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
    )
    return response


def clear_jwt_cookies(response):
    """Remove JWT cookies from the response."""
    access_name = getattr(django_settings, "JWT_ACCESS_COOKIE_NAME", "access_token")
    refresh_name = getattr(django_settings, "JWT_REFRESH_COOKIE_NAME", "refresh_token")
    response.delete_cookie(access_name, path="/")
    response.delete_cookie(refresh_name, path="/")
    return response


class RefreshRateThrottle(AnonRateThrottle):
    rate = "30/min"


class LoginRateThrottle(AnonRateThrottle):
    rate = "5/min"


class RegisterRateThrottle(AnonRateThrottle):
    rate = "3/min"


class DataExportThrottle(UserRateThrottle):
    """Low cap on data exports — heavy endpoint + Privacy Act APP-12 is low-frequency."""

    scope = "data_export"
    rate = "10/hour"
