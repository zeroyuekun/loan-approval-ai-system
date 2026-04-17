"""Sleep cap + jitter for retry_llm_call decorator.

These tests protect Celery workers from long blocking sleeps: the original
implementation computed 2**(attempt+1) * base_delay without a cap, which
could block a worker for 40s+ per retry cycle on rate-limit paths.
"""
from unittest.mock import patch

import anthropic
import httpx

from apps.agents.utils import retry_llm_call


def _fake_rate_limit_error():
    response = httpx.Response(429, request=httpx.Request("POST", "https://x"))
    return anthropic.RateLimitError("rate limited", response=response, body=None)


class TestRetrySleepCap:
    @patch("apps.agents.utils.time.sleep")
    def test_sleep_is_capped(self, mock_sleep):
        """Each sleep must be <= MAX_BACKOFF_SECONDS (+ jitter) to avoid blocking workers."""
        attempts = {"n": 0}

        @retry_llm_call(max_attempts=3, base_delay=10.0)  # Would produce 40s + 80s without cap
        def _flaky():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise _fake_rate_limit_error()
            return "ok"

        result = _flaky()
        assert result == "ok"
        assert mock_sleep.call_count >= 1
        # Every sleep must be capped at MAX_BACKOFF_SECONDS (5s) + jitter (<=0.5s)
        for call in mock_sleep.call_args_list:
            delay = call.args[0]
            assert delay <= 5.5, f"sleep({delay}) exceeds cap"

    @patch("apps.agents.utils.time.sleep")
    def test_sleep_has_jitter(self, mock_sleep):
        """Two identical retry sequences must not produce identical sleep values."""
        sleeps_a: list[float] = []
        sleeps_b: list[float] = []

        for sink in (sleeps_a, sleeps_b):
            mock_sleep.reset_mock()
            attempts = {"n": 0}

            @retry_llm_call(max_attempts=3, base_delay=1.0)
            def _flaky():
                attempts["n"] += 1
                if attempts["n"] < 3:
                    raise _fake_rate_limit_error()
                return "ok"

            _flaky()
            sink.extend(c.args[0] for c in mock_sleep.call_args_list)

        # With jitter, two runs will almost never produce identical sleep sequences
        assert sleeps_a != sleeps_b
