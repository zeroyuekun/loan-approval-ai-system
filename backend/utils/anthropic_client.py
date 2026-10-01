import os

import anthropic
import httpx


def make_anthropic_client():
    """Construct an Anthropic client if ANTHROPIC_API_KEY is set, else None.

    The single construction point for every Anthropic caller (decision email,
    marketing email, NBO, bias detectors), so timeout and retry policy cannot
    drift between them.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    return anthropic.Anthropic(
        api_key=api_key,
        timeout=httpx.Timeout(60.0, connect=10.0),
        # Pin the SDK's transient-error retry policy (connect errors,
        # 408/429/5xx with backoff) so the relied-upon default can't drift.
        max_retries=2,
    )
