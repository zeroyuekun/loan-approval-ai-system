"""One activation service for every path that changes which model serves.

Activation used to be implemented four times (training task, activate view,
traffic view, train_model command) with different gates, scoping, locking
and audit:

- I1: in block mode the training task deactivated the champion, created
  the candidate active, and only then ran the validation gate, which always
  fails at training time, so it demoted the candidate and left the segment
  with no active model.
- I7: PATCH /traffic/ could switch the live model with no gate, no audit
  and no artefact check (and accepted ``True`` as 1%).
- I8: activation never checked the artefact existed, so activating a row
  whose .joblib had been pruned broke every prediction in the segment.
- M6: no lock, so two concurrent activations could leave two champions.
- train_model: no lock, no gates, no segment, deactivated every segment,
  left retired rows at traffic 100.
"""

from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.loans.models import AuditLog
from apps.ml_engine.models import ModelValidationReport, ModelVersion
from apps.ml_engine.services.activation import (
    ActivationBlocked,
    ArtefactUnusable,
    activate_model_version,
)
from apps.ml_engine.services.scoring.prediction_cache import file_sha256

pytestmark = pytest.mark.django_db

PASSING_FAIRNESS = {
    "employment_type": {"disparate_impact_ratio": 0.95, "groups": {"a": {"count": 200}, "b": {"count": 200}}}
}


@pytest.fixture
def models_dir(tmp_path, settings):
    settings.ML_MODELS_DIR = tmp_path
    settings.MRM_DOSSIER_AUTO_GENERATE = False
    return tmp_path


def make_mv(models_dir, name, *, active=False, traffic=0, segment="unified", hashed=True, **fields):
    path = models_dir / f"{name}.joblib"
    path.write_bytes(name.encode() * 8)
    return ModelVersion.objects.create(
        algorithm="xgb",
        version=name,
        file_path=str(path),
        file_hash=file_sha256(path) if hashed else "",
        is_active=active,
        traffic_percentage=traffic,
        segment=segment,
        auc_roc=0.85,
        ks_statistic=0.5,
        ece=0.01,
        training_metadata={"psi_by_feature": {"x": 0.01}},
        **fields,
    )


@pytest.fixture
def admin_user(db):
    return CustomUser.objects.create_user(username="act_admin", email="act@x.com", password="x", role="admin")


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(admin_user)
    return client


def _approve(mv):
    ModelValidationReport.objects.create(
        model_version=mv,
        validator_name="Indep",
        validator_role="Risk",
        validation_date=dt.date.today(),
        outcome=ModelValidationReport.Outcome.APPROVED,
        methodology="holdout",
        signed_off=True,
    )


# --- the service --------------------------------------------------------------


def test_activation_promotes_the_candidate_and_retires_the_segment_champion(models_dir, admin_user):
    champion = make_mv(models_dir, "champ", active=True, traffic=100)
    other_segment = make_mv(models_dir, "home", active=True, traffic=100, segment="personal")
    candidate = make_mv(models_dir, "cand")

    activate_model_version(candidate, actor=admin_user, source="api")

    champion.refresh_from_db()
    candidate.refresh_from_db()
    other_segment.refresh_from_db()
    assert (candidate.is_active, candidate.traffic_percentage) == (True, 100)
    assert (champion.is_active, champion.traffic_percentage) == (False, 0)
    assert (other_segment.is_active, other_segment.traffic_percentage) == (True, 100)

    log = AuditLog.objects.get(action="model_activate", resource_id=str(candidate.id))
    assert log.user == admin_user
    assert log.details["source"] == "api"
    assert log.details["segment"] == "unified"
    assert log.details["previous_active_ids"] == [str(champion.id)]


def test_activation_refuses_a_missing_artefact_and_keeps_the_champion(models_dir):
    champion = make_mv(models_dir, "champ", active=True, traffic=100)
    pruned = make_mv(models_dir, "pruned")
    (models_dir / "pruned.joblib").unlink()

    with pytest.raises(ArtefactUnusable):
        activate_model_version(pruned, actor=None, source="api")

    champion.refresh_from_db()
    assert champion.is_active and champion.traffic_percentage == 100


