"""Authentication helper for operational endpoints (metrics, deep health).

Accepts either:
  1. Staff session (user.is_staff True) — for ad-hoc inspection via the admin
  2. X-Health-Token header matching settings.HEALTH_CHECK_TOKEN — for Prometheus
     scrapes and automated tooling

Denies all other requests with 403.
"""

import hmac
from functools import wraps

from django.conf import settings
from django.http import JsonResponse


def require_ops_auth(view_func):
    """Gate a view behind staff session OR X-Health-Token header."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if getattr(request.user, "is_staff", False):
            return view_func(request, *args, **kwargs)

        token = getattr(settings, "HEALTH_CHECK_TOKEN", "") or ""
        provided = request.headers.get("X-Health-Token", "") or ""
        if token and hmac.compare_digest(provided.encode(), token.encode()):
            return view_func(request, *args, **kwargs)

        return JsonResponse({"error": "unauthorized"}, status=403)

    return _wrapped
