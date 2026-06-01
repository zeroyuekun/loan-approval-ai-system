"""Redis-based daily API budget guard for Claude API.

Prevents runaway costs by enforcing:
- Daily dollar budget (hard cap — blocks calls when exceeded)
- Daily call limit (default: 500 calls/day)
- Circuit breaker: after N consecutive failures in M minutes, block calls temporarily

Usage:
    budget = ApiBudgetGuard()
    budget.check_budget()  # Raises BudgetExhausted if over limit
    # ... make API call ...
    budget.record_call(input_tokens=500, output_tokens=200, model='claude-sonnet-4-6')
    budget.record_success()  # or budget.record_failure()

Or use the guarded_api_call() wrapper which handles all of the above:
    from apps.agents.services.api_budget import guarded_api_call
    response = guarded_api_call(client, model='claude-sonnet-4-6', ...)
"""

import hashlib
import logging
import threading

import redis
from django.conf import settings

logger = logging.getLogger("agents.api_budget")

# Anthropic pricing per million tokens. Verified April 2026 against
# https://platform.claude.com/docs/en/docs/about-claude/models/overview
# Legacy IDs retained so historical APICallLog records resolve correctly.
MODEL_PRICING = {
    # Current models
    "claude-opus-4-7": {"input": 5.00, "output": 25.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    # Opus 4.6 — still generally available; same per-token pricing as 4.7
    "claude-opus-4-6": {"input": 5.00, "output": 25.00},
    # Legacy Claude 4 (May 2025) — deprecated, retiring 2026-06-15
    "claude-opus-4-20250514": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-20250514": {"input": 0.25, "output": 1.25},
}

# Fallback: assume Sonnet pricing for unknown models
_DEFAULT_PRICING = {"input": 3.00, "output": 15.00}


def estimate_cost_usd(input_tokens, output_tokens, model=""):
    """Estimate cost in USD for a single API call."""
    pricing = MODEL_PRICING.get(model, _DEFAULT_PRICING)
    cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
    return round(cost, 6)


# Conservative floor reserved per call when token counts are unknown up front.
_RESERVE_FLOOR_CENTS = 5


def _estimate_reserve_cents(model, max_tokens=None):
    """Worst-case cents to reserve before a call whose real token usage is unknown.

    Assumes a large-ish prompt (8k input) producing up to ``max_tokens`` output.
    Never returns below ``_RESERVE_FLOOR_CENTS``.
    """
    cost_usd = estimate_cost_usd(8000, max_tokens or 2048, model)
    return max(_RESERVE_FLOOR_CENTS, int(cost_usd * 100))


# Atomic check-and-reserve executed server-side so check+increment is a single
# round-trip (concurrent workers serialise on the counter, killing the M5 TOCTOU
# race). KEYS[1]=cost_cents key, KEYS[2]=calls key.
# ARGV[1]=cost_cents to add, ARGV[2]=calls to add, ARGV[3]=budget_limit_cents,
# ARGV[4]=call_limit, ARGV[5]=ttl. Returns {ok, new_cost_cents, new_calls}.
_RESERVE_LUA = """
local cost = tonumber(redis.call('GET', KEYS[1]) or '0')
local calls = tonumber(redis.call('GET', KEYS[2]) or '0')
if (cost + tonumber(ARGV[1])) > tonumber(ARGV[3]) then
    return {0, cost, calls}
end
if (calls + tonumber(ARGV[2])) > tonumber(ARGV[4]) then
    return {0, cost, calls}
end
local newcost = redis.call('INCRBY', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[5])
local newcalls = redis.call('INCRBY', KEYS[2], ARGV[2])
redis.call('EXPIRE', KEYS[2], ARGV[5])
return {1, newcost, newcalls}
"""


class BudgetExhausted(Exception):
    """Raised when the daily API budget is exhausted."""

    pass


class CircuitOpen(Exception):
    """Raised when the circuit breaker is open due to consecutive failures."""

    pass


# Process-local fallback counter used when Redis is unavailable.
# Survives for the lifetime of the worker process only, which is acceptable:
# it caps cost exposure during a Redis outage without blocking traffic entirely.
_REDIS_FALLBACK_CALLS = 0
_REDIS_FALLBACK_LIMIT = 20  # calls per process during Redis outage
_REDIS_FALLBACK_LOCK = threading.Lock()


class ApiBudgetGuard:
    """Redis-based daily call counter, dollar tracker, and circuit breaker."""

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

        return f"ai_budget:{date.today().isoformat()}:{suffix}"

    def check_budget(self):
        """Raise BudgetExhausted if daily limit reached, CircuitOpen if breaker tripped.

        Advisory pre-flight only. It reads-then-decides, so under concurrency it can
        let several callers past the cap simultaneously. Callers (EmailGenerator,
        marketing_agent, next_best_offer) use it as a cheap "should I even try the API
        or go straight to a template" hint. The AUTHORITATIVE gate is
        ``reserve_budget`` inside ``guarded_api_call``, which reserves atomically before
        the API round-trip (M5).
        """
        global _REDIS_FALLBACK_CALLS
        try:
            r = self._get_redis()

            # Check circuit breaker
            cb_key = "ai_budget:circuit_breaker"
            if r.exists(cb_key):
                ttl = r.ttl(cb_key)
                raise CircuitOpen(f"Circuit breaker open — {ttl}s remaining. Too many consecutive API failures.")

            # Check daily dollar spend
            budget_limit = getattr(settings, "AI_DAILY_BUDGET_LIMIT_USD", 5.0)
            cost_cents = int(r.get(self._daily_key("cost_cents")) or 0)
            spent_usd = cost_cents / 100
            if spent_usd >= budget_limit:
                raise BudgetExhausted(
                    f"Daily budget exhausted (${spent_usd:.2f}/${budget_limit:.2f}). "
                    f"Pipeline will use template fallback. Resets at midnight UTC."
                )

            # Check daily call count
            daily_limit = getattr(settings, "AI_DAILY_CALL_LIMIT", 500)
            call_count = int(r.get(self._daily_key("calls")) or 0)
            if call_count >= daily_limit:
                raise BudgetExhausted(
                    f"Daily API call limit reached ({call_count}/{daily_limit}). Resets at midnight UTC."
                )

            # Happy path — Redis is healthy and under limits.
            # Reset the process-local fallback counter so a transient outage
            # does not permanently brick this worker (F-04).
            with _REDIS_FALLBACK_LOCK:
                _REDIS_FALLBACK_CALLS = 0
        except (BudgetExhausted, CircuitOpen):
            raise
        except (redis.RedisError, ConnectionError, TimeoutError) as e:
            # Redis is unavailable. We can't enforce the true daily budget, but
            # we MUST still cap cost exposure — fail-open previously allowed
            # unlimited calls during an outage. Use a per-process fallback
            # counter so brief blips don't kill availability, but a sustained
            # Redis outage won't run up the API bill. The increment must be
            # lock-guarded because Celery IO workers run with concurrency > 1
            # and unlocked += is not atomic on multi-threaded Python.
            with _REDIS_FALLBACK_LOCK:
                _REDIS_FALLBACK_CALLS += 1
                current = _REDIS_FALLBACK_CALLS
            if current > _REDIS_FALLBACK_LIMIT:
                raise BudgetExhausted(
                    f"Redis unavailable and per-process fallback limit reached "
                    f"({current}/{_REDIS_FALLBACK_LIMIT}). "
                    f"Blocking calls until Redis recovers. Reason: {e}"
                ) from e
            logger.warning(
                "Budget check failed (Redis unavailable, %d/%d fallback calls used): %s",
                current,
                _REDIS_FALLBACK_LIMIT,
                e,
            )

    def reserve_budget(self, estimated_cost_cents=_RESERVE_FLOOR_CENTS, estimated_calls=1):
        """Atomically reserve budget BEFORE the API call (authoritative M5 gate).

        Performs check+increment of the cost and call counters in a single Redis
        round-trip via a Lua script, so N concurrent workers serialise on the
        counter and the $5/day cap can no longer be overshot. Raises
        ``BudgetExhausted`` if the reservation would breach the dollar or call cap
        (the counter is NOT incremented in that case — no leak). Returns the cents
        actually reserved so ``record_call`` can reconcile to the true cost.

        On a Redis outage it falls back to the same per-process cap that
        ``check_budget`` uses and returns 0 (reserved nothing; record_call records
        the real cost).
        """
        estimated_cost_cents = max(_RESERVE_FLOOR_CENTS, int(estimated_cost_cents))
        budget_limit = getattr(settings, "AI_DAILY_BUDGET_LIMIT_USD", 5.0)
        budget_limit_cents = int(budget_limit * 100)
        call_limit = getattr(settings, "AI_DAILY_CALL_LIMIT", 500)
        global _REDIS_FALLBACK_CALLS
        try:
            r = self._get_redis()
            cb_key = "ai_budget:circuit_breaker"
            if r.exists(cb_key):
                ttl = r.ttl(cb_key)
                raise CircuitOpen(f"Circuit breaker open — {ttl}s remaining. Too many consecutive API failures.")

            script = r.register_script(_RESERVE_LUA)
            ok, _new_cost, _new_calls = script(
                keys=[self._daily_key("cost_cents"), self._daily_key("calls")],
                args=[estimated_cost_cents, estimated_calls, budget_limit_cents, call_limit, self.KEY_TTL],
            )
            if not int(ok):
                raise BudgetExhausted(
                    f"Daily budget/call cap would be exceeded (reserve {estimated_cost_cents}c, "
                    f"limit ${budget_limit:.2f}). Pipeline will use template fallback. Resets at midnight UTC."
                )

            # Healthy Redis — reset the process-local fallback counter (F-04).
            with _REDIS_FALLBACK_LOCK:
                _REDIS_FALLBACK_CALLS = 0
            return estimated_cost_cents
        except (BudgetExhausted, CircuitOpen):
            raise
        except (redis.RedisError, ConnectionError, TimeoutError) as e:
            # Redis unavailable: reuse the per-process fallback cap so a brief
            # blip doesn't brick the worker but a sustained outage can't run up
            # the bill. Reserve nothing — record_call records the actual cost.
            with _REDIS_FALLBACK_LOCK:
                _REDIS_FALLBACK_CALLS += 1
                current = _REDIS_FALLBACK_CALLS
            if current > _REDIS_FALLBACK_LIMIT:
                raise BudgetExhausted(
                    f"Redis unavailable and per-process fallback limit reached "
                    f"({current}/{_REDIS_FALLBACK_LIMIT}). Reason: {e}"
                ) from e
            logger.warning(
                "Budget reserve failed (Redis unavailable, %d/%d): %s",
                current,
                _REDIS_FALLBACK_LIMIT,
                e,
            )
            return 0

    def record_call(self, input_tokens=0, output_tokens=0, model="", reserved_cents=0, released=False):
        """Record actual usage, reconciling any prior reservation to the true cost.

        Three paths, keyed off ``reserved_cents`` and ``released``:

        * **Failure release** (``reserved_cents`` > 0 and ``released`` is True): the
          guarded call reserved budget but the API call failed and produced no
          billable tokens. FULLY release the reservation — no ``max(1, …)`` floor,
          so the cost counter returns to its pre-reserve value (``cost_delta`` is
          ``-reserved`` when actual cost is 0) — AND decrement the calls counter by
          1, since ``reserve_budget`` had incremented it for a call that never
          completed.

        * **Successful reconcile** (``reserved_cents`` > 0 and ``released`` is
          False): the call succeeded. The call was already counted inside
          ``reserve_budget`` so keep the call counted; only INCRBY the delta
          ``actual - reserved`` (may be a DECRBY) so cost settles at the true value.

        * **Unreserved fallback** (``reserved_cents`` == 0): the call was never
          reserved (Redis was down at reserve time, or a legacy caller). Count the
          call + full cost, keeping the ``max(1, …)`` minimum-cent floor.
        """
        try:
            r = self._get_redis()
            pipe = r.pipeline()

            calls_key = self._daily_key("calls")
            tokens_key = self._daily_key("tokens")
            cost_key = self._daily_key("cost_cents")

            reserved = int(reserved_cents)
            cost_usd = estimate_cost_usd(input_tokens, output_tokens, model)

            if reserved > 0 and released:
                # Failure release: undo the reservation in full. No cent floor —
                # the call produced no billable cost — and give back the call slot
                # that reserve_budget consumed.
                actual_cents = int(cost_usd * 100)
                cost_delta = actual_cents - reserved
                pipe.decr(calls_key)
                pipe.expire(calls_key, self.KEY_TTL)
            elif reserved > 0:
                # Successful reconcile to the real cost. The call was already
                # counted inside reserve_budget, so do NOT touch calls again.
                cost_cents = max(1, int(cost_usd * 100))  # minimum 1 cent per real call
                cost_delta = cost_cents - reserved
            else:
                # Fallback path: the call was never reserved. Count the call +
                # full cost with the minimum-cent floor.
                cost_cents = max(1, int(cost_usd * 100))  # minimum 1 cent per call
                pipe.incr(calls_key)
                pipe.expire(calls_key, self.KEY_TTL)
                cost_delta = cost_cents

            pipe.incrby(tokens_key, input_tokens + output_tokens)
            pipe.expire(tokens_key, self.KEY_TTL)
            if cost_delta != 0:
                pipe.incrby(cost_key, cost_delta)
            pipe.expire(cost_key, self.KEY_TTL)

            pipe.execute()

            logger.info(
                "API call recorded: %d in + %d out tokens, model=%s, cost=$%.4f "
                "(reserved=%dc, delta=%dc, released=%s)",
                input_tokens,
                output_tokens,
                model or "unknown",
                cost_usd,
                reserved,
                cost_delta,
                released,
            )
        except (redis.RedisError, ConnectionError, TimeoutError) as e:
            logger.warning("Failed to record API call (Redis): %s", e)

    def record_success(self):
        """Reset consecutive failure counter on success."""
        try:
            r = self._get_redis()
            r.delete("ai_budget:consecutive_failures")
        except (redis.RedisError, ConnectionError, TimeoutError) as e:
            logger.debug("Failed to reset failure counter (Redis): %s", e)

    def record_failure(self):
        """Increment consecutive failure counter. Trip circuit breaker after threshold."""
        try:
            r = self._get_redis()
            key = "ai_budget:consecutive_failures"
            failures = r.incr(key)
            r.expire(key, 300)  # 5 minute window

            failure_threshold = getattr(settings, "AI_CIRCUIT_BREAKER_THRESHOLD", 3)
            cooldown_seconds = getattr(settings, "AI_CIRCUIT_BREAKER_COOLDOWN", 600)

            if failures >= failure_threshold:
                r.setex("ai_budget:circuit_breaker", cooldown_seconds, 1)
                logger.error(
                    "Circuit breaker tripped: %d consecutive API failures. Blocking calls for %ds.",
                    failures,
                    cooldown_seconds,
                )
        except (redis.RedisError, ConnectionError, TimeoutError) as e:
            logger.warning("Failed to record API failure (Redis): %s", e)

    def get_daily_stats(self):
        """Return current daily usage stats."""
        try:
            r = self._get_redis()
            cost_cents = int(r.get(self._daily_key("cost_cents")) or 0)
            return {
                "calls": int(r.get(self._daily_key("calls")) or 0),
                "tokens": int(r.get(self._daily_key("tokens")) or 0),
                "cost_usd": cost_cents / 100,
                "budget_limit_usd": getattr(settings, "AI_DAILY_BUDGET_LIMIT_USD", 5.0),
                "call_limit": getattr(settings, "AI_DAILY_CALL_LIMIT", 500),
                "circuit_breaker_open": bool(r.exists("ai_budget:circuit_breaker")),
            }
        except (redis.RedisError, ConnectionError, TimeoutError) as e:
            logger.debug("Failed to fetch daily stats (Redis): %s", e)
            return {
                "calls": 0,
                "tokens": 0,
                "cost_usd": 0.0,
                "budget_limit_usd": getattr(settings, "AI_DAILY_BUDGET_LIMIT_USD", 5.0),
                "call_limit": 500,
                "circuit_breaker_open": False,
            }


def _extract_prompt_text(kwargs):
    """Extract prompt text from API call kwargs for hashing."""
    parts = []
    system = kwargs.get("system", "")
    if system:
        parts.append(str(system))
    for msg in kwargs.get("messages", []):
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
    return "\n".join(parts)


def _detect_pii_categories(prompt_text):
    """Detect PII categories present in the prompt text."""
    category_keywords = {
        "name": ["name", "applicant", "customer"],
        "income": ["income", "salary", "earnings"],
        "employment": ["employment", "employer", "job", "occupation"],
        "loan_amount": ["loan_amount", "loan amount", "borrowing"],
        "credit_score": ["credit_score", "credit score"],
        "address": ["address", "postcode", "suburb"],
        "email": ["email"],
        "phone": ["phone", "mobile"],
    }
    lower_text = prompt_text.lower()
    return [cat for cat, keywords in category_keywords.items() if any(kw in lower_text for kw in keywords)]


def guarded_api_call(client, **kwargs):
    """Make a Claude API call with budget guard and cost tracking.

    Wraps client.messages.create() with pre-flight budget check and
    post-call cost recording. Raises BudgetExhausted if daily limit
    is exceeded — callers should catch this and fall back to templates
    or deterministic logic.

    Args:
        client: anthropic.Anthropic instance (or None to raise immediately)
        **kwargs: passed directly to client.messages.create()
            Extra keyword args (not passed to API):
            - _service: str — service name for API call logging (e.g. 'email_generation')
            - _loan_application_id: UUID — FK to LoanApplication
            - _agent_run_id: UUID — FK to AgentRun

    Returns:
        The API response object.

    Raises:
        BudgetExhausted: daily dollar or call limit reached
        CircuitOpen: too many consecutive failures
        ValueError: client is None (no API key configured)
    """
    if client is None:
        raise BudgetExhausted("No API client configured — using fallback")

    # Pop internal metadata before passing to API
    service = kwargs.pop("_service", "unknown")
    loan_application_id = kwargs.pop("_loan_application_id", None)
    agent_run_id = kwargs.pop("_agent_run_id", None)

    model = kwargs.get("model", "")
    budget = ApiBudgetGuard()
    # Authoritative atomic gate (M5): reserve a conservative worst-case before the
    # call so concurrent workers cannot collectively overshoot the daily cap.
    reserved = budget.reserve_budget(
        estimated_cost_cents=_estimate_reserve_cents(model, kwargs.get("max_tokens")),
    )

    try:
        response = client.messages.create(**kwargs)
    except Exception:
        budget.record_failure()
        # Release the reservation in full — the call never produced billable
        # tokens, so give back BOTH the reserved cost and the call slot.
        budget.record_call(input_tokens=0, output_tokens=0, model=model, reserved_cents=reserved, released=True)
        raise

    # Track cost from actual usage, reconciling the reservation to the true cost.
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
    budget.record_call(input_tokens=input_tokens, output_tokens=output_tokens, model=model, reserved_cents=reserved)
    budget.record_success()

    # Log API call for PII cross-border audit (Privacy Act APP 8)
    try:
        from apps.agents.models import APICallLog

        prompt_text = _extract_prompt_text(kwargs)
        APICallLog.objects.create(
            loan_application_id=loan_application_id,
            agent_run_id=agent_run_id,
            service=service,
            provider="anthropic",
            model_used=model,
            pii_categories=_detect_pii_categories(prompt_text),
            prompt_hash=hashlib.sha256(prompt_text.encode()).hexdigest(),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            destination_country="US",
        )
    except Exception as e:
        logger.warning("Failed to create APICallLog: %s", e)

    return response
