import os
from collections import Counter

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.ml_engine.services.model_selector import select_model_version


def _create_model_version(db, **kwargs):
    """Helper to create a ModelVersion with valid file_path."""
    from django.conf import settings

    from apps.ml_engine.models import ModelVersion

    models_dir = getattr(settings, "ML_MODELS_DIR", os.path.join(settings.BASE_DIR, "ml_models"))
    os.makedirs(models_dir, exist_ok=True)
    version = kwargs.pop("version", "test_v1")
    dummy_path = os.path.join(models_dir, f"test_{version}.joblib")
    with open(dummy_path, "wb") as f:
        f.write(b"dummy")

    defaults = {
        "algorithm": "xgb",
        "version": version,
        "file_path": dummy_path,
        "is_active": True,
        "traffic_percentage": 100,
        "accuracy": 0.85,
        "auc_roc": 0.88,
    }
    defaults.update(kwargs)
    return ModelVersion.objects.create(**defaults)


@pytest.mark.django_db
class TestModelSelector:
    def test_single_model_always_selected(self):
        mv = _create_model_version(True, version="solo_v1")
        for _ in range(10):
            assert select_model_version().id == mv.id

    def test_no_active_models_raises(self):
        with pytest.raises(ValueError, match="No active model"):
            select_model_version()

    def test_weighted_distribution_approximate(self):
        import random as _random

        mv1 = _create_model_version(True, version="champ_v1", traffic_percentage=70)
        _create_model_version(True, version="chall_v1", traffic_percentage=30)

        # Deterministic RNG: production code calls random.choices() at module level,
        # so seeding the global random gives reproducible sampling.
        _random.seed(42)
        counts = Counter()
        for _ in range(1000):
            selected = select_model_version()
            counts[selected.id] += 1

        ratio = counts[mv1.id] / 1000
        assert 0.55 <= ratio <= 0.85, f"Champion got {ratio:.0%}, expected ~70%"

    def test_zero_traffic_model_never_selected(self):
        mv1 = _create_model_version(True, version="active_v1", traffic_percentage=100)
        _create_model_version(True, version="zero_v1", traffic_percentage=0)

        for _ in range(50):
            assert select_model_version().id == mv1.id


@pytest.mark.django_db
class TestTrafficValidation:
    def test_total_traffic_cannot_exceed_100(self):
        _create_model_version(True, version="v1", traffic_percentage=80)
        with pytest.raises(ValidationError):
            _create_model_version(True, version="v2", traffic_percentage=30)

    def test_total_traffic_exactly_100_ok(self):
        _create_model_version(True, version="v1", traffic_percentage=70)
        mv2 = _create_model_version(True, version="v2", traffic_percentage=30)
        assert mv2.is_active is True

    def test_inactive_model_not_counted(self):
        _create_model_version(True, version="v1", traffic_percentage=80, is_active=False)
        mv2 = _create_model_version(True, version="v2", traffic_percentage=90)
        assert mv2.traffic_percentage == 90

    def test_updating_existing_model_excludes_self(self):
        mv = _create_model_version(True, version="v1", traffic_percentage=60)
        # Updating the same model should not count its own traffic twice
        mv.traffic_percentage = 80
        mv.save()  # Should not raise
        mv.refresh_from_db()
        assert mv.traffic_percentage == 80


@pytest.mark.django_db
class TestModelVersionAPI:
    @pytest.fixture(autouse=True)
    def _use_locmem_cache(self, settings):
        settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

    def _make_admin_client(self):
        from apps.accounts.models import CustomUser

        user = CustomUser.objects.create_user(
            username="admin_test",
            email="admin@test.com",
            password="testpass123",
            role="admin",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_list_models(self):
        client = self._make_admin_client()
        _create_model_version(True, version="list_v1")
        _create_model_version(True, version="list_v2", traffic_percentage=0, is_active=False)

        resp = client.get("/api/v1/ml/models/")
        assert resp.status_code == 200
        assert len(resp.data["models"]) == 2

    def test_activate_model(self):
        client = self._make_admin_client()
        mv1 = _create_model_version(True, version="old_v1", traffic_percentage=100)
        mv2 = _create_model_version(True, version="new_v1", traffic_percentage=0, is_active=False)

        resp = client.post(f"/api/v1/ml/models/{mv2.id}/activate/")
        assert resp.status_code == 200
        assert "champion" in resp.data["message"]

        mv1.refresh_from_db()
        mv2.refresh_from_db()
        assert mv1.is_active is False
        assert mv1.traffic_percentage == 0
        assert mv2.is_active is True
        assert mv2.traffic_percentage == 100

    def test_update_traffic(self):
        client = self._make_admin_client()
        mv = _create_model_version(True, version="traffic_v1", traffic_percentage=100)

        resp = client.patch(
            f"/api/v1/ml/models/{mv.id}/traffic/",
            {"traffic_percentage": 70},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["traffic_percentage"] == 70

    def test_update_traffic_invalid(self):
        client = self._make_admin_client()
        mv = _create_model_version(True, version="traffic_v2", traffic_percentage=100)

        resp = client.patch(
            f"/api/v1/ml/models/{mv.id}/traffic/",
            {"traffic_percentage": 150},
            format="json",
        )
        assert resp.status_code == 400
