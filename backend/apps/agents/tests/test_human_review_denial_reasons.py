from apps.agents.services.human_review_handler import build_denial_reason_summary


def test_summary_uses_reason_code_text_not_raw_floats():
    summary = build_denial_reason_summary(
        shap_values={"credit_score": -0.5, "debt_to_income": -0.3},
        feature_importances={"credit_score": 0.5},
    )
    assert "Credit score below minimum" in summary
    assert "0.5" not in summary  # no raw float dump
