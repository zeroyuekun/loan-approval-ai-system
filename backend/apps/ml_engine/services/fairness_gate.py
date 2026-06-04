"""Pre-deployment fairness gate for ML models.

Checks that a trained model's fairness metrics meet the EEOC four-fifths rule
(disparate impact ratio >= 0.80) across all protected attributes before
allowing it to go active.

The 80% rule originates from the EEOC Uniform Guidelines on Employee Selection
Procedures and is widely applied to lending (ECOA, CFPB guidance). If any
protected group's approval rate is less than 80% of the highest group's rate,
the model may be discriminatory and should not be deployed without review.

References:
    - EEOC Uniform Guidelines § 60-3.4(D)
    - CFPB Circular 2023-03
    - Zest AI: pre-deployment fairness testing
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_DIR_THRESHOLD = 0.80

# Minimum number of individuals in any protected group before we treat a
# None disparate_impact_ratio as a hard gate failure rather than "too small
# to assess".  Groups below this size are skipped (not enough data).
# Configurable via settings.FAIRNESS_MIN_GROUP_SIZE.
_MIN_GROUP_SIZE = lambda: getattr(settings, "FAIRNESS_MIN_GROUP_SIZE", 30)  # noqa: E731


def check_fairness_gate(
    fairness_metrics: dict,
    threshold: float = DEFAULT_DIR_THRESHOLD,
) -> dict:
    """Check whether a model passes the pre-deployment fairness gate.

    Args:
        fairness_metrics: Dict keyed by protected attribute name, each containing
            a 'disparate_impact_ratio' float (from MetricsService.compute_fairness_metrics).
        threshold: Minimum acceptable disparate impact ratio (default 0.80 per EEOC).

    Returns:
        {
            "passed": bool,
            "threshold": float,
            "results": [
                {"attribute": str, "dir": float, "passed": bool},
                ...
            ],
            "minimum_dir": float or None,
            "failing_attributes": [str, ...],
        }
    """
    results = []
    failing_attributes = []
    dir_values = []
    min_group_size = _MIN_GROUP_SIZE()

    for attribute, metrics in fairness_metrics.items():
        dir_value = metrics.get("disparate_impact_ratio")
        if dir_value is None:
            # DIR is None when max(approval_rates) == 0, i.e. zero approvals
            # across all groups for this attribute, OR when only one group exists.
            # Determine the total sample size across groups so we can decide
            # whether this is a "too small to assess" case or a genuine failure.
            groups = metrics.get("groups", {})
            group_count = sum(g.get("count", 0) for g in groups.values())

            if group_count < min_group_size:
                # Too few samples — cannot reliably assess DIR; skip silently.
                results.append(
                    {
                        "attribute": attribute,
                        "dir": None,
                        "passed": True,
                        "note": f"Skipped — only {group_count} samples (< {min_group_size} minimum)",
                    }
                )
                continue

            # Sufficient sample but DIR is still None → zero approvals in at
            # least one non-trivial group.  This is the worst possible disparate
            # impact and MUST fail the gate.
            logger.warning(
                "Fairness gate: attribute '%s' has None DIR with %d samples — "
                "zero approvals in at least one protected group (HARD FAIL)",
                attribute,
                group_count,
            )
            results.append(
                {
                    "attribute": attribute,
                    "dir": None,
                    "passed": False,
                    "note": "zero_approvals_in_protected_group",
                }
            )
            failing_attributes.append(attribute)
            continue

        passed = dir_value >= threshold
        results.append(
            {
                "attribute": attribute,
                "dir": round(dir_value, 4),
                "passed": passed,
            }
        )
        dir_values.append(dir_value)

        if not passed:
            failing_attributes.append(attribute)

    minimum_dir = round(min(dir_values), 4) if dir_values else None
    gate_passed = len(failing_attributes) == 0

    if gate_passed:
        logger.info(
            "Fairness gate PASSED: all attributes meet %.0f%% threshold (min DIR=%.4f)",
            threshold * 100,
            minimum_dir or 0,
        )
    else:
        logger.warning(
            "Fairness gate FAILED: attributes %s below %.0f%% threshold (min DIR=%.4f)",
            failing_attributes,
            threshold * 100,
            minimum_dir or 0,
        )

    return {
        "passed": gate_passed,
        "threshold": threshold,
        "results": results,
        "minimum_dir": minimum_dir,
        "failing_attributes": failing_attributes,
    }
