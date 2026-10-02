"""Ad-hoc applicant scoring: score one applicant's facts against the active
model without creating a `LoanApplication` row.

`AdhocApplicantSerializer` collects only the decision-input facts
(`DECISION_INPUT_FIELDS`) — the ~19 fields a loan officer would key in by
hand. A real `LoanApplication` decision is also assessed on roughly 40 more
attributes (credit bureau, banking behaviour, CCR, macroeconomic context,
etc. — see `prediction_features.build_prediction_features`) that this form
never collects; those take the model's training-time defaults instead.
`score_applicant` builds an unsaved `LoanApplication` from the collected
fields and runs it through the real `ModelPredictor.predict(...,
persist=False)` dry run (Task 3), so nothing is written: no
`LoanApplication` row, no D6 referral-audit save, no shadow-scoring
`PredictionLog` row. The response reports which feature names were
defaulted this way (`defaulted_features`) so a caller can judge how much to
trust the score.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.loans.models import LoanApplication
from apps.ml_engine.services.scoring.prediction_features import build_prediction_features
from apps.ml_engine.services.scoring.predictor import ModelPredictor
from apps.ml_engine.services.scoring.segmentation import derive_segment

__all__ = ["AdhocApplicantSerializer", "score_applicant"]

TOP_FACTORS_COUNT = 5

ADHOC_SCORE_NOTE = (
    "Scored on the facts entered here. Credit bureau, banking and economic features "
    "are not collected on this form and use the model's training defaults, so a real "
    "application with that data on file can score differently."
)

# Dummy args for the key-enumeration call in `_defaulted_feature_names` below — the
# key SET `build_prediction_features` returns is fixed by its source (each key is a
# literal in the dict it builds); only the *values* depend on imputation_values /
# safe_get_state_fn, which we don't need here and don't want to depend on (that
# would require a loaded model bundle, unavailable when `ModelPredictor` is mocked).
_FEATURE_KEY_PLACEHOLDER_IMPUTATION: dict = {}


def _placeholder_state(application) -> str:
    return getattr(application, "state", None) or "NSW"


class AdhocApplicantSerializer(serializers.ModelSerializer):
    """The decision-input facts collected for ad-hoc scoring — nothing else.

    A plain `ModelSerializer` over `DECISION_INPUT_FIELDS` so the field
    validators and choices (credit score bounds, purpose/home_ownership
    choices, etc.) come from the `LoanApplication` model itself rather than
    being re-declared and risking drift. The model reads many more features
    than these at inference time; see the module docstring.
    """

    class Meta:
        model = LoanApplication
        fields = LoanApplication.DECISION_INPUT_FIELDS


def _defaulted_feature_names(application) -> list[str]:
    """Model feature names this ad-hoc instance did not supply.

    `build_prediction_features` is the one place that enumerates every
    attribute the model reads off a `LoanApplication` at inference time, so
    diffing its key set against what the serializer actually collected
    (`DECISION_INPUT_FIELDS`) is the most direct, honest source for this —
    no hard-coded list to drift out of sync with that function.
    """
    features = build_prediction_features(
        application,
        safe_get_state_fn=_placeholder_state,
        imputation_values=_FEATURE_KEY_PLACEHOLDER_IMPUTATION,
    )
    return sorted(set(features) - set(LoanApplication.DECISION_INPUT_FIELDS))


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
        "note": ADHOC_SCORE_NOTE,
        "defaulted_features": _defaulted_feature_names(application),
    }
