"""Prometheus metrics for the email-generation pipeline.

Backs the `email_generation_total` SLO documented in `docs/slo.md`
(98 % success rate over 30-day window).

Labels on `email_generation_total`:
- `decision` — approved | denied
- `source`   — claude_api | template_fallback
- `status`   — success | guardrail_fail | api_error

`success` requires both Claude (or template) returning a body AND every
non-warning guardrail check passing. Guardrail-fail counts emails that
generated but tripped a blocker (e.g. regulatory phrase, hallucinated
number) and thus did not reach the customer. `api_error` covers Claude
API failures that end up falling back to the template path.

`email_llm_input_tokens_total` exposes the three input-token buckets
Anthropic reports when prompt caching is active. Cache hit ratio in
production is
``sum(cache_read) / sum(standard) + sum(cache_create) + sum(cache_read)``
— without this metric you can't see whether the cache is actually paying
off after `EMAIL_GENERATION_MODE` is flipped to `api`.
"""

from prometheus_client import Counter

email_generation_total = Counter(
    "email_generation_total",
    "Email generation outcomes by decision, source, and status",
    labelnames=["decision", "source", "status"],
)

email_llm_input_tokens_total = Counter(
    "email_llm_input_tokens_total",
    "Claude API input tokens by category — standard, cache_create (write), cache_read (hit)",
    labelnames=["decision", "type"],
)
