"""I5: an applicant beyond the training range is scored, not rejected.

Columns with no service (policy) limit used to get the training (p1, p99) as
their only bound, so roughly 1-2% of applicants per feature raised
ApplicationValidationError, the orchestrator failed the prediction step and
the applicant got no decision. Now the model sees the value clipped to the
range it was trained on, and the clip is recorded on the result.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from apps.ml_engine.tests.predictor_stub import build_stub_predictor


def test_value_beyond_training_quantiles_is_scored_with_the_clipped_value(monkeypatch):
    p = build_stub_predictor(
        monkeypatch,
        features={"employment_type": "payg_permanent", "purpose": "personal", "monthly_rent": 12_000.0},
        probability=0.9,
        threshold=0.5,
        feature_cols=["monthly_rent"],
        # The bundle's training-quantile bound for a column with no hard bound.
        feature_bounds={"monthly_rent": (300.0, 5488.0)},
        reference_distribution={
            "monthly_rent": {"percentiles": [200.0, 900.0, 1500.0, 8000.0], "mean": 1600.0, "std": 700.0}
        },
    )

    result = p.predict(MagicMock())

    assert result["prediction"] == "approved"
    model_input = p.model.predict_proba.call_args.args[0]
    assert model_input["monthly_rent"].tolist() == [8000.0]
    assert [c["feature"] for c in result["clipped_features"]] == ["monthly_rent"]
    assert result["clipped_features"][0]["value"] == 12_000.0
