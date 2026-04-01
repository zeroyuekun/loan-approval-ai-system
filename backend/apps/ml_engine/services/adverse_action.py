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
from datetime import UTC, datetime

from apps.ml_engine.services.reason_codes import (
    generate_adverse_action_reasons,
    generate_reapplication_guidance,
)

logger = logging.getLogger(__name__)

US_RIGHT_TO_REQUEST_TEXT = (
    "Under the Equal Credit Opportunity Act (ECOA), you have the right to "
    "request a copy of the appraisal or valuation used in connection with "
    "your application within 30 days of this notice. You also have the right "
    "to know the specific reasons for this decision."
)

AU_RIGHT_TO_REQUEST_TEXT = (
    "Under the Privacy Act 1988, you have the right to request access to "
    "the personal information we hold about you and the reasons for this "
    "decision. You may also request a review of this decision by contacting "
    "us directly or lodging a complaint with AFCA."
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

# --- US jurisdiction: FCRA / ECOA required disclosures ---

FCRA_DISCLOSURE_TEXT = (
    "This decision was based in whole or in part on information obtained from "
    "a consumer reporting agency. You have the right to obtain a free copy of "
    "your credit report from the agency listed below within 60 days of this "
    "notice, and to dispute the accuracy or completeness of any information "
    "contained therein. The consumer reporting agency did not make the credit "
    "decision and is unable to provide the specific reasons for it."
)

ECOA_ANTIDISCRIMINATION_NOTICE = (
    "The Federal Equal Credit Opportunity Act prohibits creditors from "
    "discriminating against credit applicants on the basis of race, color, "
    "religion, national origin, sex, marital status, age (provided the "
    "applicant has the capacity to enter into a binding contract), because "
    "all or part of the applicant's income derives from any public assistance "
    "program, or because the applicant has in good faith exercised any right "
    "under the Consumer Credit Protection Act."
)

US_REGULATOR_CONTACT = {
    "name": "Consumer Financial Protection Bureau (CFPB)",
    "address": "1700 G Street NW, Washington, DC 20552",
    "phone": "(855) 411-2372",
    "website": "www.consumerfinance.gov",
}

US_CREDIT_BUREAU = {
    "name": "Equifax",
    "address": "P.O. Box 740241, Atlanta, GA 30374-0241",
    "phone": "(800) 685-1111",
    "website": "www.equifax.com",
}

# --- Australian jurisdiction ---

AU_CREDIT_BUREAU = {
    "name": "Equifax Australia",
    "address": "GPO Box 964, North Sydney NSW 2059",
    "phone": "13 83 32",
    "website": "www.equifax.com.au",
}

AU_REGULATOR_CONTACT = {
    "name": "Australian Securities and Investments Commission (ASIC)",
    "phone": "1300 300 630",
    "website": "www.asic.gov.au",
}


def generate_adverse_action_notice(
    application,
    prediction_result: dict,
    max_reasons: int = 4,
    jurisdiction: str = "AU",
) -> dict:
    """Generate a formal adverse action notice for a denied application.

    Args:
        application: LoanApplication instance
        prediction_result: Dict from ModelPredictor.predict() containing
            shap_values, probability, model_version, risk_grade, counterfactuals
        max_reasons: Maximum principal reasons to include (ECOA allows up to 4)
        jurisdiction: "AU" (Australia) or "US" (United States) — controls
            which regulatory disclosures are included

    Returns dict with:
        - notice_type, applicant_name, application_id, date, decision
        - principal_reasons: list of {code, reason, feature}
        - model_version, risk_grade
        - right_to_request (ECOA 30-day right)
        - complaint_info (AFCA for AU)
        - shap_stability_note
        - credit_score_disclosure (score used, range, key factors)
        - reapplication_guidance (improvement targets, timeline)
        - Jurisdiction-specific:
          AU: au_regulator_contact, au_credit_bureau
          US: fcra_disclosure, ecoa_antidiscrimination_notice,
              us_regulator_contact, us_credit_bureau
    """
    shap_values = prediction_result.get("shap_values", {})
    model_version = prediction_result.get("model_version", "unknown")
    risk_grade = prediction_result.get("risk_grade", "unknown")
    counterfactuals = prediction_result.get("counterfactuals", [])

    # Delegate to reason_codes for the heavy lifting
    raw_reasons = generate_adverse_action_reasons(
        shap_values=shap_values,
        prediction="denied",
        max_reasons=max_reasons,
    )

    # Strip raw SHAP contribution values — consumer-facing only
    principal_reasons = [{"code": r["code"], "reason": r["reason"], "feature": r["feature"]} for r in raw_reasons]

    # Build applicant name from the application's user relation
    applicant_name = _get_applicant_name(application)

    # Credit score disclosure — required under both ECOA (US) and good practice (AU)
    credit_score = getattr(application, "credit_score", None)
    credit_score_disclosure = {
        "score_used": credit_score,
        "score_range": {"min": 0, "max": 1200} if jurisdiction == "AU" else {"min": 300, "max": 850},
        "score_source": "Equifax Australia" if jurisdiction == "AU" else "Equifax",
        "key_factors": [r["reason"] for r in principal_reasons[:4]],
    }

    # Reapplication guidance from counterfactuals
    reapplication = generate_reapplication_guidance(counterfactuals, raw_reasons)

    notice = {
        "notice_type": "adverse_action",
        "applicant_name": applicant_name,
        "application_id": str(getattr(application, "id", "")),
        "date": datetime.now(UTC).isoformat(),
        "decision": "denied",
        "principal_reasons": principal_reasons,
        "model_version": str(model_version),
        "risk_grade": str(risk_grade),
        "right_to_request": US_RIGHT_TO_REQUEST_TEXT if jurisdiction == "US" else AU_RIGHT_TO_REQUEST_TEXT,
        "complaint_info": AFCA_COMPLAINT_TEXT,
        "shap_stability_note": SHAP_STABILITY_NOTE,
        "credit_score_disclosure": credit_score_disclosure,
        "reapplication_guidance": reapplication,
    }

    # Jurisdiction-specific disclosures
    if jurisdiction == "US":
        notice["fcra_disclosure"] = FCRA_DISCLOSURE_TEXT
        notice["ecoa_antidiscrimination_notice"] = ECOA_ANTIDISCRIMINATION_NOTICE
        notice["us_regulator_contact"] = US_REGULATOR_CONTACT
        notice["us_credit_bureau"] = US_CREDIT_BUREAU
    else:  # AU default
        notice["au_regulator_contact"] = AU_REGULATOR_CONTACT
        notice["au_credit_bureau"] = AU_CREDIT_BUREAU

    logger.info(
        "Generated adverse action notice for application %s (%s jurisdiction) with %d reasons",
        notice["application_id"],
        jurisdiction,
        len(principal_reasons),
    )

    return notice


def _get_applicant_name(application) -> str:
    """Extract applicant name from a LoanApplication instance."""
    user = getattr(application, "applicant", None)
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
        dev_date = created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
    else:
        dev_date = None

    # Validation dates — last is created_at, next is +12 months (annual cycle)
    last_validation = dev_date
    next_validation = None
    if created_at and hasattr(created_at, "replace"):
        try:
            next_validation = created_at.replace(year=created_at.year + 1).isoformat()
        except ValueError:
            # Leap year edge case (Feb 29 → Feb 28)
            next_validation = created_at.replace(year=created_at.year + 1, day=28).isoformat()

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