def test_activation_refuses_an_artefact_whose_hash_does_not_match(models_dir):
    champion = make_mv(models_dir, "champ", active=True, traffic=100)
    tampered = make_mv(models_dir, "tampered")
    (models_dir / "tampered.joblib").write_bytes(b"swapped")

    with pytest.raises(ArtefactUnusable):
        activate_model_version(tampered, actor=None, source="api")

    champion.refresh_from_db()
    assert champion.is_active


@override_settings(ML_VALIDATION_SIGNOFF_GATE_MODE="block")
def test_block_mode_gate_refuses_activation_and_keeps_the_champion(models_dir):
    champion = make_mv(models_dir, "champ", active=True, traffic=100)
    candidate = make_mv(models_dir, "cand")

    with pytest.raises(ActivationBlocked) as exc:
        activate_model_version(candidate, actor=None, source="api")

    assert exc.value.blocked_gates == ["validation"]
    champion.refresh_from_db()
    candidate.refresh_from_db()
    assert champion.is_active and not candidate.is_active
    assert AuditLog.objects.filter(action="model_activation_blocked", resource_id=str(candidate.id)).exists()


@override_settings(ML_FAIRNESS_GATE_MODE="block")
def test_block_mode_fairness_gate_applies_to_manual_activation(models_dir):
    failing = {"employment_type": {"disparate_impact_ratio": 0.5, "groups": {"a": {"count": 200}, "b": {"count": 200}}}}
    candidate = make_mv(models_dir, "cand", fairness_metrics=failing)

    with pytest.raises(ActivationBlocked) as exc:
        activate_model_version(candidate, actor=None, source="api")
    assert "fairness" in exc.value.blocked_gates


@override_settings(ML_VALIDATION_SIGNOFF_GATE_MODE="block")
def test_force_bypasses_the_governance_gates_but_not_the_artefact_check(models_dir, admin_user):
    candidate = make_mv(models_dir, "cand")
    activate_model_version(candidate, actor=admin_user, source="api", force=True)
    candidate.refresh_from_db()
    assert candidate.is_active
    log = AuditLog.objects.get(action="model_activate_force", resource_id=str(candidate.id))
    assert log.details["force_bypass"] is True

    gone = make_mv(models_dir, "gone")
    (models_dir / "gone.joblib").unlink()
    with pytest.raises(ArtefactUnusable):
        activate_model_version(gone, actor=admin_user, source="api", force=True)


@override_settings(ML_VALIDATION_SIGNOFF_GATE_MODE="block")
def test_approved_candidate_passes_block_mode(models_dir):
    candidate = make_mv(models_dir, "cand", fairness_metrics=PASSING_FAIRNESS)
    _approve(candidate)
    activate_model_version(candidate, actor=None, source="api")
    candidate.refresh_from_db()
    assert candidate.is_active


def _stale(mv, computed_at=0.5, serving_at=0.87):
    mv.optimal_threshold = serving_at
    mv.training_metadata = {**mv.training_metadata, "metrics_threshold": computed_at}
    mv.save(update_fields=["optimal_threshold", "training_metadata"])
    return mv


@override_settings(ML_FAIRNESS_GATE_MODE="block")
def test_block_mode_refuses_fairness_evidence_computed_at_another_threshold(models_dir):
    """Migration 0010 moved legacy models' threshold, not the metrics computed at the old one."""
    candidate = _stale(make_mv(models_dir, "stale", fairness_metrics=PASSING_FAIRNESS))
    _approve(candidate)

    with pytest.raises(ActivationBlocked) as exc:
        activate_model_version(candidate, actor=None, source="api")

    assert "fairness" in exc.value.blocked_gates
    candidate.refresh_from_db()
    assert not candidate.is_active


@override_settings(ML_FAIRNESS_GATE_MODE="warn")
def test_warn_mode_records_stale_fairness_evidence(models_dir):
    candidate = _stale(make_mv(models_dir, "stale_warn", fairness_metrics=PASSING_FAIRNESS))
    _approve(candidate)

    gates = activate_model_version(candidate, actor=None, source="api")

    assert gates["fairness"]["stale_metrics"] == {"computed_at": 0.5, "serving_at": 0.87}
    candidate.refresh_from_db()
    assert candidate.is_active


def test_metrics_computed_at_the_serving_threshold_are_not_stale(models_dir):
    same = _stale(make_mv(models_dir, "same"), computed_at=0.87, serving_at=0.87)
    unrecorded = make_mv(models_dir, "unrecorded")
    assert same.stale_metrics_threshold() is None
    assert unrecorded.stale_metrics_threshold() is None


