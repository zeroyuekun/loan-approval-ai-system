"""Strip credentials and personal data from Sentry events before they are sent.

Login, registration and loan application bodies carry passwords, income and
identity details, and the local variables in a stack frame hold the same
values. send_default_pii=False does not stop the SDK sending either, so the
init in settings turns both off at the source and this hook strips anything
that still gets through. The request and user handling mirrors the
frontend's scrubEvent (frontend/src/lib/sentryScrub.ts); log and breadcrumb
messages go through the same regex redaction as the application logs.
"""

from config.logging_filters import redact_pii

# Request headers that carry credentials or session state (as in sentryScrub.ts).
_SENSITIVE_HEADERS = frozenset({"cookie", "set-cookie", "authorization", "x-csrftoken", "x-csrf-token"})


def _scrub_request(request):
    for key in ("data", "cookies", "query_string"):
        request.pop(key, None)
    headers = request.get("headers")
    if isinstance(headers, dict):
        request["headers"] = {name: value for name, value in headers.items() if name.lower() not in _SENSITIVE_HEADERS}


def _strip_frame_vars(stacktrace):
    if not isinstance(stacktrace, dict):
        return
    for frame in stacktrace.get("frames") or ():
        if isinstance(frame, dict):
            frame.pop("vars", None)


def _redact_logentry(logentry):
    for key in ("message", "formatted"):
        if isinstance(logentry.get(key), str):
            logentry[key] = redact_pii(logentry[key])
    params = logentry.get("params")
    if isinstance(params, (list, tuple)):
        logentry["params"] = [redact_pii(p) if isinstance(p, str) else p for p in params]


def _redact_breadcrumbs(breadcrumbs):
    if not isinstance(breadcrumbs, dict):
        return
    for crumb in breadcrumbs.get("values") or ():
        if isinstance(crumb, dict) and isinstance(crumb.get("message"), str):
            crumb["message"] = redact_pii(crumb["message"])


def scrub_event(event, hint):
    """Sentry before_send hook (also used for transactions)."""
    request = event.get("request")
    if isinstance(request, dict):
        _scrub_request(request)

    user = event.get("user")
    if isinstance(user, dict):
        event["user"] = {"id": user["id"]} if "id" in user else {}

    _strip_frame_vars(event.get("stacktrace"))
    for key in ("exception", "threads"):
        container = event.get(key)
        if isinstance(container, dict):
            for value in container.get("values") or ():
                if isinstance(value, dict):
                    _strip_frame_vars(value.get("stacktrace"))
                    if isinstance(value.get("value"), str):
                        value["value"] = redact_pii(value["value"])

    if isinstance(event.get("message"), str):
        event["message"] = redact_pii(event["message"])
    if isinstance(event.get("logentry"), dict):
        _redact_logentry(event["logentry"])
    _redact_breadcrumbs(event.get("breadcrumbs"))
    return event
