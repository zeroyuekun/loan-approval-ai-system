"""Business-facing lending metrics for the dashboard.

Answers two questions a credit team asks of a decision system:

* Why are applications declined?  (top decline reasons)
* How much does a person touch each decision?  (automated vs reviewed vs changed)

Decline reasons follow the decision email's rule: a lending-rule decline is
reported as that rule (``decline_rule_codes``), otherwise the model's regulatory
reason codes (``generate_adverse_action_reasons``) are used. Labels are written
for staff, not customers.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from apps.ml_engine.services.scoring.credit_policy import POLICY_RULES
from apps.ml_engine.services.scoring.decision_assembly import (
    POLICY_DECLINE_PREFIX,
    PRICING_TIER_DECLINE,
    decline_rule_codes,
)
from apps.ml_engine.services.scoring.reason_codes import generate_adverse_action_reasons

from ..models import LoanDecision

DECLINE_WINDOW_DAYS = 90

_RULE_LABELS = {
    PRICING_TIER_DECLINE: "Risk too high to offer a rate",
    **{f"{POLICY_DECLINE_PREFIX}{r.code}": r.description.removesuffix(" — decline") for r in POLICY_RULES},
}


def _decline_reasons(shap_values, waterfall) -> set[tuple[str, str]]:
    rules = decline_rule_codes(waterfall)
    if rules:
        return {(code, _RULE_LABELS.get(code, "Failed a lending policy rule")) for code in rules}
    return {(r["code"], r["reason"]) for r in generate_adverse_action_reasons(shap_values or {}, "denied")}


def top_decline_reasons(limit: int = 5) -> dict:
    """Most common reasons across declines in the last ``DECLINE_WINDOW_DAYS`` days.

    Each reason counts once per application, so ``share`` reads as "X% of
    declines cited this reason"; shares can sum past 100%.
    """
    since = timezone.now() - timedelta(days=DECLINE_WINDOW_DAYS)
    rows = LoanDecision.objects.filter(decision="denied", created_at__gte=since).values_list(
        "shap_values", "decision_waterfall"
    )
    counts: Counter = Counter()
    total = 0
    for shap_values, waterfall in rows.iterator():
        total += 1
        counts.update(_decline_reasons(shap_values, waterfall))
    return {
        "total_declines": total,
        "window_days": DECLINE_WINDOW_DAYS,
        "reasons": [
            {"code": code, "reason": label, "count": n, "share": round(n / total * 100, 1)}
            for (code, label), n in counts.most_common(limit)
        ],
    }


def decision_handling() -> dict:
    """How many decisions were fully automated, reviewed by staff, or changed by staff."""
    involvement = LoanDecision.HumanInvolvement
    return LoanDecision.objects.aggregate(
        total=Count("id"),
        automated=Count("id", filter=Q(human_involvement=involvement.NONE)),
        reviewed=Count("id", filter=Q(human_involvement=involvement.ASSISTED)),
        overridden=Count("id", filter=Q(human_involvement=involvement.OVERRIDDEN)),
    )
