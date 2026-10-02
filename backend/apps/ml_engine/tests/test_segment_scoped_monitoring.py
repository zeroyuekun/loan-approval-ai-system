"""M4: dashboards and weekly drift picked the newest active model of any segment.

``ModelVersion.objects.filter(is_active=True).first()`` returns the newest
active row across segments, so once a per-segment model exists the metrics
page and the drift list switch to it, and the weekly drift job monitors only
that one model.
"""

from unittest.mock import patch

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.loans.models import LoanApplication
from apps.ml_engine.models import DriftReport, ModelVersion, PredictionLog
from apps.ml_engine.services.governance.model_card import ModelCardGenerator

pytestmark = pytest.mark.django_db


def _mv(settings, version, segment, traffic_percentage=100):
    return ModelVersion.objects.create(
        algorithm="xgb",
        version=version,
        file_path=str(settings.ML_MODELS_DIR / f"{version}.joblib"),
        is_active=True,
        traffic_percentage=traffic_percentage,
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


# The remaining "active model" readers resolve the champion, not the newest
# active row. The personal model above is newer, so a plain
# ``filter(is_active=True).first()`` would pick it.


def _staff_client(django_user_model, username, role):
    user = django_user_model.objects.create_user(username=username, password="x", role=role)
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_dashboard_stats_describe_the_unified_champion(two_segments, django_user_model):
    unified, _personal = two_segments
    cache.clear()
    client = _staff_client(django_user_model, "officer", "officer")
    response = client.get("/api/v1/loans/dashboard-stats/")
    assert response.status_code == 200
    assert response.json()["active_model"]["name"] == f"xgb v{unified.version}"


def test_model_card_describes_the_unified_champion(two_segments):
    unified, _personal = two_segments
    assert ModelCardGenerator().model_version.pk == unified.pk


def test_drift_view_monitors_the_champion_not_a_random_challenger(two_segments, settings, django_user_model):
    unified, _personal = two_segments
    unified.traffic_percentage = 90
    unified.save(update_fields=["traffic_percentage"])
    # Created at 10% directly: the segment's traffic may not exceed 100%.
    challenger = _mv(settings, "unified_challenger_v1", "unified", traffic_percentage=10)  # newest, unified

    seen = []

    def _fake_psi(model_version, days):
        seen.append(model_version.pk)
        return {"application_count": 0, "days": days, "insufficient_data": True}

    client = _staff_client(django_user_model, "admin_drift", "admin")
    with (
        # Weighted A/B routing would pick the challenger on this draw.
        patch("apps.ml_engine.services.model_selector.random.choices", return_value=[challenger]),
        patch(
            "apps.ml_engine.services.governance.drift_monitor.compute_on_demand_feature_psi",
            side_effect=_fake_psi,
        ),
    ):
        response = client.get("/api/v1/ml/models/active/drift/")
    assert response.status_code == 200
    assert seen == [unified.pk]


def test_model_compare_lists_the_champion_first(two_segments, django_user_model):
    unified, personal = two_segments
    client = _staff_client(django_user_model, "admin_compare", "admin")
    response = client.get("/api/v1/ml/models/compare/")
    assert response.status_code == 200
    ids = [row["model_id"] for row in response.json()["comparison"]]
    assert ids == [str(unified.id), str(personal.id)]


def test_model_compare_needs_two_active_models(settings, tmp_path, django_user_model):
    settings.MRM_DOSSIER_AUTO_GENERATE = False
    settings.ML_MODELS_DIR = tmp_path
    _mv(settings, "only_v1", "unified")
    client = _staff_client(django_user_model, "admin_compare_one", "admin")
    response = client.get("/api/v1/ml/models/compare/")
    assert response.status_code == 200
    assert "comparison" not in response.json()
