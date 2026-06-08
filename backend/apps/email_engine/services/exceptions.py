class RateLimited(Exception):
    """Raised by EmailGenerator when the Claude API rate-limits.

    The Celery task converts this into a ``self.retry(countdown=...)`` so the
    worker is freed instead of blocking inside a hard ``time_limit`` with a
    ``time.sleep`` (M6/L25).
    """

    def __init__(self, retry_after=30):
        self.retry_after = retry_after
        super().__init__(f"Claude API rate limited; retry after {retry_after}s")
