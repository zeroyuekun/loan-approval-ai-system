"""Tests for the Model Card generator service and API endpoint."""

import os

import pytest
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient

# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestModelCardEndpoint:
    def test_model_card_unauthenticated_rejected(self):
        client = APIClient()
        response = client.get("/api/v1/ml/models/active/model-card/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @override_settings(
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    )
    def test_model_card_no_active_model_returns_404(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        response = client.get("/api/v1/ml/models/active/model-card/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "error" in response.data

    @override_settings(
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    )
    def test_model_card_returns_correct_structure(self, admin_user):
        from django.conf import settings

        from apps.ml_engine.models import ModelVersion

        # Create a dummy joblib file in the ML_MODELS_DIR
        models_dir = getattr(settings, "ML_MODELS_DIR", os.path.join(settings.BASE_DIR, "ml_models"))
        os.makedirs(models_dir, exist_ok=True)
        dummy_path = os.path.join(models_dir, "test_model_card.joblib")
        with open(dummy_path, "wb") as f:
            f.write(b"dummy")

        try:
            ModelVersion.objects.create(
                algorithm="xgb",
                version="test_v1",
                file_path=dummy_path,
                is_active=True,
                accuracy=0.85,
                precision=0.80,
                recall=0.90,
                f1_score=0.85,
                auc_roc=0.88,
                gini_coefficient=0.76,
                ks_statistic=0.65,
                brier_score=0.12,
                optimal_threshold=0.5,
                training_metadata={
                    "train_size": 800,
                    "val_size": 100,
                    "test_size": 100,
                    "class_balance": 0.65,
                    "split_strategy": "temporal",
                    "n_features": 48,
                },
                fairness_metrics={"employment_type": {"passes_80_percent_rule": True}},
            )

            client = APIClient()
            client.force_authenticate(user=admin_user)
            response = client.get("/api/v1/ml/models/active/model-card/")
            assert response.status_code == status.HTTP_200_OK

            card = response.data["model_card"]

            # All required top-level sections present
            assert "model_details" in card
            assert "intended_use" in card
            assert "training_data" in card
            assert "performance_metrics" in card
            assert "fairness_analysis" in card
            assert "limitations" in card
            assert "regulatory_compliance" in card
            assert "last_updated" in card

            # Model details
            assert card["model_details"]["algorithm"] == "xgb"
            assert card["model_details"]["version"] == "test_v1"
            assert "name" in card["model_details"]
            assert "description" in card["model_details"]

            # Training data
            assert card["training_data"]["size"] == 1000
            assert card["training_data"]["features"] == 48
            assert "label_distribution" in card["training_data"]

            # Performance metrics
            assert card["performance_metrics"]["auc_roc"] == 0.88
            assert card["performance_metrics"]["accuracy"] == 0.85
            assert card["performance_metrics"]["gini"] == 0.76
            assert card["performance_metrics"]["brier_score"] == 0.12

            # Fairness analysis
            assert "protected_attributes" in card["fairness_analysis"]
            assert "disparate_impact_ratio" in card["fairness_analysis"]

            # Regulatory compliance
            assert card["regulatory_compliance"]["apra_cpg_235"] is True
            assert card["regulatory_compliance"]["nccp_act"] is True
        finally:
            if os.path.exists(dummy_path):
                os.unlink(dummy_path)


# ---------------------------------------------------------------------------
# Service unit tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestModelCardGenerator:
    """Direct tests for the ModelCardGenerator service class."""

    def _create_model_version(self, **overrides):
        """Helper to create a ModelVersion with a dummy joblib file."""
        from django.conf import settings as django_settings

        from apps.ml_engine.models import ModelVersion

        models_dir = getattr(
            django_settings,
            "ML_MODELS_DIR",
            os.path.join(django_settings.BASE_DIR, "ml_models"),
        )
        os.makedirs(models_dir, exist_ok=True)
        dummy_path = os.path.join(models_dir, "test_model_card_svc.joblib")
        with open(dummy_path, "wb") as f:
            f.write(b"dummy")

        defaults = dict(
            algorithm="xgb",
            version="svc_v1",
            file_path=dummy_path,
            is_active=True,
            accuracy=0.90,
            precision=0.88,
            recall=0.92,
            f1_score=0.90,
            auc_roc=0.95,
            gini_coefficient=0.90,
            brier_score=0.08,
            ece=0.03,
            training_metadata={
                "train_size": 7000,
                "val_size": 1500,
                "test_size": 1500,
                "class_balance": 0.60,
                "n_features": 48,
            },
            fairness_metrics={
                "gender": {"disparate_impact_ratio": 0.92, "passes_80_percent_rule": True},
                "age_group": {"disparate_impact_ratio": 0.85, "passes_80_percent_rule": True},
            },
        )
        defaults.update(overrides)
        mv = ModelVersion.objects.create(**defaults)
        return mv, dummy_path

    def test_raises_when_no_active_model(self):
        from apps.ml_engine.services.model_card import ModelCardGenerator

        with pytest.raises(ValueError, match="No active model found"):
            ModelCardGenerator()

    def test_generate_returns_all_sections(self):
        from apps.ml_engine.services.model_card import ModelCardGenerator

        mv, path = self._create_model_version()
        try:
            card = ModelCardGenerator(mv).generate()
            expected_sections = {
                "model_details",
                "intended_use",
                "training_data",
                "performance_metrics",
                "fairness_analysis",
                "limitations",
                "regulatory_compliance",
                "last_updated",
            }
            assert set(card.keys()) == expected_sections
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_training_data_size_sums_splits(self):
        from apps.ml_engine.services.model_card import ModelCardGenerator

        mv, path = self._create_model_version()
        try:
            card = ModelCardGenerator(mv).generate()
            assert card["training_data"]["size"] == 10000  # 7000+1500+1500
            assert card["training_data"]["features"] == 48
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_label_distribution_from_class_balance(self):
        from apps.ml_engine.services.model_card import ModelCardGenerator

        mv, path = self._create_model_version()
        try:
            card = ModelCardGenerator(mv).generate()
            dist = card["training_data"]["label_distribution"]
            assert dist["approved"] == 0.60
            assert dist["denied"] == 0.40
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_gini_fallback_from_auc(self):
        """When gini_coefficient is null, derive from AUC: 2*AUC - 1."""
        from apps.ml_engine.services.model_card import ModelCardGenerator

        mv, path = self._create_model_version(gini_coefficient=None, auc_roc=0.88)
        try:
            card = ModelCardGenerator(mv).generate()
            assert card["performance_metrics"]["gini"] == round(2 * 0.88 - 1, 4)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_fairness_extracts_disparate_impact(self):
        from apps.ml_engine.services.model_card import ModelCardGenerator

        mv, path = self._create_model_version()
        try:
            card = ModelCardGenerator(mv).generate()
            di = card["fairness_analysis"]["disparate_impact_ratio"]
            assert "gender" in di
            assert di["gender"] == 0.92
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_accepts_explicit_model_version(self):
        """Constructor accepts a specific ModelVersion rather than auto-detecting."""
        from apps.ml_engine.services.model_card import ModelCardGenerator

        mv, path = self._create_model_version(is_active=False, version="explicit_v1")
        try:
            card = ModelCardGenerator(mv).generate()
            assert card["model_details"]["version"] == "explicit_v1"
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_empty_fairness_metrics_handled(self):
        from apps.ml_engine.services.model_card import ModelCardGenerator

        mv, path = self._create_model_version(fairness_metrics={})
        try:
            card = ModelCardGenerator(mv).generate()
            assert card["fairness_analysis"]["disparate_impact_ratio"] == {}
        finally:
            if os.path.exists(path):
                os.unlink(path)
