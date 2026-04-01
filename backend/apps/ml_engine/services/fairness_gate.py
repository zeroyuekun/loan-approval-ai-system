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

logger = logging.getLogger(__name__)

DEFAULT_DIR_THRESHOLD = 0.80


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

    for attribute, metrics in fairness_metrics.items():
        dir_value = metrics.get("disparate_impact_ratio")
        if dir_value is None:
            # Undefined (e.g., single group) — skip
            results.append({
                "attribute": attribute,
                "dir": None,
                "passed": True,
                "note": "Undefined — single group or zero approvals",
            })
            continue

        passed = dir_value >= threshold
        results.append({
            "attribute": attribute,
            "dir": round(dir_value, 4),
            "passed": passed,
        })
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
