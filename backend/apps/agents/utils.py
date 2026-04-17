"""Retry utilities for the agents pipeline."""

import functools
import logging
import random
import time

import anthropic

from .exceptions import LLMAuthError, LLMRateLimitError, LLMServiceError, LLMTimeoutError

logger = logging.getLogger("agents.utils")

# Cap any single sleep to avoid blocking Celery workers for long stretches.
# Exponential backoff can exceed a minute on repeated failures, which starves
# the worker pool — bound it + add jitter to prevent thundering-herd retries.
MAX_BACKOFF_SECONDS = 5.0


def _bounded_sleep(delay):
    """Sleep for min(delay, MAX_BACKOFF_SECONDS) plus up to 0.5s jitter."""
    capped = min(delay, MAX_BACKOFF_SECONDS) + random.uniform(0, 0.5)  # noqa: S311 - jitter, not cryptographic
    time.sleep(capped)


def retry_llm_call(max_attempts=3, base_delay=1.0):
    """Decorator that retries LLM calls with typed exception handling.

    - ``anthropic.AuthenticationError`` -> raise immediately (never retry)
    - ``anthropic.RateLimitError`` -> retry with longer backoff (2^(attempt+1) * base_delay)
    - ``anthropic.APITimeoutError``, ``anthropic.APIConnectionError`` -> retry standard backoff
    - ``anthropic.APIStatusError`` where status >= 500 -> retry; status < 500 -> raise
    - After *max_attempts* -> raise ``LLMServiceError`` wrapping the last error
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except anthropic.AuthenticationError as e:
                    logger.error("LLM auth error (not retryable): %s", e)
                    raise LLMAuthError(str(e)) from e
                except anthropic.RateLimitError as e:
                    last_exc = e
                    if attempt < max_attempts:
                        delay = (2 ** (attempt + 1)) * base_delay
                        logger.warning(
                            "LLM rate limit hit, retry %d/%d in %.1fs: %s",
                            attempt,
                            max_attempts,
                            delay,
                            e,
                        )
                        _bounded_sleep(delay)
                    else:
                        raise LLMRateLimitError(str(e)) from e
                except anthropic.APITimeoutError as e:
                    last_exc = e
                    if attempt < max_attempts:
                        delay = (2**attempt) * base_delay
                        logger.warning(
                            "LLM timeout, retry %d/%d in %.1fs: %s",
                            attempt,
                            max_attempts,
                            delay,
                            e,
                        )
                        _bounded_sleep(delay)
                    else:
                        raise LLMTimeoutError(str(e)) from e
                except anthropic.APIConnectionError as e:
                    last_exc = e
                    if attempt < max_attempts:
                        delay = (2**attempt) * base_delay
                        logger.warning(
                            "LLM connection error, retry %d/%d in %.1fs: %s",
                            attempt,
                            max_attempts,
                            delay,
                            e,
                        )
                        _bounded_sleep(delay)
                    else:
                        raise LLMServiceError(str(e)) from e
                except anthropic.APIStatusError as e:
                    last_exc = e
                    if e.status_code >= 500:
                        if attempt < max_attempts:
                            delay = (2**attempt) * base_delay
                            logger.warning(
                                "LLM server error (%d), retry %d/%d in %.1fs: %s",
                                e.status_code,
                                attempt,
                                max_attempts,
                                delay,
                                e,
                            )
                            _bounded_sleep(delay)
                        else:
                            raise LLMServiceError(str(e)) from e
                    else:
                        # 4xx (non-auth, non-rate-limit) — not retryable
                        logger.error("LLM client error (%d, not retryable): %s", e.status_code, e)
                        raise LLMServiceError(str(e)) from e
                except Exception:
                    # Unexpected — don't retry
                    raise

            # Should not reach here, but safety net
            raise LLMServiceError(f"LLM call failed after {max_attempts} attempts") from last_exc

        return wrapper

    return decorator
