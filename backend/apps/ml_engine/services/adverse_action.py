"""Formal adverse action notice generator for denied loan applications.

Wraps the existing reason_codes module to produce regulatory-compliant notices
per CFPB Circular 2022-03 (ECOA/Regulation B) and NCCP Act s133.

The CFPB requires "specific and accurate reasons" for adverse action but is
method-agnostic — it does not mandate SHAP or any specific technique.

SHAP stability caveat: Mid-ranked features may show ranking instability across
model runs (arXiv:2508.01851). Top and bottom features are stable. We report
the top max_reasons features which have the most stable attributions.

References:
    - CFPB Circular 2022-03: consumerfinance.gov/compliance/circulars/circular-2022-03
    - NCCP Act 2009 s133: legislation.gov.au
    - SHAP stability: arXiv:2508.01851
"""

import logging
from datetime import datetime, timezone

from apps.ml_engine.services.reason_codes import generate_adverse_action_reasons

logger = logging.getLogger(__name__)

RIGHT_TO_REQUEST_TEXT = (
    "Under the Equal Credit Opportunity Act (ECOA), you have the right to "
    "request a copy of the appraisal or valuation used in connection with "
    "your application within 30 days of this notice. You also have the right "
    "to know the specific reasons for this decision."
)

AFCA_COMPLAINT_TEXT = (
    "If you believe this decision is incorrect, you may lodge a complaint "
    "with the Australian Financial Complaints Authority (AFCA). "
    "Online: www.afca.org.au | Phone: 1800 931 678 | "
    "Email: info@afca.org.au | GPO Box 3, Melbourne VIC 3001."
)

SHAP_STABILITY_NOTE = (
    "Reason rankings are derived from feature attribution analysis. "
    "Top contributing factors are stable across model evaluations; "
    "mid-ranked factors may vary between assessments (arXiv:2508.01851)."
)


def generate_adverse_action_notice(
    application,
    prediction_result: dict,
    max_reasons: int = 4,
) -> dict:
    """Generate a formal adverse action notice for a denied application.

    Args:
        application: LoanApplication instance
        prediction_result: Dict from ModelPredictor.predict() containing
            shap_values, probability, model_version, risk_grade
        max_reasons: Maximum principal reasons to include (ECOA allows up to 4)

    Returns dict with:
        - notice_type: 'adverse_action'
        - applicant_name: str
        - application_id: str
        - date: ISO timestamp
        - decision: 'denied'
        - principal_reasons: list of {code, reason, feature} (no raw
          contribution values — those are internal)
        - model_version: str
        - risk_grade: str
        - right_to_request: str (ECOA 30-day right)
        - complaint_info: str (AFCA details for AU)
        - shap_stability_note: str (caveat about mid-rank instability)
    """
    shap_values = prediction_result.get("shap_values", {})
    model_version = prediction_result.get("model_version", "unknown")
    risk_grade = prediction_result.get("risk_grade", "unknown")

    # Delegate to reason_codes for the heavy lifting
    raw_reasons = generate_adverse_action_reasons(
        shap_values=shap_values,
        prediction="denied",
        max_reasons=max_reasons,
    )

    # Strip raw SHAP contribution values — consumer-facing only
    principal_reasons = [
        {"code": r["code"], "reason": r["reason"], "feature": r["feature"]}
        for r in raw_reasons
    ]

    # Build applicant name from the application's user relation
    applicant_name = _get_applicant_name(application)

    notice = {
        "notice_type": "adverse_action",
        "applicant_name": applicant_name,
        "application_id": str(getattr(application, "id", "")),
        "date": datetime.now(timezone.utc).isoformat(),
        "decision": "denied",
        "principal_reasons": principal_reasons,
        "model_version": str(model_version),
        "risk_grade": str(risk_grade),
        "right_to_request": RIGHT_TO_REQUEST_TEXT,
        "complaint_info": AFCA_COMPLAINT_TEXT,
        "shap_stability_note": SHAP_STABILITY_NOTE,
    }

    logger.info(
        "Generated adverse action notice for application %s with %d reasons",
        notice["application_id"],
        len(principal_reasons),
    )

    return notice


