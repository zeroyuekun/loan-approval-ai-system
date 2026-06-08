"""Tests for the validation sign-off gate dispatcher (Codex v1.10.7 finding 2).

Covers:
  - Mode-matrix dispatch (warn / block / off, plus unknown collapses to warn)
  - Decision against a real ModelVersion + ModelValidationReport pair
  - Force bypass on the dispatcher
  - End-to-end behaviour through ModelActivateView (?force=true and 409 on block)

See docs/superpowers/specs/2026-05-07-codex-adversarial-response-v1-10-7-design.md
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.loans.models import AuditLog
from apps.ml_engine.models import ModelValidationReport, ModelVersion
from apps.ml_engine.services.validation_gate_mode import (
    DEFAULT_MODE,
    VALID_MODES,
    ValidationDecision,
    ValidationSignoffBlocked,
    evaluate_validation_signoff_gate,
    normalize_mode,
)

# ---------------------------------------------------------------------------
# Pure-function tests for normalize_mode (no DB)
# ---------------------------------------------------------------------------


class TestNormalizeMode:
    def test_passes_valid_modes_through(self):
        for mode in VALID_MODES:
            assert normalize_mode(mode) == mode

    def test_collapses_unknown_to_warn(self, caplog):
        with caplog.at_level("WARNING"):
            assert normalize_mode("strict") == DEFAULT_MODE
        assert "Unknown ML_VALIDATION_SIGNOFF_GATE_MODE" in caplog.text

    def test_handles_none(self):
        assert normalize_mode(None) == DEFAULT_MODE


# ---------------------------------------------------------------------------
# DB-bound dispatcher tests
# ---------------------------------------------------------------------------


@pytest.fixture
def models_dir(tmp_path, settings):
    settings.ML_MODELS_DIR = str(tmp_path)
    return tmp_path


@pytest.fixture
def model_version(db, models_dir):
    file_path = models_dir / "v_signoff_test.joblib"
    file_path.write_bytes(b"\0" * 64)
    return ModelVersion.objects.create(
        algorithm="xgb",
        version="v_signoff_test",
        file_path=str(file_path),
        file_hash="b" * 64,
        is_active=False,
        segment=ModelVersion.SEGMENT_UNIFIED,
        traffic_percentage=0,
    )


def _make_report(model_version, *, signed_off: bool, outcome: str):
    return ModelValidationReport.objects.create(
        model_version=model_version,
        validator_name="Indep. Auditor",
        validator_role="Risk Manager",
        validation_date=dt.date.today(),
        outcome=outcome,
        methodology="Holdout test + AUC retention vs champion",
        signed_off=signed_off,
    )


@pytest.mark.django_db
class TestValidationGateDispatcher:
    def test_off_mode_skips_check(self, model_version):
        result = evaluate_validation_signoff_gate(model_version, mode="off")
        assert result["action"] == "skip_check"
        assert result["mode"] == "off"
        assert isinstance(result["decision"], ValidationDecision)
        assert result["decision"].result == "skipped"
        assert result["decision"].reason == "gate_off"

    def test_bypass_skips_check_and_records_bypass_reason(self, model_version):
        result = evaluate_validation_signoff_gate(model_version, mode="block", bypass=True)
        assert result["action"] == "skip_check"
        assert result["bypass"] is True
        assert result["decision"].reason == "bypass"

    def test_no_report_blocks_in_block_mode(self, model_version):
        with pytest.raises(ValidationSignoffBlocked) as exc_info:
            evaluate_validation_signoff_gate(model_version, mode="block")
        payload = exc_info.value.payload
        assert payload["result"] == "blocked"
        assert payload["reason"] == "no_report"

    def test_no_report_warns_but_proceeds_in_warn_mode(self, model_version):
        result = evaluate_validation_signoff_gate(model_version, mode="warn")
        assert result["action"] == "activate"
        assert result["decision"].result == "blocked"
        assert result["decision"].reason == "no_report"

    def test_unapproved_report_blocks_in_block_mode(self, model_version):
        _make_report(model_version, signed_off=True, outcome=ModelValidationReport.Outcome.CONDITIONAL)
        with pytest.raises(ValidationSignoffBlocked) as exc_info:
            evaluate_validation_signoff_gate(model_version, mode="block")
        assert exc_info.value.payload["reason"] == "report_not_approved"

    def test_unsigned_report_blocks_in_block_mode(self, model_version):
        _make_report(model_version, signed_off=False, outcome=ModelValidationReport.Outcome.APPROVED)
        with pytest.raises(ValidationSignoffBlocked) as exc_info:
            evaluate_validation_signoff_gate(model_version, mode="block")
        assert exc_info.value.payload["reason"] == "report_not_approved"

    def test_approved_signed_report_passes(self, model_version):
        report = _make_report(model_version, signed_off=True, outcome=ModelValidationReport.Outcome.APPROVED)
        result = evaluate_validation_signoff_gate(model_version, mode="block")
        assert result["action"] == "activate"
        assert result["decision"].result == "passed"
        assert result["decision"].report_id == str(report.id)


# ---------------------------------------------------------------------------
# End-to-end through ModelActivateView
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_user(db):
    return CustomUser.objects.create_user(
        username="admin_signoff",
        email="admin_signoff@test.com",
        password="x",
        role="admin",
        is_staff=True,
    )


@pytest.fixture
def authed_admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.mark.django_db
class TestModelActivateValidationGate:
    def test_block_mode_returns_409_without_report(self, authed_admin_client, model_version):
        with override_settings(ML_VALIDATION_SIGNOFF_GATE_MODE="block"):
            url = reverse("model-activate", kwargs={"pk": model_version.id})
            response = authed_admin_client.post(url)
        assert response.status_code == 409
        body = response.json()
        assert body["error"] == "validation_signoff_required"
        assert body["details"]["reason"] == "no_report"

        # Verify the row was NOT activated.
        model_version.refresh_from_db()
        assert model_version.is_active is False

    def test_force_bypass_activates_and_audits(self, authed_admin_client, model_version, admin_user):
        with override_settings(ML_VALIDATION_SIGNOFF_GATE_MODE="block"):
            url = reverse("model-activate", kwargs={"pk": model_version.id})
            response = authed_admin_client.post(url + "?force=true")
        assert response.status_code == 200, response.content

        model_version.refresh_from_db()
        assert model_version.is_active is True

        log = AuditLog.objects.filter(
            user=admin_user,
            action="model_activate_force",
            resource_id=str(model_version.id),
        ).first()
        assert log is not None
        assert log.details["force_bypass"] is True
        assert log.details["validation_gate_decision"]["reason"] == "bypass"

    def test_warn_mode_allows_activation_without_report(self, authed_admin_client, model_version):
        with override_settings(ML_VALIDATION_SIGNOFF_GATE_MODE="warn"):
            url = reverse("model-activate", kwargs={"pk": model_version.id})
            response = authed_admin_client.post(url)
        assert response.status_code == 200
        body = response.json()
        assert body["validation_gate"] == "warn"
        model_version.refresh_from_db()
        assert model_version.is_active is True

    def test_approved_report_passes_block_mode(self, authed_admin_client, model_version):
        _make_report(model_version, signed_off=True, outcome=ModelValidationReport.Outcome.APPROVED)
        with override_settings(ML_VALIDATION_SIGNOFF_GATE_MODE="block"):
            url = reverse("model-activate", kwargs={"pk": model_version.id})
            response = authed_admin_client.post(url)
        assert response.status_code == 200
        model_version.refresh_from_db()
        assert model_version.is_active is True
