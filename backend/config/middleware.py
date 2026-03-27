"""Request correlation ID middleware.

Injects a unique ``request_id`` into every log record produced during a
request lifecycle.  The ID is also forwarded to Celery tasks via a custom
header so that the entire Django → Celery → external-API chain can be
traced in log aggregation systems (ELK, Datadog, CloudWatch).

Usage:
    Add ``'config.middleware.CorrelationIdMiddleware'`` to MIDDLEWARE
    **after** SecurityMiddleware and **before** application middleware.
"""

import logging
import threading
import uuid

_correlation_id = threading.local()


def get_correlation_id() -> str | None:
    """Return the current request's correlation ID (or ``None`` outside a request)."""
    return getattr(_correlation_id, 'value', None)


class _CorrelationIdFilter(logging.Filter):
    """Logging filter that adds ``correlation_id`` to every LogRecord."""

    def filter(self, record):
        record.correlation_id = get_correlation_id() or '-'
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
        cid = request.META.get('HTTP_X_REQUEST_ID') or uuid.uuid4().hex
        _correlation_id.value = cid
        request.correlation_id = cid

        response = self.get_response(request)

        response['X-Request-ID'] = cid
        _correlation_id.value = None
        return response
