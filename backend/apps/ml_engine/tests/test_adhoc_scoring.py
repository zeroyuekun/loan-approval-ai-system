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


class _AdhocPredictorPatch:
    """Patch the champion lookup and `adhoc.ModelPredictor` together."""

    def __init__(self, predictor):
        self._patches = [
            patch("apps.ml_engine.services.scoring.adhoc.champion_model_version", return_value=MagicMock()),
            patch("apps.ml_engine.services.scoring.adhoc.ModelPredictor", return_value=predictor),
        ]

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


def _mock_adhoc_predictor():
    """Patch `adhoc.ModelPredictor` to return a concrete dict (no MagicMock leaves)."""
    mock_predictor = MagicMock()
    mock_predictor.predict.return_value = _fake_predict_result()
    return _AdhocPredictorPatch(mock_predictor), mock_predictor


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
            "policy_mode",
            "policy_hard_fails",
            "policy_refers",
            "refer_reasons",
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
            "apps.ml_engine.services.scoring.adhoc.champion_model_version",
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
        assert set(log.details) == {"fields"}
        assert log.details["fields"] == sorted(VALID_ADHOC_PAYLOAD.keys())


# ---------------------------------------------------------------------------
# Final-review fixes
# ---------------------------------------------------------------------------

# Mirrors toPayload(SAMPLE_APPLICANT) in frontend TryItTab.tsx; keep in sync.
FRONTEND_SAMPLE_PAYLOAD = {
    "annual_income": 95000,
    "credit_score": 780,
    "loan_amount": 450000,
    "loan_term_months": 360,
    "debt_to_income": 3.2,
    "employment_length": 4,
    "number_of_dependants": 0,
    "property_value": 600000,
    "deposit_amount": 150000,
    "monthly_expenses": 3000,
    "purpose": "home",
    "home_ownership": "mortgage",
    "employment_type": "payg_permanent",
    "applicant_type": "single",
    "state": "NSW",
}


def _stub_with_real_input_checks(monkeypatch, **kwargs):
    """A stub predictor that keeps the REAL feature building, input-bounds
    validation and consistency checker, so view tests exercise the paths that
    reject an inconsistent applicant."""
    from apps.ml_engine.services.scoring import prediction_features as pf
    from apps.ml_engine.services.scoring.consistency import DataConsistencyChecker
    from apps.ml_engine.services.training.feature_engineering import DEFAULT_IMPUTATION_VALUES

    predictor = build_stub_predictor(monkeypatch, features={}, probability=0.8, threshold=0.5, **kwargs)
    monkeypatch.setattr(predictor_mod, "_build_prediction_features_helper", pf.build_prediction_features)
    monkeypatch.setattr(predictor_mod, "_derive_underwriter_features_helper", pf.derive_underwriter_features)
    predictor.consistency_checker = DataConsistencyChecker()
    predictor.imputation_values = dict(DEFAULT_IMPUTATION_VALUES)
    return predictor


@pytest.fixture
def officer_client(django_user_model):
    officer = django_user_model.objects.create_user(username="adhoc_off_fix", password="x", role="officer")
    client = APIClient()
    client.force_authenticate(officer)
    return client


