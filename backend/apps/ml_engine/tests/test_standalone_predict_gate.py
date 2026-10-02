from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.loans.models import LoanApplication

pytestmark = pytest.mark.django_db


def _denied_customer_app(django_user_model):
    cust = django_user_model.objects.create_user(username="pc", password="x", role="customer", email="pc@x.com")
    app = LoanApplication.objects.create(
        applicant=cust,
        annual_income=50000,
        credit_score=600,
        loan_amount=20000,
        debt_to_income=4,
        employment_length=2,
        purpose="personal",
        home_ownership="rent",
        status="pending",
    )
    return cust, app


def test_predict_endpoint_disabled_by_default(django_user_model):
    cust, app = _denied_customer_app(django_user_model)
    client = APIClient()
    client.force_authenticate(cust)
    r = client.post(f"/api/v1/ml/predict/{app.id}/")
    assert r.status_code == 503


@override_settings(ML_STANDALONE_PREDICT_ENABLED=True)
def test_predict_endpoint_enabled_when_flag_on(django_user_model, monkeypatch):
    cust, app = _denied_customer_app(django_user_model)
    # Don't actually enqueue Celery — assert the queued envelope.
    from apps.ml_engine import views as ml_views

    class _FakeTask:
        id = "task-123"

    monkeypatch.setattr(ml_views.run_prediction_task, "delay", lambda *_a, **_k: _FakeTask())
    client = APIClient()
    client.force_authenticate(cust)
    r = client.post(f"/api/v1/ml/predict/{app.id}/")
    assert r.status_code == 202
    assert r.data["status"] == "prediction_queued"


def _run_task(app, predictor=None, *, for_application_side_effect=None):
    kwargs = {"return_value": predictor} if predictor is not None else {"side_effect": for_application_side_effect}
    with patch("apps.ml_engine.services.scoring.predictor.ModelPredictor.for_application", **kwargs):
        from apps.ml_engine.tasks import run_prediction_task

        return run_prediction_task.run(str(app.id))  # synchronous, no Celery broker


@pytest.mark.parametrize("flag", [False, True])
def test_task_applies_decision_with_refer_reasons_whatever_the_flag(django_user_model, flag):
    """Refer reasons (borderline / drift / policy refer) never send the
    application to the review queue: that queue is only for bias flags."""
    cust, app = _denied_customer_app(django_user_model)
    fake = {
        "prediction": "denied",
        "probability": 0.49,
        "model_version": None,
        "feature_importances": {"credit_score": 0.3},
        "shap_values": {},
        "processing_time_ms": 10,
        "refer_reasons": [{"code": "BORDERLINE", "detail": "near threshold"}],
    }
    predictor = MagicMock()
    predictor.predict.return_value = fake
    with override_settings(ML_STANDALONE_PREDICT_ENABLED=flag):
        _run_task(app, predictor)
    app.refresh_from_db()
    assert app.status == "denied"


def test_task_no_active_model_returns_to_pending_through_the_state_machine(django_user_model):
    from apps.loans.models import AuditLog
    from apps.ml_engine.services.model_selector import NoActiveModelError

    cust, app = _denied_customer_app(django_user_model)
    result = _run_task(app, for_application_side_effect=NoActiveModelError("no model"))

    assert result["reason"] == "no_active_model"
    app.refresh_from_db()
    assert app.status == "pending"
    last = AuditLog.objects.filter(resource_id=str(app.id), action="status_transition").latest("timestamp")
    assert last.details["to_status"] == "pending"
    assert last.details["reason"] == "no_active_model"


def test_task_integrity_failure_is_not_reported_as_no_active_model(django_user_model):
    """A tampered artefact (hash mismatch) is an incident, not "no model":
    it must surface (raise) after the application is returned to pending."""
    cust, app = _denied_customer_app(django_user_model)
    with pytest.raises(ValueError, match="integrity"):
        _run_task(
            app,
            for_application_side_effect=ValueError("Model file integrity check failed: expected hash ab..., got cd..."),
        )
    app.refresh_from_db()
    assert app.status == "pending"
