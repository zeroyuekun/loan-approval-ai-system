"""Outcome tracking service -- compares model predictions to actual outcomes.

Required by SR 11-7 (Federal Reserve, 2011) as one of three model validation
pillars: "outcomes analysis" comparing model estimates to actual results.

References:
    - SR 11-7: federalreserve.gov/supervisionreg/srletters/sr1107.htm
    - APRA CPG 235: data integrity and model performance monitoring
"""
import logging
from collections import defaultdict

from django.db.models import Count, Q
from django.db.models.functions import TruncMonth

from apps.loans.models import LoanApplication, LoanDecision

logger = logging.getLogger(__name__)

# Outcomes classified as "bad" for binary comparison
BAD_OUTCOMES = frozenset({"default", "arrears_90"})


def _is_bad_outcome(outcome: str) -> bool:
    """Map granular outcome to binary bad/good."""
    return outcome in BAD_OUTCOMES


def compute_outcome_analysis(days=90):
    """Compare predicted outcomes to actual outcomes for applications with known results.

    Returns dict with:
    - total_with_outcomes: int
    - accuracy: float (predicted default matched actual default)
    - confusion_matrix: dict with tp, fp, tn, fn counts
    - accuracy_by_risk_grade: dict mapping grade -> accuracy
    - actual_default_rate: float
    - predicted_default_rate: float
    - calibration_gap: float (predicted - actual default rate)
    - outcome_breakdown: dict mapping outcome type -> count
    """
    # Fetch applications that have both a decision and an actual outcome
    apps = (
        LoanApplication.objects.filter(
            actual_outcome__isnull=False,
            decision__isnull=False,
        )
        .select_related("decision")
    )

    total = apps.count()

    if total == 0:
        return {
            "total_with_outcomes": 0,
            "accuracy": 0.0,
            "confusion_matrix": {"tp": 0, "fp": 0, "tn": 0, "fn": 0},
            "accuracy_by_risk_grade": {},
            "actual_default_rate": 0.0,
            "predicted_default_rate": 0.0,
            "calibration_gap": 0.0,
            "outcome_breakdown": {},
        }

    tp = fp = tn = fn = 0
    grade_correct = defaultdict(int)
    grade_total = defaultdict(int)
    outcome_counts = defaultdict(int)

    for app in apps.iterator():
        actual_bad = _is_bad_outcome(app.actual_outcome)
        # 'denied' means the model predicted the applicant was risky (predicted bad)
        predicted_bad = app.decision.decision == "denied"
        risk_grade = app.decision.risk_grade or "UNKNOWN"

        outcome_counts[app.actual_outcome] += 1

        correct = actual_bad == predicted_bad
        if correct:
            grade_correct[risk_grade] += 1

        grade_total[risk_grade] += 1

        if predicted_bad and actual_bad:
            tp += 1
        elif predicted_bad and not actual_bad:
            fp += 1
        elif not predicted_bad and not actual_bad:
            tn += 1
        else:
            fn += 1

    accuracy = (tp + tn) / total if total else 0.0
    actual_default_rate = (tp + fn) / total if total else 0.0
    predicted_default_rate = (tp + fp) / total if total else 0.0
    calibration_gap = predicted_default_rate - actual_default_rate

    accuracy_by_risk_grade = {}
    for grade in grade_total:
        g_total = grade_total[grade]
        accuracy_by_risk_grade[grade] = (
            grade_correct[grade] / g_total if g_total else 0.0
        )

    return {
        "total_with_outcomes": total,
        "accuracy": round(accuracy, 4),
        "confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "accuracy_by_risk_grade": accuracy_by_risk_grade,
        "actual_default_rate": round(actual_default_rate, 4),
        "predicted_default_rate": round(predicted_default_rate, 4),
        "calibration_gap": round(calibration_gap, 4),
        "outcome_breakdown": dict(outcome_counts),
    }


def compute_vintage_analysis(months_back=12):
    """Track outcome rates by origination month (vintage curves).

    Returns list of dicts:
        [{'month': '2025-01', 'originated': int, 'defaulted': int, 'default_rate': float}, ...]
    """
    # Only consider approved applications that have an actual outcome
    apps = (
        LoanApplication.objects.filter(
            actual_outcome__isnull=False,
            decision__decision="approved",
        )
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(
            originated=Count("id"),
            defaulted=Count(
                "id",
                filter=Q(actual_outcome__in=list(BAD_OUTCOMES)),
            ),
        )
        .order_by("month")
    )

    results = []
    for row in apps:
        originated = row["originated"]
        defaulted = row["defaulted"]
        month_str = row["month"].strftime("%Y-%m") if row["month"] else "unknown"
        results.append(
            {
                "month": month_str,
                "originated": originated,
                "defaulted": defaulted,
                "default_rate": round(defaulted / originated, 4) if originated else 0.0,
            }
        )

    return results
