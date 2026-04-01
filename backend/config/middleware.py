"""Custom middleware for the loan approval system.

Includes:
* **CorrelationIdMiddleware** — assigns a unique request ID for tracing.
* **SecurityHeadersMiddleware** — hardens responses for OWASP ZAP compliance.

Usage:
    Add both to MIDDLEWARE after SecurityMiddleware and before application
    middleware.
"""

import logging
import threading
import uuid

_correlation_id = threading.local()


def get_correlation_id() -> str | None:
    """Return the current request's correlation ID (or ``None`` outside a request)."""
    return getattr(_correlation_id, "value", None)


class _CorrelationIdFilter(logging.Filter):
    """Logging filter that adds ``correlation_id`` to every LogRecord."""

    def filter(self, record):
        record.correlation_id = get_correlation_id() or "-"
        return True


# Install the filter on the root logger once at import time so every
# handler (console, JSON, file) automatically receives the field.
logging.getLogger().addFilter(_CorrelationIdFilter())


class CorrelationIdMiddleware:
    """Assign a correlation ID to each request and propagate it via logs.

    * Reads ``X-Request-ID`` from the incoming request (set by a load
      balancer or gateway) and reuses it, or generates a new UUID4.
    * Stores the ID in ``threading.local`` so ``get_correlation_id()``
      works anywhere in the call stack (views, services, model methods).
    * Sets ``X-Request-ID`` on the response for client-side tracing.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        cid = request.META.get("HTTP_X_REQUEST_ID") or uuid.uuid4().hex
        _correlation_id.value = cid
        request.correlation_id = cid

        response = self.get_response(request)

        response["X-Request-ID"] = cid
        _correlation_id.value = None
        return response


class SecurityHeadersMiddleware:
    """Add security headers and strip information-leaking headers.

    Addresses OWASP ZAP findings:
    * 10037 — strips ``X-Powered-By`` and ``Server`` headers
    * 10015 — adds ``Cache-Control`` to API responses
    * Adds ``Permissions-Policy`` to restrict browser features
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Strip information-leaking headers (ZAP rule 10037)
        for header in ("X-Powered-By", "Server"):
            if header in response:
                del response[header]

        # Cache-Control for API responses (ZAP rule 10015)
        if request.path.startswith("/api/") and "Cache-Control" not in response:
            response["Cache-Control"] = "no-store"

        # Permissions-Policy — restrict unused browser features
        if "Permissions-Policy" not in response:
            response["Permissions-Policy"] = (
                "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"
            )

        return response
