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


@pytest.mark.django_db
def test_task_applies_decision_not_review_when_flag_off(django_user_model):
    cust, app = _denied_customer_app(django_user_model)
    fake = {
        "prediction": "denied",
        "probability": 0.49,
        "model_version": None,
        "feature_importances": {"credit_score": 0.3},
        "shap_values": {},
        "processing_time_ms": 10,
        "requires_human_review": True,
    }
    predictor = MagicMock()
    predictor.predict.return_value = fake
    with patch("apps.ml_engine.services.scoring.predictor.ModelPredictor.for_application", return_value=predictor):
        from apps.ml_engine.tasks import run_prediction_task

        run_prediction_task.run(str(app.id))  # synchronous, no Celery broker
    app.refresh_from_db()
    assert app.status == "denied"  # NOT 'review' (would be unresumable)
