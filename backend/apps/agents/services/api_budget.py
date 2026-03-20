"""Redis-based daily API call counter and circuit breaker for Claude API.

Prevents runaway costs by enforcing:
- Daily call limit (default: 500 calls/day)
- Daily cost budget (tracked but not hard-enforced, for alerting)
- Circuit breaker: after N consecutive failures in M minutes, block calls temporarily

Usage:
    budget = ApiBudgetGuard()
    budget.check_budget()  # Raises BudgetExhausted if over limit
    # ... make API call ...
    budget.record_call(input_tokens=500, output_tokens=200)
    budget.record_success()  # or budget.record_failure()
"""

import logging
import time

from django.conf import settings

logger = logging.getLogger('agents.api_budget')


class BudgetExhausted(Exception):
    """Raised when the daily API budget is exhausted."""
    pass


class CircuitOpen(Exception):
    """Raised when the circuit breaker is open due to consecutive failures."""
    pass


class ApiBudgetGuard:
    """Redis-based daily call counter + circuit breaker."""

    # Keys expire after 25 hours to cover timezone edge cases
    KEY_TTL = 90000

    def __init__(self):
        self._redis = None

    def _get_redis(self):
        if self._redis is None:
            import redis
            broker_url = settings.CELERY_BROKER_URL
            self._redis = redis.from_url(broker_url, socket_connect_timeout=3)
        return self._redis

    def _daily_key(self, suffix):
        from datetime import date
        return f'ai_budget:{date.today().isoformat()}:{suffix}'

    def check_budget(self):
        """Raise BudgetExhausted if daily limit reached, CircuitOpen if breaker tripped."""
        try:
            r = self._get_redis()

            # Check circuit breaker
            cb_key = 'ai_budget:circuit_breaker'
            if r.exists(cb_key):
                ttl = r.ttl(cb_key)
                raise CircuitOpen(
                    f'Circuit breaker open — {ttl}s remaining. '
                    f'Too many consecutive API failures.'
                )

            # Check daily call count
            daily_limit = getattr(settings, 'AI_DAILY_CALL_LIMIT', 500)
            call_count = int(r.get(self._daily_key('calls')) or 0)
            if call_count >= daily_limit:
                raise BudgetExhausted(
                    f'Daily API call limit reached ({call_count}/{daily_limit}). '
                    f'Resets at midnight UTC.'
                )
        except (BudgetExhausted, CircuitOpen):
            raise
        except Exception as e:
            # If Redis is down, allow the call (fail-open for availability)
            logger.warning('Budget check failed (Redis unavailable): %s — allowing call', e)

    def record_call(self, input_tokens=0, output_tokens=0):
        """Increment daily call counter and token usage."""
        try:
            r = self._get_redis()
            pipe = r.pipeline()

            calls_key = self._daily_key('calls')
            tokens_key = self._daily_key('tokens')

            pipe.incr(calls_key)
            pipe.expire(calls_key, self.KEY_TTL)
            pipe.incrby(tokens_key, input_tokens + output_tokens)
            pipe.expire(tokens_key, self.KEY_TTL)

            pipe.execute()
        except Exception as e:
            logger.warning('Failed to record API call: %s', e)

    def record_success(self):
        """Reset consecutive failure counter on success."""
        try:
            r = self._get_redis()
            r.delete('ai_budget:consecutive_failures')
        except Exception:
            pass

    def record_failure(self):
        """Increment consecutive failure counter. Trip circuit breaker after threshold."""
        try:
            r = self._get_redis()
            key = 'ai_budget:consecutive_failures'
            failures = r.incr(key)
            r.expire(key, 300)  # 5 minute window

            failure_threshold = getattr(settings, 'AI_CIRCUIT_BREAKER_THRESHOLD', 3)
            cooldown_seconds = getattr(settings, 'AI_CIRCUIT_BREAKER_COOLDOWN', 600)

            if failures >= failure_threshold:
                r.setex('ai_budget:circuit_breaker', cooldown_seconds, 1)
                logger.error(
                    'Circuit breaker tripped: %d consecutive API failures. '
                    'Blocking calls for %ds.',
                    failures, cooldown_seconds,
                )
        except Exception as e:
            logger.warning('Failed to record API failure: %s', e)

    def get_daily_stats(self):
        """Return current daily usage stats."""
        try:
            r = self._get_redis()
            return {
                'calls': int(r.get(self._daily_key('calls')) or 0),
                'tokens': int(r.get(self._daily_key('tokens')) or 0),
                'limit': getattr(settings, 'AI_DAILY_CALL_LIMIT', 500),
                'circuit_breaker_open': bool(r.exists('ai_budget:circuit_breaker')),
            }
        except Exception:
            return {'calls': 0, 'tokens': 0, 'limit': 500, 'circuit_breaker_open': False}
