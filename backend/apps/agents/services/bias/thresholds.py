"""Single source of truth for the bias severe-violation boundary.

Both the decision gate (`core.py`) and the marketing gates (`marketing.py`,
`marketing_pipeline.py`) must treat the review threshold as INCLUSIVE: a score
*equal to* the review threshold is, by definition, at the "review" level and
must escalate/block — it must not fall through to the moderate-findings path.

Before this helper, `core.py` used `>=` while `marketing.py` used `>` (M4),
so a deterministic marketing score of exactly 70 (prohibited 50 + decline 20)
was treated as merely "moderate" instead of blocked. Centralising the
comparison here makes the inclusive policy impossible to drift between gates.
"""

from __future__ import annotations


def is_severe(score: float, review_threshold: float) -> bool:
    """Return True when `score` is at or above the severe-violation threshold.

    Inclusive bound (`>=`): a score equal to `review_threshold` is severe.
    """
    return score >= review_threshold
