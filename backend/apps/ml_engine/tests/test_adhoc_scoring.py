"""Ad-hoc applicant scoring: dry-run predictor mode + the scoring endpoint.

Task 3 proves `ModelPredictor.predict(app, persist=False)` writes nothing —
no referral-audit save on the (unsaved) `LoanApplication` and no shadow-
scoring `PredictionLog` row. Task 4 adds the `AdhocScoreView` tests that
drive the same dry-run path through the REST endpoint.
"""

from __future__ import annotations

from unittest.mock import ANY, MagicMock, patch

import pytest
from rest_framework.test import APIClient

from apps.loans.models import AuditLog, LoanApplication
from apps.ml_engine.models import PredictionLog
from apps.ml_engine.services.governance.shadow_scoring import score_challengers_shadow
from apps.ml_engine.services.model_selector import NoActiveModelError
from apps.ml_engine.services.scoring import predictor as predictor_mod
from apps.ml_engine.services.scoring.adhoc import ADHOC_SCORE_NOTE
from apps.ml_engine.services.scoring.policy_overlay import apply_policy_overlay
from apps.ml_engine.tests.predictor_stub import build_stub_predictor

pytestmark = pytest.mark.django_db


class TestPredictorDryRun:
    def test_persist_false_writes_nothing(self, monkeypatch):
        predictor = build_stub_predictor(
            monkeypatch,
            features={"purpose": "personal", "employment_type": "payg_permanent", "loan_amount": 20000},
            probability=0.4,
            threshold=0.5,
        )
        # Swap in the REAL write-site helpers (the stub no-ops them out) so
        # this test actually exercises — and would fail on — a missing guard,
        # instead of passing regardless because the stub never calls them.
        monkeypatch.setattr(predictor_mod, "_apply_policy_overlay_helper", apply_policy_overlay)
        monkeypatch.setattr(predictor_mod, "_score_challengers_shadow_helper", score_challengers_shadow)

        app = LoanApplication(
            annual_income=60000,
            credit_score=680,
            loan_amount=20000,
            debt_to_income=3,
            employment_length=4,
            purpose="personal",
            home_ownership="rent",
            num_hardship_flags=1,  # P11 refer — exercises the referral-audit save guard
        )

        def _fail_if_saved(*_a, **_k):
            pytest.fail("persist=False must not save the unsaved LoanApplication")

        monkeypatch.setattr(app, "save", _fail_if_saved)

        result = predictor.predict(app, persist=False)

        assert "probability" in result
        assert LoanApplication.objects.count() == 0
        assert PredictionLog.objects.count() == 0


ADHOC_SCORE_URL = "/api/v1/ml/models/active/score/"

VALID_ADHOC_PAYLOAD = {
    "annual_income": 95000,
    "credit_score": 720,
    "loan_amount": 30000,
    "loan_term_months": 60,
    "debt_to_income": 2.5,
    "employment_length": 5,
    "property_value": 0,
    "deposit_amount": 0,
    "monthly_expenses": 2000,
    "existing_credit_card_limit": 5000,
    "number_of_dependants": 0,
    "employment_type": "payg_permanent",
    "applicant_type": "single",
    "purpose": "personal",
    "home_ownership": "rent",
    "has_cosigner": False,
    "has_hecs": False,
    "has_bankruptcy": False,
    "state": "NSW",
}


def _fake_predict_result():
    return {
        "prediction": "approved",
        "probability": 0.82,
        "threshold_used": 0.5,
        "risk_grade": "A",
        "shap_values": {
            "purpose": 0.3,
            "credit_score": 0.12,
            "annual_income": 0.08,
            "loan_amount": -0.05,
            "debt_to_income": -0.02,
            "employment_length": 0.01,  # 6th-largest — must be dropped from top_factors
        },
        "model_version": "11111111-1111-1111-1111-111111111111",
    }


def _mock_adhoc_predictor():
    """Patch `adhoc.ModelPredictor` to return a concrete dict (no MagicMock leaves)."""
    mock_predictor = MagicMock()
    mock_predictor.predict.return_value = _fake_predict_result()
    patcher = patch("apps.ml_engine.services.scoring.adhoc.ModelPredictor", return_value=mock_predictor)
    return patcher, mock_predictor