class TestAdhocInputErrors:
    def test_frontend_sample_scores_200_through_the_real_consistency_checker(self, monkeypatch, officer_client):
        predictor = _stub_with_real_input_checks(monkeypatch)

        with _AdhocPredictorPatch(predictor):
            response = officer_client.post(ADHOC_SCORE_URL, FRONTEND_SAMPLE_PAYLOAD, format="json")

        assert response.status_code == 200, response.json()
        assert response.json()["decision"] == "approved"

    def test_home_loan_without_property_value_is_400_with_value_free_detail(self, monkeypatch, officer_client, caplog):
        predictor = _stub_with_real_input_checks(monkeypatch)
        payload = {k: v for k, v in FRONTEND_SAMPLE_PAYLOAD.items() if k != "property_value"}

        with _AdhocPredictorPatch(predictor), caplog.at_level("WARNING"):
            response = officer_client.post(ADHOC_SCORE_URL, payload, format="json")

        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "property value" in detail.lower()
        assert not any(ch.isdigit() for ch in detail), detail
        logged = " ".join(r.getMessage() for r in caplog.records)
        assert "ConsistencyError" in logged
        for value in ("450000", "450,000", "95000", "95,000", "150000", "150,000"):
            assert value not in logged

    def test_loan_above_property_value_is_400_without_echoing_figures(self, monkeypatch, officer_client):
        predictor = _stub_with_real_input_checks(monkeypatch)
        payload = {**FRONTEND_SAMPLE_PAYLOAD, "property_value": 400000, "deposit_amount": 50000}

        with _AdhocPredictorPatch(predictor):
            response = officer_client.post(ADHOC_SCORE_URL, payload, format="json")

        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "loan cannot exceed the property purchase price" in detail.lower()
        assert not any(ch.isdigit() for ch in detail), detail

    def test_out_of_bounds_value_is_400_naming_the_field_only(self, officer_client):
        from apps.ml_engine.services.training.feature_prep import ApplicationValidationError

        mock_predictor = MagicMock()
        mock_predictor.predict.side_effect = ApplicationValidationError(
            "Input validation failed: loan_amount: 0.0 is outside valid range [1000, 5000000]",
            fields=["loan_amount"],
        )

        with _AdhocPredictorPatch(mock_predictor):
            response = officer_client.post(ADHOC_SCORE_URL, FRONTEND_SAMPLE_PAYLOAD, format="json")

        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "loan_amount" in detail
        assert not any(ch.isdigit() for ch in detail), detail

    def test_policy_overlay_unavailable_is_503_generic(self, officer_client, caplog):
        from apps.ml_engine.services.scoring.policy_overlay import PolicyOverlayUnavailable

        mock_predictor = MagicMock()
        mock_predictor.predict.side_effect = PolicyOverlayUnavailable(
            "Credit policy overlay could not be evaluated: 450000"
        )

        with _AdhocPredictorPatch(mock_predictor), caplog.at_level("WARNING"):
            response = officer_client.post(ADHOC_SCORE_URL, FRONTEND_SAMPLE_PAYLOAD, format="json")

        assert response.status_code == 503
        detail = response.json()["detail"]
        assert "450000" not in detail
        assert "credit policy" in detail.lower()
        assert "450000" not in " ".join(r.getMessage() for r in caplog.records)
        assert not AuditLog.objects.filter(action="adhoc_score").exists()


class TestAdhocPolicyReasons:
    def test_response_names_the_policy_codes_and_refer_reasons(self, monkeypatch, officer_client):
        predictor = _stub_with_real_input_checks(monkeypatch)
        monkeypatch.setattr(
            predictor_mod,
            "_apply_policy_overlay_helper",
            lambda **k: (
                "denied",
                {
                    "passed": False,
                    "mode": "enforce",
                    "hard_fails": ["P01"],
                    "refers": ["P11"],
                    "rationale_by_code": {"P01": "x", "P11": "y"},
                    "changed_model_decision": True,
                },
            ),
        )

        with _AdhocPredictorPatch(predictor):
            response = officer_client.post(ADHOC_SCORE_URL, FRONTEND_SAMPLE_PAYLOAD, format="json")

        assert response.status_code == 200, response.json()
        data = response.json()
        assert data["decision"] == "denied"
        assert data["policy_mode"] == "enforce"
        assert data["policy_hard_fails"] == ["P01"]
        assert data["policy_refers"] == ["P11"]
        assert "POLICY_REFER_P11" in data["refer_reasons"]
        assert all(isinstance(code, str) for code in data["refer_reasons"])


_PROMETHEUS_METRICS = (
    "ml_predictions_total",
    "ml_prediction_latency_seconds",
    "ml_prediction_confidence",
    "ml_drift_warnings_total",
)


def _personal_app():
    return LoanApplication(
        annual_income=60000,
        credit_score=680,
        loan_amount=20000,
        debt_to_income=3,
        employment_length=4,
        purpose="personal",
        home_ownership="rent",
    )


def _personal_stub(monkeypatch):
    return build_stub_predictor(
        monkeypatch,
        features={"purpose": "personal", "employment_type": "payg_permanent", "loan_amount": 20000},
        probability=0.7,
        threshold=0.5,
    )


