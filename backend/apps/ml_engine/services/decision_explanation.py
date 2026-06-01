"""Single source of truth for the customer-facing decision explanation.

Consolidates the previously-duplicated denial-reason ranking that lived in
`loans.serializers.CustomerLoanDecisionSerializer`, `agents...human_review_handler`,
and (prose-only) `email_generator._format_denial_reasons`. This module owns the
ranking; renderers (structured reason codes for the UI, ADM disclosure) consume it.

Pure functions — no Django model writes — so they unit-test without a DB and can
run against either a saved `LoanDecision` or a live `prediction_result` dict.
"""

from __future__ import annotations

from apps.ml_engine.services.adm_disclosure import resolve_adm_disclosure
from apps.ml_engine.services.reason_codes import (
    generate_adverse_action_reasons,
    generate_reapplication_guidance,
)


def ranked_denial_drivers(*, shap_values: dict, feature_importances: dict, max_n: int = 4) -> list[tuple[str, float]]:
    """Canonical ordered list of (feature, magnitude) that drove a denial.

    Prefers per-applicant negative SHAP (most-negative first). Falls back to
    global feature importances (descending) when no negative SHAP is present.
    This is the ONE ranking all customer-facing surfaces start from.
    """
    if shap_values:
        negative = [(name, val) for name, val in shap_values.items() if val < 0]
        if negative:
            negative.sort(key=lambda x: x[1])  # most negative first
            return [(name, abs(val)) for name, val in negative[:max_n]]
    ordered = sorted(feature_importances.items(), key=lambda x: x[1], reverse=True)
    return [(name, float(val)) for name, val in ordered[:max_n]]


def build_explanation_payload(
    *,
    decision: str,
    shap_values: dict | None,
    feature_importances: dict | None,
    counterfactual_results: list | None,
    requires_human_review: bool,
    human_involvement: str = "none",
) -> dict:
    """Build the customer-facing decision payload (the UI/serializer contract)."""
    shap_values = shap_values or {}
    feature_importances = feature_importances or {}
    counterfactual_results = counterfactual_results or []

    denial_reasons = generate_adverse_action_reasons(shap_values, decision)

    if decision == "denied":
        counterfactuals = counterfactual_results
        reapplication_guidance = generate_reapplication_guidance(counterfactual_results, denial_reasons)
    else:
        counterfactuals = []
        reapplication_guidance = None

    return {
        "decision": decision,
        "denial_reasons": denial_reasons,
        "counterfactuals": counterfactuals,
        "reapplication_guidance": reapplication_guidance,
        "adm_disclosure": resolve_adm_disclosure(
            decision=decision,
            requires_human_review=requires_human_review,
            human_involvement=human_involvement,
        ),
    }


def build_explanation_from_decision(loan_decision) -> dict:
    """Convenience wrapper for a saved `LoanDecision` instance.

    Human involvement is read from the persisted `human_involvement` field
    (set at escalation-resolve / officer-override time) — NOT inferred from
    the transient `application.status`, which has already moved on by the
    time the customer views the decision.
    """
    involvement = getattr(loan_decision, "human_involvement", "none")
    return build_explanation_payload(
        decision=loan_decision.decision,
        shap_values=loan_decision.shap_values or {},
        feature_importances=loan_decision.feature_importances or {},
        counterfactual_results=loan_decision.counterfactual_results or [],
        requires_human_review=(involvement != "none"),
        human_involvement=involvement,
    )