def test_weekly_fairness_check_reports_models_serving_on_stale_metrics(models_dir):
    from apps.ml_engine.tasks import check_fairness_violations

    _stale(make_mv(models_dir, "live_stale", active=True, traffic=100, fairness_metrics=PASSING_FAIRNESS))

    result = check_fairness_violations.apply().get()

    assert [m["version"] for m in result["stale_metrics"]] == ["live_stale"]
    assert AuditLog.objects.filter(action="fairness_metrics_stale").exists()


# --- traffic endpoint (I7) ----------------------------------------------------


@pytest.mark.parametrize("value", [True, 50.9, "50", -1, 101])
def test_traffic_rejects_values_that_are_not_an_integer_percentage(models_dir, admin_client, value):
    mv = make_mv(models_dir, "champ", active=True, traffic=100)
    response = admin_client.patch(f"/api/v1/ml/models/{mv.id}/traffic/", {"traffic_percentage": value}, format="json")
    assert response.status_code == 400


@override_settings(ML_VALIDATION_SIGNOFF_GATE_MODE="block")
def test_traffic_cannot_put_an_unvalidated_model_live(models_dir, admin_client):
    champion = make_mv(models_dir, "champ", active=True, traffic=70)
    challenger = make_mv(models_dir, "chall")

    response = admin_client.patch(
        f"/api/v1/ml/models/{challenger.id}/traffic/", {"traffic_percentage": 30}, format="json"
    )

    assert response.status_code == 409
    challenger.refresh_from_db()
    assert not challenger.is_active
    champion.refresh_from_db()
    assert champion.traffic_percentage == 70


def test_traffic_change_is_audited(models_dir, admin_client, admin_user):
    champion = make_mv(models_dir, "champ", active=True, traffic=100)
    response = admin_client.patch(
        f"/api/v1/ml/models/{champion.id}/traffic/", {"traffic_percentage": 70}, format="json"
    )
    assert response.status_code == 200
    log = AuditLog.objects.get(action="model_traffic_change", resource_id=str(champion.id))
    assert log.user == admin_user
    assert (log.details["from"], log.details["to"]) == (100, 70)


def test_traffic_zero_on_the_only_live_model_is_refused(models_dir, admin_client):
    champion = make_mv(models_dir, "champ", active=True, traffic=100)
    response = admin_client.patch(f"/api/v1/ml/models/{champion.id}/traffic/", {"traffic_percentage": 0}, format="json")
    assert response.status_code == 409
    champion.refresh_from_db()
    assert champion.is_active and champion.traffic_percentage == 100


def test_traffic_zero_retires_a_challenger(models_dir, admin_client):
    make_mv(models_dir, "champ", active=True, traffic=70)
    challenger = make_mv(models_dir, "chall", active=True, traffic=30)
    response = admin_client.patch(
        f"/api/v1/ml/models/{challenger.id}/traffic/", {"traffic_percentage": 0}, format="json"
    )
    assert response.status_code == 200
    challenger.refresh_from_db()
    assert (challenger.is_active, challenger.traffic_percentage) == (False, 0)


def test_activate_view_refuses_a_pruned_artefact(models_dir, admin_client):
    champion = make_mv(models_dir, "champ", active=True, traffic=100)
    pruned = make_mv(models_dir, "pruned")
    (models_dir / "pruned.joblib").unlink()
    response = admin_client.post(f"/api/v1/ml/models/{pruned.id}/activate/")
    assert response.status_code == 409
    assert response.json()["error"] == "artefact_unusable"
    champion.refresh_from_db()
    assert champion.is_active


# --- training paths (I1, train_model command) -----------------------------------


class _FakeTrainer:
    """Stands in for ModelTrainer: writes a small artefact, returns metrics."""

    def train(self, data_path, algorithm="xgb", segment=None):
        return object(), {
            "accuracy": 0.8,
            "precision": 0.8,
            "recall": 0.8,
            "f1_score": 0.8,
            "auc_roc": 0.85,
            "ks_statistic": 0.5,
            "optimal_threshold": 0.6,
            "confusion_matrix": {},
            "feature_importances": {},
            "roc_curve": {},
            "training_params": {},
            "calibration_data": {"ece": 0.01},
            "fairness": PASSING_FAIRNESS,
            "training_metadata": {"psi_by_feature": {"x": 0.01}, "segment": segment or "unified"},
        }

    def save_model(self, model, path):
        with open(path, "wb") as f:
            f.write(b"fake-bundle")


