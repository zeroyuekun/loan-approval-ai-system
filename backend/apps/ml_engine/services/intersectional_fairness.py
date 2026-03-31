"""Intersectional fairness analysis — tests fairness across combined protected attributes.

Single-axis fairness testing is insufficient. Kim et al. (2023) demonstrated that
compliance along individual axes can mask amplified disparities at intersections.

References:
    - Kim et al. (2023) "Fair Models in Credit: Intersectional Discrimination"
      arXiv:2308.02680
    - Kleinberg, Mullainathan, Raghavan (2016) "Inherent Trade-Offs in the Fair
      Determination of Risk Scores" arXiv:1609.05807
    - EEOC Uniform Guidelines 29 CFR 1607.4 (four-fifths rule)
"""

import logging
from itertools import combinations

import numpy as np

logger = logging.getLogger(__name__)

# The 80% rule is explicitly "not intended as a legal definition" per the EEOC
# (29 CFR 1607.4) -- it is a practical screening threshold, not a guarantee.
DISPARATE_IMPACT_THRESHOLD = 0.80


def compute_intersectional_fairness(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_prob: np.ndarray,
    protected_attributes: dict[str, np.ndarray],
    min_group_size: int = 30,
) -> dict:
    """Compute fairness metrics across all pairwise intersections of protected attributes.

    Args:
        y_true: Actual binary outcomes (1=approved, 0=denied)
        y_pred: Predicted binary outcomes
        y_prob: Predicted probabilities
        protected_attributes: Dict mapping attribute name to array of group labels
            e.g. {'employment_type': [...], 'applicant_type': [...], 'state': [...]}
        min_group_size: Minimum subgroup size to include (avoids unreliable small samples)

    Returns dict with:
        - single_axis: dict of per-attribute fairness
        - intersectional: dict of pairwise intersection fairness
        - worst_subgroup: the subgroup with lowest approval rate (or None)
        - amplification_detected: bool -- True if any intersection is worse than single-axis
        - summary: human-readable summary
    """
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    y_prob = np.asarray(y_prob)

    n = len(y_true)

    # Graceful handling of empty / degenerate input
    if n == 0 or len(protected_attributes) == 0:
        return {
            "single_axis": {},
            "intersectional": {},
            "worst_subgroup": None,
            "amplification_detected": False,
            "summary": "No data or no protected attributes provided.",
        }

    # Convert all attribute arrays once
    attrs = {name: np.asarray(values) for name, values in protected_attributes.items()}

    # ------------------------------------------------------------------
    # Step 1: Single-axis fairness per attribute
    # ------------------------------------------------------------------
    single_axis = {}
    worst_single_axis_di = 1.0  # track the worst (lowest) single-axis DI

    for attr_name, labels in attrs.items():
        result = _compute_group_fairness(y_pred, labels, min_group_size)
        single_axis[attr_name] = result
        if result["disparate_impact_ratio"] is not None:
            worst_single_axis_di = min(worst_single_axis_di, result["disparate_impact_ratio"])

    # ------------------------------------------------------------------
    # Step 2: Pairwise intersectional fairness
    # ------------------------------------------------------------------
    intersectional = {}
    worst_subgroup = None
    worst_subgroup_rate = 1.0
    worst_intersectional_di = 1.0

    attr_names = list(attrs.keys())

    for attr_a, attr_b in combinations(attr_names, 2):
        labels_a = attrs[attr_a]
        labels_b = attrs[attr_b]

        # Build intersection labels: "value_a + value_b"
        intersection_labels = np.array([f"{a} + {b}" for a, b in zip(labels_a, labels_b, strict=False)])

        pair_key = f"{attr_a} x {attr_b}"
        result = _compute_group_fairness(y_pred, intersection_labels, min_group_size)
        intersectional[pair_key] = result

        if result["disparate_impact_ratio"] is not None:
            worst_intersectional_di = min(worst_intersectional_di, result["disparate_impact_ratio"])

        # Track worst subgroup across all intersections
        for group_name, group_info in result["groups"].items():
            rate = group_info["approval_rate"]
            if rate < worst_subgroup_rate:
                worst_subgroup_rate = rate
                worst_subgroup = {
                    "intersection": pair_key,
                    "subgroup": group_name,
                    "approval_rate": round(rate, 4),
                    "count": group_info["count"],
                }

    # ------------------------------------------------------------------
    # Step 3: Check for amplification
    # ------------------------------------------------------------------
    amplification_detected = worst_intersectional_di < worst_single_axis_di

    # ------------------------------------------------------------------
    # Step 4: Build summary
    # ------------------------------------------------------------------
    summary_parts = []
    summary_parts.append(
        f"Analysed {len(single_axis)} single-axis attributes and {len(intersectional)} pairwise intersections."
    )
    summary_parts.append(f"Worst single-axis disparate impact: {worst_single_axis_di:.4f}.")
    if intersectional:
        summary_parts.append(f"Worst intersectional disparate impact: {worst_intersectional_di:.4f}.")
    if amplification_detected:
        summary_parts.append(
            "AMPLIFICATION DETECTED: intersectional disparity is worse than "
            "any single-axis disparity. See Kim et al. (2023) arXiv:2308.02680."
        )
    else:
        summary_parts.append("No intersectional amplification detected.")

    return {
        "single_axis": single_axis,
        "intersectional": intersectional,
        "worst_subgroup": worst_subgroup,
        "amplification_detected": amplification_detected,
        "summary": " ".join(summary_parts),
    }


def _compute_group_fairness(
    y_pred: np.ndarray,
    group_labels: np.ndarray,
    min_group_size: int,
) -> dict:
    """Compute approval-rate fairness for a single set of group labels.

    Groups smaller than min_group_size are excluded to avoid unreliable estimates.

    Returns dict with:
        - groups: {group_name: {count, approval_rate}}
        - disparate_impact_ratio: min/max approval rate (or None if < 2 groups)
        - passes_80_percent_rule: bool (or None)
    """
    unique_groups = np.unique(group_labels)
    groups = {}
    approval_rates = []

    for group in unique_groups:
        mask = group_labels == group
        count = int(mask.sum())
        if count < min_group_size:
            continue
        rate = float(y_pred[mask].mean())
        groups[str(group)] = {
            "count": count,
            "approval_rate": round(rate, 4),
        }
        approval_rates.append(rate)

    if len(approval_rates) >= 2 and max(approval_rates) > 0:
        di_ratio = min(approval_rates) / max(approval_rates)
    else:
        di_ratio = None

    passes = di_ratio >= DISPARATE_IMPACT_THRESHOLD if di_ratio is not None else None

    return {
        "groups": groups,
        "disparate_impact_ratio": round(di_ratio, 4) if di_ratio is not None else None,
        "passes_80_percent_rule": passes,
    }
