class RateLimited(Exception):
    """Raised by EmailGenerator when the Claude API rate-limits.

    The Celery task converts this into a ``self.retry(countdown=...)`` so the
    worker is freed instead of blocking inside a hard ``time_limit`` with a
    ``time.sleep`` (M6/L25).
    """

    def __init__(self, retry_after=30):
        self.retry_after = retry_after
        super().__init__(f"Claude API rate limited; retry after {retry_after}s")


class EmailBackendError(Exception):
    """Raised by an OpenAI-compatible email backend adapter when the provider
    fails in a way that should DEGRADE TO THE DETERMINISTIC TEMPLATE rather than
    crash: a non-retryable HTTP error (e.g. 413 request-too-large, 4xx, 5xx) or
    a transport failure.

    EmailGenerator catches this (alongside ``anthropic.APIError``) and returns
    the template fallback, so a provider hiccup never leaves a customer without a
    compliant email. A 429 is handled separately as ``RateLimited`` (Celery
    retry); programming errors (AttributeError, KeyError, ...) are NOT wrapped in
    this, so they still surface as real bugs.
    """
