"""Redis-based daily API budget guard for Claude API.

Prevents runaway costs by enforcing:
- Daily dollar budget (hard cap — blocks calls when exceeded)
- Daily call limit (default: 500 calls/day)
- Circuit breaker PER PROVIDER: after N consecutive TRANSIENT failures (timeout,
  connection, 5xx, 429) in M minutes, block that provider's calls temporarily.
  A 4xx such as a free-tier 413 never trips it, and one provider's outage
  never blocks another provider.

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

import contextvars
import hashlib
import logging
import threading
from contextlib import contextmanager

import redis
from django.conf import settings

logger = logging.getLogger("agents.api_budget")

# ---------------------------------------------------------------------------
# APP 8 attribution context
#
# Which application / AgentRun an LLM call is made for. Entry points (the
# orchestrator run, the human-review resume) open a scope and guarded_api_call
# reads it, so deep callers such as the bias detector, which never see the
# application, are still attributed. An explicit _loan_application_id /
# _agent_run_id kwarg wins over the context.
# ---------------------------------------------------------------------------

_API_CALL_CONTEXT = contextvars.ContextVar("api_call_context", default=None)


@contextmanager
def api_call_context(**fields):
    """Scope in which LLM calls are attributed to ``application_id`` / ``agent_run_id``."""
    parent = _API_CALL_CONTEXT.get() or {}
    token = _API_CALL_CONTEXT.set({**parent, **{k: v for k, v in fields.items() if v is not None}})
    try:
        yield
    finally:
        _API_CALL_CONTEXT.reset(token)


def bind_api_call_context(**fields):
    """Add fields (e.g. the AgentRun id once created) to the innermost open scope.

    No-op outside an ``api_call_context`` scope, so nothing leaks past it.
    """
    ctx = _API_CALL_CONTEXT.get()
    if ctx is not None:
        ctx.update({k: v for k, v in fields.items() if v is not None})


def current_api_call_context():
    return dict(_API_CALL_CONTEXT.get() or {})


# Anthropic pricing per million tokens. Verified April 2026 against
# https://platform.claude.com/docs/en/docs/about-claude/models/overview
# Legacy IDs retained so historical APICallLog records resolve correctly.
MODEL_PRICING = {
    # Current models
    "claude-fable-5": {"input": 10.00, "output": 50.00},
    "claude-opus-4-8": {"input": 5.00, "output": 25.00},
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

# Model families that REMOVED the sampling parameters — sending temperature/
# top_p/top_k returns HTTP 400 (these are adaptive-thinking-only: Opus 4.7+,
# Fable 5). Steer them with the `effort` parameter instead. We strip these
# kwargs centrally in guarded_api_call so a call site that passes temperature=0
# (valid for Sonnet/Haiku and the Groq/Ollama backends) does not 400 on an
# adaptive-only model. Matched as substrings so dated snapshots
# ("claude-opus-4-8-20260301") and platform-prefixed IDs
# ("anthropic.claude-opus-4-8" on Bedrock) are covered too.
# Add future adaptive-only model families here.
_SAMPLING_PARAMS_REMOVED_FAMILIES = ("claude-opus-4-7", "claude-opus-4-8", "claude-fable-5")
_REMOVED_SAMPLING_KWARGS = ("temperature", "top_p", "top_k")


def _sampling_params_removed(model):
    """True when ``model`` belongs to a family that rejects sampling params."""
    return any(family in model for family in _SAMPLING_PARAMS_REMOVED_FAMILIES)


# Where each provider physically processes the prompt — drives the APICallLog
# cross-border (Privacy Act APP 8) record. Local Ollama runs on-prem in
# Australia, so it is NOT a cross-border disclosure; hosted providers are US.
_PROVIDER_DESTINATION = {"anthropic": "US", "groq": "US", "ollama": "AU"}

# Providers whose calls cost $0/token (free Groq tier, on-prem Ollama). Keyed
# by PROVIDER, not model tag, so any local model tag costs $0 without a
# MODEL_PRICING row. The budget guard still reserves the per-call floor and
# counts the call against the daily call limit.
_FREE_PROVIDERS = frozenset({"groq", "ollama"})

_DEFAULT_PROVIDER = "anthropic"


def _breaker_key(provider):
    return f"ai_budget:circuit_breaker:{provider or _DEFAULT_PROVIDER}"


def _failures_key(provider):
    return f"ai_budget:consecutive_failures:{provider or _DEFAULT_PROVIDER}"


def open_circuit_providers(r):
    """Providers whose breaker is currently open (for health/stats reporting)."""
    return [p for p in _PROVIDER_DESTINATION if r.exists(_breaker_key(p))]


def is_transient_failure(exc):
    """True for failures that say the provider is unhealthy right now.

    Timeouts, connection errors, 5xx and 429 count towards the breaker. A 4xx
    (400 bad request, 401/403 auth, 413 request too large) is a property of the
    request or the configuration: retrying later will not fix it, so tripping
    the breaker would only block healthy traffic.
    """
    import anthropic

    from apps.email_engine.services.exceptions import EmailBackendError, RateLimited

    if isinstance(exc, (RateLimited, TimeoutError, ConnectionError, anthropic.APIConnectionError)):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    if isinstance(exc, EmailBackendError):
        status = getattr(exc, "status_code", None)
        return status is None or status == 429 or status >= 500  # None = transport failure
    return False


def estimate_cost_usd(input_tokens, output_tokens, model="", provider="anthropic"):
    """Estimate cost in USD for a single API call."""
    if provider in _FREE_PROVIDERS:
        return 0.0
    pricing = MODEL_PRICING.get(model, _DEFAULT_PRICING)
    cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
    return round(cost, 6)


# Conservative floor reserved per call when token counts are unknown up front.
_RESERVE_FLOOR_CENTS = 5


def _estimate_reserve_cents(model, max_tokens=None, provider="anthropic"):
    """Worst-case cents to reserve before a call whose real token usage is unknown.

    Assumes a large-ish prompt (8k input) producing up to ``max_tokens`` output.
    Never returns below ``_RESERVE_FLOOR_CENTS``.
    """
    cost_usd = estimate_cost_usd(8000, max_tokens or 2048, model, provider=provider)
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


class ApiGateClosed(Exception):
    """Base for every gate that refuses an API call before it is made.

    Callers that degrade to a template catch this base, so a new gate
    exception cannot slip past a site that only lists the old ones.
    """


class BudgetExhausted(ApiGateClosed):
    """Raised when the daily API budget is exhausted."""


class CircuitOpen(ApiGateClosed):
    """Raised when the circuit breaker is open due to consecutive failures."""


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

    def check_budget(self, provider=_DEFAULT_PROVIDER):
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

            # Check this provider's circuit breaker
            cb_key = _breaker_key(provider)
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
        except ApiGateClosed:
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

    def reserve_budget(self, estimated_cost_cents=_RESERVE_FLOOR_CENTS, estimated_calls=1, provider=_DEFAULT_PROVIDER):
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
            cb_key = _breaker_key(provider)
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
        except ApiGateClosed:
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

    def record_call(
        self, input_tokens=0, output_tokens=0, model="", reserved_cents=0, released=False, provider="anthropic"
    ):
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

        Free providers (``_FREE_PROVIDERS``) cost $0/token, so the minimum-cent
        floor is skipped for them — otherwise every free call would drain a
        phantom cent from the shared daily cap. Call-count accounting is
        unchanged: free calls still consume call slots.
        """
        try:
            r = self._get_redis()
            pipe = r.pipeline()

            calls_key = self._daily_key("calls")
            tokens_key = self._daily_key("tokens")
            cost_key = self._daily_key("cost_cents")

            reserved = int(reserved_cents)
            cost_usd = estimate_cost_usd(input_tokens, output_tokens, model, provider=provider)
            # Minimum 1 cent per real call, except free providers ($0).
            min_cents = 0 if provider in _FREE_PROVIDERS else 1
            floored_cents = max(min_cents, int(cost_usd * 100))

            if reserved > 0 and released:
                # Failure release: undo the reservation in full. No cent floor —
                # the call produced no billable cost — and give back the call slot
                # that reserve_budget consumed.
                actual_cents = int(cost_usd * 100)
                cost_delta = actual_cents - reserved
                # Safe DECR: only decrement when the key exists so an expired
                # calls_key is not initialised to -1 (M21).  Check outside the
                # pipeline (EXISTS is cheap) then DECR + EXPIRE inside it.
                if r.exists(calls_key):
                    pipe.decr(calls_key)
                    pipe.expire(calls_key, self.KEY_TTL)
            elif reserved > 0:
                # Successful reconcile to the real cost. The call was already
                # counted inside reserve_budget, so do NOT touch calls again.
                cost_delta = floored_cents - reserved
            else:
                # Fallback path: the call was never reserved. Count the call +
                # full cost with the minimum-cent floor.
                pipe.incr(calls_key)
                pipe.expire(calls_key, self.KEY_TTL)
                cost_delta = floored_cents

            pipe.incrby(tokens_key, input_tokens + output_tokens)
            pipe.expire(tokens_key, self.KEY_TTL)
            if cost_delta != 0:
                pipe.incrby(cost_key, cost_delta)
            pipe.expire(cost_key, self.KEY_TTL)

            pipe.execute()

            logger.info(
                "API call recorded: %d in + %d out tokens, model=%s, cost=$%.4f (reserved=%dc, delta=%dc, released=%s)",
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

    def record_success(self, provider=_DEFAULT_PROVIDER):
        """Reset this provider's consecutive failure counter on success."""
        try:
            r = self._get_redis()
            r.delete(_failures_key(provider))
        except (redis.RedisError, ConnectionError, TimeoutError) as e:
            logger.debug("Failed to reset failure counter (Redis): %s", e)

    def record_failure(self, provider=_DEFAULT_PROVIDER):
        """Count a TRANSIENT failure for ``provider``; trip its breaker at the threshold.

        Callers decide transience (``is_transient_failure``); this only counts.
        """
        try:
            r = self._get_redis()
            key = _failures_key(provider)
            failures = r.incr(key)
            r.expire(key, 300)  # 5 minute window

            failure_threshold = getattr(settings, "AI_CIRCUIT_BREAKER_THRESHOLD", 3)
            cooldown_seconds = getattr(settings, "AI_CIRCUIT_BREAKER_COOLDOWN", 600)

            if failures >= failure_threshold:
                r.setex(_breaker_key(provider), cooldown_seconds, 1)
                logger.error(
                    "Circuit breaker tripped for %s: %d consecutive transient failures. Blocking calls for %ds.",
                    provider,
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
                "circuit_breaker_open": bool(open_circuit_providers(r)),
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


def _log_api_call(
    kwargs,
    *,
    outcome,
    service,
    provider,
    model,
    loan_application_id,
    agent_run_id,
    pii_categories,
    input_tokens=0,
    output_tokens=0,
):
    """Write the APP 8 cross-border record. Never raises."""
    try:
        from apps.agents.models import APICallLog

        prompt_text = _extract_prompt_text(kwargs)
        APICallLog.objects.create(
            loan_application_id=loan_application_id,
            agent_run_id=agent_run_id,
            service=service,
            provider=provider,
            model_used=model,
            pii_categories=pii_categories,
            prompt_hash=hashlib.sha256(prompt_text.encode()).hexdigest(),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            destination_country=_PROVIDER_DESTINATION.get(provider, "US"),
            outcome=outcome,
        )
    except Exception as e:
        logger.warning("Failed to create APICallLog: %s", e)


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
            - _loan_application_id: UUID — FK to LoanApplication (default: the
              open api_call_context scope)
            - _agent_run_id: UUID — FK to AgentRun (default: the open scope)
            - _pii_categories: list[str] — categories of personal data the
              caller actually interpolated into the prompt, declared from its
              structured fields and never guessed from prompt wording. A call
              that declares none is logged as "unclassified".

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
    ctx = current_api_call_context()
    service = kwargs.pop("_service", "unknown")
    loan_application_id = kwargs.pop("_loan_application_id", None) or ctx.get("application_id")
    agent_run_id = kwargs.pop("_agent_run_id", None) or ctx.get("agent_run_id")
    pii_categories = list(kwargs.pop("_pii_categories", None) or ["unclassified"])

    model = kwargs.get("model", "")
    # See _SAMPLING_PARAMS_REMOVED_FAMILIES: adaptive-only models 400 on
    # temperature/top_p/top_k, so they never reach the API.
    if _sampling_params_removed(model):
        stripped = {p: kwargs.pop(p) for p in _REMOVED_SAMPLING_KWARGS if p in kwargs}
        if stripped:
            logger.debug("Stripped sampling params %s for adaptive-only model %s", stripped, model)

    # Provider drives BOTH the $0 cost accounting (_FREE_PROVIDERS) and the
    # APICallLog cross-border destination, so resolve it once up front.
    provider = getattr(client, "provider", "anthropic")

    budget = ApiBudgetGuard()
    # Authoritative atomic gate (M5): reserve a conservative worst-case before the
    # call so concurrent workers cannot collectively overshoot the daily cap.
    reserved = budget.reserve_budget(
        estimated_cost_cents=_estimate_reserve_cents(model, kwargs.get("max_tokens"), provider=provider),
        provider=provider,
    )

    audit = {
        "service": service,
        "provider": provider,
        "model": model,
        "loan_application_id": loan_application_id,
        "agent_run_id": agent_run_id,
        "pii_categories": pii_categories,
    }
    try:
        response = client.messages.create(**kwargs)
    except Exception as exc:
        # Only a transient failure says the provider is unhealthy; a 4xx is a
        # property of this request and must not block other callers.
        if is_transient_failure(exc):
            budget.record_failure(provider)
        # Release the reservation in full — the call never produced billable
        # tokens, so give back BOTH the reserved cost and the call slot.
        budget.record_call(
            input_tokens=0, output_tokens=0, model=model, reserved_cents=reserved, released=True, provider=provider
        )
        # A timeout or 5xx can arrive after the prompt was transmitted (the SDK
        # may even have sent it more than once): still a disclosure for APP 8.
        _log_api_call(kwargs, outcome="error", **audit)
        raise

    # Track cost from actual usage, reconciling the reservation to the true cost.
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
    budget.record_call(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
        reserved_cents=reserved,
        provider=provider,
    )
    budget.record_success(provider)

    # Log API call for PII cross-border audit (Privacy Act APP 8)
    _log_api_call(kwargs, outcome="success", input_tokens=input_tokens, output_tokens=output_tokens, **audit)

    return response
