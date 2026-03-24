"""Tests for adverse action notice generator and model inventory.

All tests use mocks — no Django DB required.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.ml_engine.services.adverse_action import (
    AFCA_COMPLAINT_TEXT,
    RIGHT_TO_REQUEST_TEXT,
    generate_adverse_action_notice,
    generate_model_inventory_entry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_application(app_id=42, first_name="Jane", last_name="Doe", email="jane@example.com"):
    user = SimpleNamespace(first_name=first_name, last_name=last_name, email=email)
    return SimpleNamespace(id=app_id, user=user)


def _make_prediction_result():
    return {
        "shap_values": {
            "credit_score": -0.35,
            "annual_income": -0.25,
            "debt_to_income": -0.18,
            "employment_length": -0.12,
            "loan_amount": -0.05,
        },
        "probability": 0.78,
        "model_version": "v3.1",
        "risk_grade": "E",
    }


def _make_model_version(
    is_active=True,
    algorithm="xgboost",
    version="3.1",
    traffic_percentage=100,
    **metric_overrides,
):
    defaults = {
        "id": 7,
        "is_active": is_active,
        "algorithm": algorithm,
        "version": version,
        "traffic_percentage": traffic_percentage,
        "created_at": datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
        "auc_roc": 0.87,
        "gini_coefficient": 0.74,
        "ks_statistic": 0.52,
        "f1_score": 0.81,
        "accuracy": 0.84,
        "brier_score": 0.12,
        "ece": 0.03,
    }
    defaults.update(metric_overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Adverse Action Notice Tests
# ---------------------------------------------------------------------------

class TestAdverseActionNotice:

    def test_notice_contains_all_required_fields(self):
        app = _make_application()
        pred = _make_prediction_result()

        notice = generate_adverse_action_notice(app, pred)

        required_fields = [
            "notice_type",
            "applicant_name",
            "application_id",
            "date",
            "decision",
            "principal_reasons",
            "model_version",
            "risk_grade",
            "right_to_request",
            "complaint_info",
            "shap_stability_note",
        ]
        for field in required_fields:
            assert field in notice, f"Missing required field: {field}"

        assert notice["notice_type"] == "adverse_action"
        assert notice["decision"] == "denied"
        assert notice["applicant_name"] == "Jane Doe"
        assert notice["application_id"] == "42"
        assert notice["model_version"] == "v3.1"
        assert notice["risk_grade"] == "E"

    def test_principal_reasons_respects_max_reasons(self):
        app = _make_application()
        pred = _make_prediction_result()

        notice = generate_adverse_action_notice(app, pred, max_reasons=2)
        assert len(notice["principal_reasons"]) <= 2

        notice4 = generate_adverse_action_notice(app, pred, max_reasons=4)
        assert len(notice4["principal_reasons"]) <= 4

    def test_raw_shap_values_not_in_consumer_notice(self):
        """CFPB requires specific reasons but raw SHAP values are internal."""
        app = _make_application()
        pred = _make_prediction_result()

        notice = generate_adverse_action_notice(app, pred)

        for reason in notice["principal_reasons"]:
            assert "contribution" not in reason, (
                "Raw SHAP contribution must not appear in consumer-facing notice"
            )
            # Verify only allowed keys
            assert set(reason.keys()) == {"code", "reason", "feature"}

    def test_notice_includes_right_to_request(self):
        app = _make_application()
        pred = _make_prediction_result()

        notice = generate_adverse_action_notice(app, pred)
        assert notice["right_to_request"] == RIGHT_TO_REQUEST_TEXT
        assert "30 days" in notice["right_to_request"]

    def test_notice_includes_afca_complaint_info(self):
        app = _make_application()
        pred = _make_prediction_result()

        notice = generate_adverse_action_notice(app, pred)
        assert notice["complaint_info"] == AFCA_COMPLAINT_TEXT
        assert "AFCA" in notice["complaint_info"]
        assert "1800 931 678" in notice["complaint_info"]

    def test_empty_shap_values_returns_no_reasons(self):
        app = _make_application()
        pred = {"shap_values": {}, "model_version": "v1", "risk_grade": "A"}

        notice = generate_adverse_action_notice(app, pred)
        assert notice["principal_reasons"] == []

    def test_missing_user_falls_back_gracefully(self):
        app = SimpleNamespace(id=99, user=None)
        pred = _make_prediction_result()

        notice = generate_adverse_action_notice(app, pred)
        assert notice["applicant_name"] == "Applicant"

    def test_date_is_iso_format(self):
        app = _make_application()
        pred = _make_prediction_result()

        notice = generate_adverse_action_notice(app, pred)
        # Should parse without error
        datetime.fromisoformat(notice["date"])


# ---------------------------------------------------------------------------
# Model Inventory Tests
# ---------------------------------------------------------------------------

class TestModelInventory:

    def test_inventory_contains_all_sr117_fields(self):
        mv = _make_model_version()
        entry = generate_model_inventory_entry(mv)

        required_fields = [
            "model_name",
            "model_id",
            "version",
            "algorithm",
            "risk_classification",
            "owner",
            "purpose",
            "status",
            "development_date",
            "last_validation_date",
            "next_validation_date",
            "performance_metrics",
            "data_sources",
            "known_limitations",
            "third_party_dependencies",
            "regulatory_references",
        ]
        for field in required_fields:
            assert field in entry, f"Missing SR 11-7 field: {field}"

        assert entry["risk_classification"] == "high"
        assert entry["purpose"] == "Consumer credit decisioning"
        assert entry["owner"] == "ML Engineering Team"

    def test_active_model_status(self):
        mv = _make_model_version(is_active=True)
        entry = generate_model_inventory_entry(mv)
        assert entry["status"] == "active"

    def test_inactive_model_status(self):
        mv = _make_model_version(is_active=False, traffic_percentage=0)
        entry = generate_model_inventory_entry(mv)
        assert entry["status"] == "inactive"

    def test_challenger_model_status(self):
        mv = _make_model_version(is_active=False, traffic_percentage=10)
        entry = generate_model_inventory_entry(mv)
        assert entry["status"] == "challenger"

    def test_performance_metrics_populated(self):
        mv = _make_model_version()
        entry = generate_model_inventory_entry(mv)

        metrics = entry["performance_metrics"]
        assert metrics["auc"] == 0.87
        assert metrics["gini"] == 0.74
        assert metrics["ks"] == 0.52
        assert metrics["f1"] == 0.81
        assert metrics["accuracy"] == 0.84
        assert metrics["brier"] == 0.12
        assert metrics["ece"] == 0.03

    def test_next_validation_is_one_year_after_creation(self):
        mv = _make_model_version()
        entry = generate_model_inventory_entry(mv)

        next_val = datetime.fromisoformat(entry["next_validation_date"])
        assert next_val.year == 2026
        assert next_val.month == 6
        assert next_val.day == 15

    def test_regulatory_references_include_key_regulations(self):
        mv = _make_model_version()
        entry = generate_model_inventory_entry(mv)

        refs = " ".join(entry["regulatory_references"])
        assert "SR 11-7" in refs
        assert "CFPB" in refs
        assert "NCCP" in refs