def _get_applicant_name(application) -> str:
    """Extract applicant name from a LoanApplication instance."""
    user = getattr(application, "user", None)
    if user is None:
        return "Applicant"
    first = getattr(user, "first_name", "") or ""
    last = getattr(user, "last_name", "") or ""
    full = f"{first} {last}".strip()
    return full if full else getattr(user, "email", "Applicant")


def generate_model_inventory_entry(model_version) -> dict:
    """Generate SR 11-7 compliant model inventory entry.

    SR 11-7 (Federal Reserve, 2011) requires organizations to maintain an
    inventory of models "implemented for use, under development for
    implementation, or recently retired."

    Args:
        model_version: ModelVersion instance

    Returns dict with SR 11-7 required fields:
        - model_name, model_id, version
        - algorithm, risk_classification
        - owner
        - purpose, status
        - development_date, last_validation_date, next_validation_date
        - performance_metrics
        - data_sources, known_limitations
        - third_party_dependencies, regulatory_references
    """
    is_active = getattr(model_version, "is_active", False)
    algorithm = getattr(model_version, "algorithm", "unknown")
    version = getattr(model_version, "version", "unknown")
    created_at = getattr(model_version, "created_at", None)

    # Determine status
    if is_active:
        status = "active"
    else:
        # If traffic_percentage > 0 it may be a challenger; otherwise inactive
        traffic = getattr(model_version, "traffic_percentage", 0) or 0
        status = "inactive" if traffic == 0 else "challenger"

    # Development date
    if created_at is not None:
        dev_date = (
            created_at.isoformat()
            if hasattr(created_at, "isoformat")
            else str(created_at)
        )
    else:
        dev_date = None

    # Validation dates — last is created_at, next is +12 months (annual cycle)
    last_validation = dev_date
    next_validation = None
    if created_at and hasattr(created_at, "replace"):
        try:
            next_validation = created_at.replace(
                year=created_at.year + 1
            ).isoformat()
        except ValueError:
            # Leap year edge case (Feb 29 → Feb 28)
            next_validation = created_at.replace(
                year=created_at.year + 1, day=28
            ).isoformat()

    # Performance metrics — pull from model fields
    performance_metrics = {
        "auc": getattr(model_version, "auc_roc", None),
        "gini": getattr(model_version, "gini_coefficient", None),
        "ks": getattr(model_version, "ks_statistic", None),
        "f1": getattr(model_version, "f1_score", None),
        "accuracy": getattr(model_version, "accuracy", None),
        "brier": getattr(model_version, "brier_score", None),
        "ece": getattr(model_version, "ece", None),
    }

    return {
        "model_name": f"Loan Approval Model — {algorithm}",
        "model_id": str(getattr(model_version, "id", "")),
        "version": str(version),
        "algorithm": str(algorithm),
        "risk_classification": "high",  # Consumer credit = high risk per SR 11-7
        "owner": "ML Engineering Team",
        "purpose": "Consumer credit decisioning",
        "status": status,
        "development_date": dev_date,
        "last_validation_date": last_validation,
        "next_validation_date": next_validation,
        "performance_metrics": performance_metrics,
        "data_sources": [
            "Application form data",
            "Credit bureau (Equifax/Illion)",
            "Open banking transaction data",
        ],
        "known_limitations": [
            "Mid-ranked SHAP feature attributions may be unstable (arXiv:2508.01851)",
            "Model trained on Australian lending data — not validated for other jurisdictions",
            "Does not account for macroeconomic regime changes post-training",
        ],
        "third_party_dependencies": [
            "scikit-learn",
            "XGBoost",
            "SHAP",
        ],
        "regulatory_references": [
            "SR 11-7 (Federal Reserve, 2011) — Model Risk Management",
            "CFPB Circular 2022-03 — Adverse Action under ECOA",
            "NCCP Act 2009 (Cth) — Responsible lending obligations",
            "ASIC RG 209 — Credit licensing: Responsible lending conduct",
        ],
    }
