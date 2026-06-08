from apps.ml_engine.services.decision_explanation import (
    build_explanation_payload,
    ranked_denial_drivers,
)


def test_ranked_drivers_prefers_negative_shap_then_caps():
    shap = {"credit_score": -0.4, "annual_income": -0.1, "loan_amount": 0.2, "debt_to_income": -0.3}
    drivers = ranked_denial_drivers(shap_values=shap, feature_importances={}, max_n=2)
    assert [d[0] for d in drivers] == ["credit_score", "debt_to_income"]


def test_ranked_drivers_falls_back_to_importances_when_no_negative_shap():
    drivers = ranked_denial_drivers(
        shap_values={}, feature_importances={"credit_score": 0.5, "loan_amount": 0.2}, max_n=1
    )
    assert drivers[0][0] == "credit_score"


def test_build_payload_denied_has_reasons_counterfactuals_and_adm():
    payload = build_explanation_payload(
        decision="denied",
        shap_values={"credit_score": -0.5},
        feature_importances={"credit_score": 0.5},
        counterfactual_results=[{"changes": {"loan_amount": 10000}, "statement": "Reduce your loan amount"}],
        requires_human_review=False,
    )
    assert payload["decision"] == "denied"
    assert payload["denial_reasons"][0]["code"] == "R06"
    assert payload["counterfactuals"][0]["statement"].startswith("Reduce")
    assert payload["reapplication_guidance"] is not None
    assert payload["adm_disclosure"]["mode"] == "solely_automated"


def test_build_payload_approved_omits_denial_fields():
    payload = build_explanation_payload(
        decision="approved",
        shap_values={},
        feature_importances={},
        counterfactual_results=[],
        requires_human_review=False,
    )
    assert payload["denial_reasons"] == []
    assert payload["counterfactuals"] == []
    assert payload["reapplication_guidance"] is None
    assert payload["adm_disclosure"]["mode"] == "solely_automated"


def test_build_payload_overridden_is_human_mode():
    payload = build_explanation_payload(
        decision="approved",
        shap_values={},
        feature_importances={},
        counterfactual_results=[],
        requires_human_review=False,
        human_involvement="overridden",
    )
    assert payload["adm_disclosure"]["mode"] == "human"
