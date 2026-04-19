"""Prometheus metrics for the email-generation pipeline.

Backs the `email_generation_total` SLO documented in `docs/slo.md`
(98 % success rate over 30-day window).

Labels:
- `decision` — approved | denied
- `source`   — claude_api | template_fallback
- `status`   — success | guardrail_fail | api_error

`success` requires both Claude (or template) returning a body AND every
non-warning guardrail check passing. Guardrail-fail counts emails that
generated but tripped a blocker (e.g. regulatory phrase, hallucinated
number) and thus did not reach the customer. `api_error` covers Claude
API failures that end up falling back to the template path.
"""

from prometheus_client import Counter

email_generation_total = Counter(
    "email_generation_total",
    "Email generation outcomes by decision, source, and status",
    labelnames=["decision", "source", "status"],
)
