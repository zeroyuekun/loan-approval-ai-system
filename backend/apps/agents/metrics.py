"""Prometheus metrics for the agent orchestrator.

These histograms back the SLOs documented in `docs/slo.md`:

- `pipeline_e2e_seconds`   — decision-pipeline wall time (p95 < 30 s, p99 < 60 s)
- `bias_review_ttr_seconds` — human-review time-to-resolution for bias escalations

Keep this module import-light: it is pulled in by step_tracker + human_review_handler
on the hot path of every orchestrator run.
"""

from prometheus_client import Counter, Histogram

# Buckets tuned for the documented SLO: p95 30 s, p99 60 s.
# A leading tail (1-5 s) catches ultra-short happy paths (template-only,
# cache hit) that skip the Claude call.
pipeline_e2e_seconds = Histogram(
    "pipeline_e2e_seconds",
    "End-to-end loan pipeline wall time (submit → decision persisted)",
    labelnames=["status", "decision"],
    buckets=[1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0],
)

# `decision` is the outcome that was applied (approved/denied) after human review.
# Buckets span "same-shift turnaround" (30 min) to "multi-day backlog" (3 d).
bias_review_ttr_seconds = Histogram(
    "bias_review_ttr_seconds",
    "Time from bias escalation to human review resolution",
    labelnames=["decision"],
    buckets=[
        60.0,  # 1 min
        300.0,  # 5 min
        900.0,  # 15 min
        1800.0,  # 30 min
        3600.0,  # 1 hr
        14400.0,  # 4 hr
        43200.0,  # 12 hr
        86400.0,  # 1 day
        259200.0,  # 3 days
    ],
)

# Counter used by both `orchestrate()` and `resume_after_review()` so the
# escalation-rate SLO (< 15 % weekly) can be computed across both code paths.
bias_review_total = Counter(
    "bias_review_total",
    "Bias review decisions by outcome",
    labelnames=["outcome"],  # pass | escalated | ai_cleared | human_resolved
)
