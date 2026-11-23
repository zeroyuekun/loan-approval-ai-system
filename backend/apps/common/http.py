"""Request helpers shared across apps."""

import ipaddress

from rest_framework.throttling import BaseThrottle

_throttle = BaseThrottle()


def client_ip(request) -> str | None:
    """The client's IP address for the audit trail.

    Uses the same rule as the DRF throttles (BaseThrottle.get_ident), so it
    honours REST_FRAMEWORK["NUM_PROXIES"]: behind N trusted proxies it takes
    the address the outermost one appended to X-Forwarded-For, otherwise
    REMOTE_ADDR. Works on a DRF Request or a plain Django HttpRequest. Falls
    back to REMOTE_ADDR when the derived value is not an IP address (a client
    talking to the backend directly can send any header).
    """
    remote_addr = request.META.get("REMOTE_ADDR")
    ident = _throttle.get_ident(request)
    try:
        ipaddress.ip_address(ident)
    except ValueError:
        return remote_addr
    return ident


def page_params(request, default_size=20, max_size=100):
    """``(page, page_size)`` from the query string, each clamped to a usable range.

    Non-numbers fall back to the defaults; values below 1 become 1, so a
    hand-written paginator never builds a negative slice (a 500).
    """

    def _int(name, default):
        try:
            return int(request.query_params.get(name, default))
        except (ValueError, TypeError):
            return default

    page = max(_int("page", 1), 1)
    page_size = min(max(_int("page_size", default_size), 1), max_size)
    return page, page_size