@pytest.fixture
def fake_training(models_dir, tmp_path):
    data = tmp_path / "data.csv"
    data.write_text("x\n1\n")
    with (
        patch("apps.ml_engine.services.training.trainer.ModelTrainer", _FakeTrainer),
        patch("apps.ml_engine.services.scoring.predictor.clear_model_cache"),
    ):
        yield str(data)


@override_settings(ML_VALIDATION_SIGNOFF_GATE_MODE="block")
def test_block_mode_training_keeps_the_champion_serving(models_dir, fake_training):
    from apps.ml_engine.tasks import _do_train

    champion = make_mv(models_dir, "champ", active=True, traffic=100)

    result = _do_train(MagicMock(), "xgb", fake_training, MagicMock())

    # The task result names the blocking gates so the Train Model UI can say
    # why the new model is not serving, instead of reporting plain success.
    assert result["activated"] is False
    assert result["activation_blocked"] == ["validation"]
    champion.refresh_from_db()
    assert champion.is_active and champion.traffic_percentage == 100
    candidate = ModelVersion.objects.exclude(pk=champion.pk).get()
    assert (candidate.is_active, candidate.traffic_percentage) == (False, 0)
    assert candidate.training_metadata["activation_blocked"] == ["validation"]
    assert candidate.training_metadata["validation_gate"]["reason"] == "no_report"


def test_warn_mode_training_activates_and_records_the_gates(models_dir, fake_training):
    from apps.ml_engine.tasks import _do_train

    champion = make_mv(models_dir, "champ", active=True, traffic=100)

    result = _do_train(MagicMock(), "xgb", fake_training, MagicMock())

    assert result["activated"] is True
    assert result["activation_blocked"] == []
    champion.refresh_from_db()
    candidate = ModelVersion.objects.exclude(pk=champion.pk).get()
    assert (candidate.is_active, candidate.traffic_percentage) == (True, 100)
    assert (champion.is_active, champion.traffic_percentage) == (False, 0)
    meta = candidate.training_metadata
    assert meta["fairness_gate_mode"] == "warn"
    assert meta["promotion_gate_mode"] == "warn"
    assert meta["validation_gate_mode"] == "warn"
    assert meta["fairness_gate"]["passed"] is True
    assert AuditLog.objects.filter(action="model_activate", resource_id=str(candidate.id)).exists()


def test_train_model_command_uses_the_activation_service(models_dir, fake_training):
    unified = make_mv(models_dir, "unified_champ", active=True, traffic=100)
    personal = make_mv(models_dir, "personal_champ", active=True, traffic=100, segment="personal")

    with patch("apps.ml_engine.tasks.acquire_train_lock", return_value=MagicMock()):
        call_command("train_model", algorithm="xgb", data_path=fake_training)

    unified.refresh_from_db()
    personal.refresh_from_db()
    new = ModelVersion.objects.exclude(pk__in=[unified.pk, personal.pk]).get()
    assert new.segment == "unified" and new.is_active and new.traffic_percentage == 100
    assert (unified.is_active, unified.traffic_percentage) == (False, 0)
    assert (personal.is_active, personal.traffic_percentage) == (True, 100)
    assert "fairness_gate_mode" in new.training_metadata


def test_train_model_command_refuses_while_a_training_run_holds_the_lock(models_dir, fake_training):
    with (
        patch("apps.ml_engine.tasks.acquire_train_lock", return_value=None),
        pytest.raises(CommandError, match="already in progress"),
    ):
        call_command("train_model", algorithm="xgb", data_path=fake_training)
    assert not ModelVersion.objects.exists()


def test_mrm_dossier_is_queued_only_after_the_registration_commits(
    models_dir, settings, django_capture_on_commit_callbacks
):
    """M8: the dossier task was queued from post_save inside the training
    transaction, so a worker could read before commit (model_not_found) or
    before the gate verdicts were saved."""
    settings.MRM_DOSSIER_AUTO_GENERATE = True
    with (
        patch("apps.ml_engine.tasks.generate_mrm_dossier_task.delay") as delay,
        django_capture_on_commit_callbacks(execute=False) as callbacks,
    ):
        make_mv(models_dir, "dossier")
        assert not delay.called
    assert len(callbacks) == 1
