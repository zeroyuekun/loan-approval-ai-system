"""Single source of truth for the bias severe-violation boundary and the
policy applied when the bias check cannot run.

Both the decision gate (`core.py`) and the marketing gates (`marketing.py`,
`marketing_pipeline.py`) must treat the review threshold as INCLUSIVE: a score
*equal to* the review threshold is, by definition, at the "review" level and
must escalate/block — it must not fall through to the moderate-findings path.

For example, a deterministic marketing score of exactly 70 (prohibited 50 +
decline 20) must be blocked, not treated as merely "moderate". Centralising
the comparison here keeps the inclusive policy from drifting between gates.
"""

from __future__ import annotations

import logging

from django.conf import settings

from apps.agents.metrics import bias_check_unavailable_total

logger = logging.getLogger("agents.bias")

_FAILURE_MODES = ("block", "warn", "off")


def is_severe(score: float, review_threshold: float) -> bool:
    """Return True when `score` is at or above the severe-violation threshold.

    Inclusive bound (`>=`): a score equal to `review_threshold` is severe.
    """
    return score >= review_threshold


def bias_failure_mode() -> str:
    """Record a bias check that could not run and return the BIAS_FAILURE_MODE to apply.

    ``block`` withholds the email; ``warn`` and ``off`` let it through. An
    unknown value means ``block``. Every caller is a path that could not
    bias-check an email, so the outage is counted here, once per failed
    check, and the ``bias_check_unavailable`` alert covers all of them.
    """
    mode = str(getattr(settings, "BIAS_FAILURE_MODE", "block")).lower()
    if mode not in _FAILURE_MODES:
        logger.warning("Unknown BIAS_FAILURE_MODE=%r — defaulting to 'block'", mode)
        mode = "block"
    bias_check_unavailable_total.labels(mode=mode).inc()
    return mode