class TestDryRunSideEffects:
    @pytest.mark.parametrize("persist", [False, True])
    def test_prometheus_metrics_only_for_persisted_predictions(self, monkeypatch, persist):
        predictor = _personal_stub(monkeypatch)
        spies = {name: MagicMock() for name in _PROMETHEUS_METRICS}
        for name, spy in spies.items():
            monkeypatch.setattr(predictor_mod, name, spy)

        predictor.predict(_personal_app(), persist=persist)

        touched = {name for name, spy in spies.items() if spy.mock_calls}
        if persist:
            assert touched >= {"ml_predictions_total", "ml_prediction_latency_seconds", "ml_prediction_confidence"}
        else:
            assert touched == set()

    @pytest.mark.parametrize("persist", [False, True])
    def test_shadow_scoring_only_for_persisted_predictions(self, monkeypatch, persist):
        predictor = _personal_stub(monkeypatch)
        shadow_spy = MagicMock()
        monkeypatch.setattr(predictor_mod, "_score_challengers_shadow_helper", shadow_spy)

        predictor.predict(_personal_app(), persist=persist)

        assert shadow_spy.call_count == (1 if persist else 0)

    @pytest.mark.parametrize("persist", [False, True])
    def test_shadow_disagreement_log_only_for_persisted_predictions(self, monkeypatch, caplog, persist):
        from types import SimpleNamespace

        from apps.ml_engine.services.scoring import policy_overlay

        failing = SimpleNamespace(
            passed=False,
            has_hard_fail=True,
            has_refer=False,
            hard_fails=["P01"],
            refers=[],
            rationale_by_code={},
            to_dict=lambda: {"passed": False, "hard_fails": ["P01"], "refers": []},
        )
        monkeypatch.setattr(policy_overlay._policy, "current_mode", lambda: policy_overlay._policy.OVERLAY_MODE_SHADOW)
        monkeypatch.setattr(policy_overlay._policy, "evaluate", lambda application: failing)

        with caplog.at_level("WARNING", logger=policy_overlay.logger.name):
            label, _payload = apply_policy_overlay(
                application=None,
                model_version=None,
                prediction_label="approved",
                persist_referral=persist,
            )

        assert label == "approved"
        emitted = any(r.getMessage() == "credit_policy_shadow_disagreement" for r in caplog.records)
        assert emitted is persist


class TestThrottleScopes:
    def test_ml_throttles_do_not_share_the_global_user_bucket(self):
        from apps.ml_engine.views import AdhocScoreThrottle, PredictionThrottle

        request = MagicMock()
        request.user.is_authenticated = True
        request.user.pk = 7

        adhoc_key = AdhocScoreThrottle().get_cache_key(request, None)
        predict_key = PredictionThrottle().get_cache_key(request, None)

        assert not adhoc_key.startswith("throttle_user_")
        assert not predict_key.startswith("throttle_user_")
        assert adhoc_key != predict_key


class TestChampionPinning:
    def _mv(self, settings, version, traffic, segment="unified"):
        from apps.ml_engine.models import ModelVersion

        return ModelVersion.objects.create(
            algorithm="xgb",
            version=version,
            file_path=str(settings.ML_MODELS_DIR / f"{version}.joblib"),
            is_active=True,
            traffic_percentage=traffic,
            segment=segment,
        )

    def test_champion_is_the_highest_traffic_model_every_time(self, settings):
        from apps.ml_engine.services.model_selector import champion_model_version

        champion = self._mv(settings, "champ", 70)
        self._mv(settings, "challenger", 30)

        assert {champion_model_version("unified").pk for _ in range(25)} == {champion.pk}

    def test_champion_falls_back_to_unified_and_raises_when_none(self, settings):
        from apps.ml_engine.services.model_selector import champion_model_version

        with pytest.raises(NoActiveModelError):
            champion_model_version("personal")
        champion = self._mv(settings, "champ", 100)
        assert champion_model_version("personal").pk == champion.pk

    def test_score_applicant_scores_against_the_pinned_champion(self, settings):
        from apps.ml_engine.services.scoring.adhoc import score_applicant

        champion = self._mv(settings, "champ", 70)
        self._mv(settings, "challenger", 30)
        mock_predictor = MagicMock()
        mock_predictor.predict.return_value = _fake_predict_result()

        with patch("apps.ml_engine.services.scoring.adhoc.ModelPredictor", return_value=mock_predictor) as ctor:
            for _ in range(5):
                score_applicant(dict(VALID_ADHOC_PAYLOAD))

        assert {c.kwargs["model_version"].pk for c in ctor.call_args_list} == {champion.pk}
