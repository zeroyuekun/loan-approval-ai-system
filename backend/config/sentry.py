"""Keep request bodies and stack-frame locals out of Sentry events.

Login, registration and loan application bodies carry passwords, income and
identity details, and the local variables in a stack frame hold the same
values. send_default_pii=False does not stop the SDK sending either, so the
init in settings turns both off at the source and this hook strips anything
that still gets through.
"""


def _strip_frame_vars(stacktrace):
    if not isinstance(stacktrace, dict):
        return
    for frame in stacktrace.get("frames") or ():
        if isinstance(frame, dict):
            frame.pop("vars", None)


def scrub_event(event, hint):
    """Sentry before_send hook: drop the request body and every frame's locals."""
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
    _strip_frame_vars(event.get("stacktrace"))
    for key in ("exception", "threads"):
        container = event.get(key)
        if isinstance(container, dict):
            for value in container.get("values") or ():
                if isinstance(value, dict):
                    _strip_frame_vars(value.get("stacktrace"))
    return event
