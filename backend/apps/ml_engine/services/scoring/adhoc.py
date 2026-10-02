"""Ad-hoc applicant scoring: score one applicant's facts against the active
model without creating a `LoanApplication` row.

`AdhocApplicantSerializer` validates the raw applicant facts against the
same fields (and the same model-field validators/choices) a real
`LoanApplication` decision is assessed on — `DECISION_INPUT_FIELDS`.
`score_applicant` builds an unsaved `LoanApplication` from those fields and
runs it through the real `ModelPredictor.predict(..., persist=False)` dry
run (Task 3), so nothing is written: no `LoanApplication` row, no D6
referral-audit save, no shadow-scoring `PredictionLog` row.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.loans.models import LoanApplication
from apps.ml_engine.services.scoring.predictor import ModelPredictor
from apps.ml_engine.services.scoring.segmentation import derive_segment

__all__ = ["AdhocApplicantSerializer", "score_applicant"]

TOP_FACTORS_COUNT = 5


class AdhocApplicantSerializer(serializers.ModelSerializer):
    """The applicant facts a decision is assessed on — nothing else.

    A plain `ModelSerializer` over `DECISION_INPUT_FIELDS` so the field
    validators and choices (credit score bounds, purpose/home_ownership
    choices, etc.) come from the `LoanApplication` model itself rather than
    being re-declared and risking drift.
    """

    class Meta:
        model = LoanApplication
        fields = LoanApplication.DECISION_INPUT_FIELDS


def score_applicant(validated_data: dict) -> dict:
    """Score one applicant's facts against the active model. Persists nothing."""
    application = LoanApplication(**validated_data)
    predictor = ModelPredictor(segment=derive_segment(application))
    result = predictor.predict(application, persist=False)

    shap_values = result.get("shap_values") or {}
    top_factors = [
        {"feature": feature, "impact": impact}
        for feature, impact in sorted(shap_values.items(), key=lambda kv: abs(kv[1]), reverse=True)[:TOP_FACTORS_COUNT]
    ]

    return {
        "probability": result["probability"],
        "decision": result["prediction"],
        "threshold": result["threshold_used"],
        "risk_grade": result["risk_grade"],
        "top_factors": top_factors,
        "model_version": result["model_version"],
    }
