"""M4: dashboards and weekly drift picked the newest active model of any segment.

``ModelVersion.objects.filter(is_active=True).first()`` returns the newest
active row across segments, so once a per-segment model exists the metrics
page and the drift list switch to it, and the weekly drift job monitors only
that one model.
"""

import pytest
from rest_framework.test import APIClient

from apps.loans.models import LoanApplication
from apps.ml_engine.models import DriftReport, ModelVersion, PredictionLog

pytestmark = pytest.mark.django_db


def _mv(settings, version, segment):
    return ModelVersion.objects.create(
        algorithm="xgb",
        version=version,
        file_path=str(settings.ML_MODELS_DIR / f"{version}.joblib"),
        is_active=True,
        traffic_percentage=100,
        segment=segment,
        training_metadata={"reference_probabilities": [0.2, 0.4, 0.6, 0.8]},
    )


@pytest.fixture
def two_segments(settings, tmp_path):
    settings.MRM_DOSSIER_AUTO_GENERATE = False
    settings.ML_MODELS_DIR = tmp_path
    unified = _mv(settings, "unified_v1", "unified")
    personal = _mv(settings, "personal_v1", "personal")  # newer
    return unified, personal


def test_metrics_page_shows_the_unified_champion(two_segments, django_user_model):
    unified, _personal = two_segments
    admin = django_user_model.objects.create_user(username="m4_admin", password="x", role="admin")
    client = APIClient()
    client.force_authenticate(admin)
    response = client.get("/api/v1/ml/models/active/metrics/")
    assert response.status_code == 200
    assert response.json()["id"] == str(unified.id)


def test_weekly_drift_reports_every_active_model(two_segments, django_user_model):
    from apps.ml_engine.tasks import compute_weekly_drift_report

    customer = django_user_model.objects.create_user(username="m4_cust", password="x", role="customer")
    app = LoanApplication.objects.create(
        applicant=customer,
        annual_income=50000,
        credit_score=700,
        loan_amount=10000,
        debt_to_income=2,
        employment_length=3,
        purpose="personal",
        home_ownership="rent",
    )
    for mv in two_segments:
        for p in (0.3, 0.5, 0.7):
            PredictionLog.objects.create(model_version=mv, application=app, prediction="approved", probability=p)

    compute_weekly_drift_report.run()

    assert set(DriftReport.objects.values_list("model_version_id", flat=True)) == {mv.id for mv in two_segments}
