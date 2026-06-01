"""Automated decision-making (ADM) disclosure register.

Implements the transparency obligations of the Privacy Act 1988 ADM reforms
(APP 1.7-1.9, commencing 10 Dec 2026) and the Voluntary AI Safety Standard
"transparency" + "contestability" guardrails: a loan applicant is told whether
their decision was made solely by automated means or with human involvement,
what kinds of information were used, and that they may request a human review.

Kept as code (not DB) — these are product/legal facts about the pipeline, not
per-tenant config. Surfaced three ways: in the customer decision payload (via
DecisionExplanation), in the DenialExplanationPanel, and on the /rights page.
"""

from __future__ import annotations

REVIEW_REQUEST_PATH = "/api/v1/loans/decision-reviews/"

_INFO_USED = [
    "Income and employment details you provided",
    "Credit report and repayment history (Equifax/Illion, CCR)",
    "Existing debts, expenses and serviceability under an interest-rate buffer",
    "Loan amount, term and purpose",
]

ADM_REGISTER: dict[str, dict] = {
    "automated_approve": {
        "mode": "solely_automated",
        "summary": "Approved by our automated credit-decision model.",
        "info_used": _INFO_USED,
        "human_review_right": True,
    },
    "automated_decline": {
        "mode": "solely_automated",
        "summary": "Declined by our automated credit-decision model.",
        "info_used": _INFO_USED,
        "human_review_right": True,
    },
    "escalated_review": {
        "mode": "assisted",
        "summary": "Assessed by our automated model and reviewed by a lending officer.",
        "info_used": _INFO_USED,
        "human_review_right": True,
    },
    "human_override": {
        "mode": "human",
        "summary": "Reviewed and decided by a lending officer.",
        "info_used": _INFO_USED,
        "human_review_right": True,
    },
}


def resolve_adm_disclosure(
    *, decision: str, requires_human_review: bool = False, human_involvement: str = "none"
) -> dict:
    """Return the ADM disclosure block for a single decision.

    `human_involvement` (persisted on LoanDecision) is authoritative:
    - "overridden" -> a lending officer overrode the model ("human")
    - "assisted"   -> model assessed + human reviewed ("assisted")
    - "none"       -> solely automated
    `requires_human_review` is the legacy live-prediction signal kept for
    backward compatibility; it maps to "assisted".
    """
    if human_involvement == "overridden":
        entry = ADM_REGISTER["human_override"]
    elif human_involvement == "assisted" or requires_human_review:
        entry = ADM_REGISTER["escalated_review"]
    elif decision == "approved":
        entry = ADM_REGISTER["automated_approve"]
    else:
        entry = ADM_REGISTER["automated_decline"]

    return {
        "mode": entry["mode"],
        "summary": entry["summary"],
        "info_used": list(entry["info_used"]),
        "human_review_right": entry["human_review_right"],
        "review_request_path": REVIEW_REQUEST_PATH,
    }