class TestAdhocScoreView:
    def test_customer_forbidden(self, django_user_model):
        customer = django_user_model.objects.create_user(username="adhoc_cust", password="x", role="customer")
        client = APIClient()
        client.force_authenticate(customer)

        response = client.post(ADHOC_SCORE_URL, VALID_ADHOC_PAYLOAD, format="json")

        assert response.status_code == 403

    def test_missing_credit_score_is_bad_request(self, django_user_model):
        officer = django_user_model.objects.create_user(username="adhoc_off_400", password="x", role="officer")
        client = APIClient()
        client.force_authenticate(officer)
        payload = {k: v for k, v in VALID_ADHOC_PAYLOAD.items() if k != "credit_score"}

        patcher, _mock_predictor = _mock_adhoc_predictor()
        with patcher:
            response = client.post(ADHOC_SCORE_URL, payload, format="json")

        assert response.status_code == 400

    def test_officer_gets_200_with_response_keys(self, django_user_model):
        officer = django_user_model.objects.create_user(username="adhoc_off_200", password="x", role="officer")
        client = APIClient()
        client.force_authenticate(officer)

        patcher, mock_predictor = _mock_adhoc_predictor()
        with patcher:
            response = client.post(ADHOC_SCORE_URL, VALID_ADHOC_PAYLOAD, format="json")

        assert response.status_code == 200
        data = response.json()
        assert set(data.keys()) == {
            "probability",
            "decision",
            "threshold",
            "risk_grade",
            "top_factors",
            "model_version",
            "note",
            "defaulted_features",
        }
        assert data["decision"] == "approved"
        assert data["probability"] == 0.82
        assert data["threshold"] == 0.5
        assert data["risk_grade"] == "A"
        assert data["model_version"] == "11111111-1111-1111-1111-111111111111"
        # Top 5 of 6 by absolute SHAP value — employment_length (0.01) dropped.
        assert data["top_factors"] == [
            {"feature": "purpose", "impact": 0.3},
            {"feature": "credit_score", "impact": 0.12},
            {"feature": "annual_income", "impact": 0.08},
            {"feature": "loan_amount", "impact": -0.05},
            {"feature": "debt_to_income", "impact": -0.02},
        ]
        mock_predictor.predict.assert_called_once_with(ANY, persist=False)

        assert data["note"] == ADHOC_SCORE_NOTE
        assert isinstance(data["defaulted_features"], list)
        assert len(data["defaulted_features"]) > 0
        assert data["defaulted_features"] == sorted(data["defaulted_features"])
        submitted_fields = set(VALID_ADHOC_PAYLOAD.keys())
        assert not (set(data["defaulted_features"]) & submitted_fields)
        # Spot-check a couple of the ~40 bureau/banking/macro features the
        # ad-hoc form never collects, called out by the review.
        for expected in ("num_hardship_flags", "rba_cash_rate", "postcode_default_rate"):
            assert expected in data["defaulted_features"]

    def test_no_active_model_returns_503(self, django_user_model):
        officer = django_user_model.objects.create_user(username="adhoc_off_503", password="x", role="officer")
        client = APIClient()
        client.force_authenticate(officer)

        with patch(
            "apps.ml_engine.services.scoring.adhoc.ModelPredictor",
            side_effect=NoActiveModelError("no model"),
        ):
            response = client.post(ADHOC_SCORE_URL, VALID_ADHOC_PAYLOAD, format="json")

        assert response.status_code == 503
        assert response.json() == {"detail": "No active model"}

    def test_no_writes_and_audit_log_records_field_names_only(self, django_user_model):
        officer = django_user_model.objects.create_user(username="adhoc_off_audit", password="x", role="officer")
        client = APIClient()
        client.force_authenticate(officer)

        patcher, _mock_predictor = _mock_adhoc_predictor()
        with patcher:
            response = client.post(ADHOC_SCORE_URL, VALID_ADHOC_PAYLOAD, format="json")

        assert response.status_code == 200
        assert LoanApplication.objects.count() == 0
        assert PredictionLog.objects.count() == 0

        log = AuditLog.objects.get(action="adhoc_score")
        assert log.details["fields"] == sorted(VALID_ADHOC_PAYLOAD.keys())
        submitted_values = set(VALID_ADHOC_PAYLOAD.values())
        for field_name in log.details["fields"]:
            assert field_name not in submitted_values
