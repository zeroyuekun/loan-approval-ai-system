import hashlib
import logging
from datetime import datetime, timedelta

import numpy as np
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.loans.models import LoanApplication, LoanDecision
from apps.ml_engine.models import DriftReport, ModelVersion, PredictionLog
from apps.ml_engine.services.governance.drift_monitor import compute_psi as _compute_psi

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="apps.ml_engine.tasks.train_model_task",
    time_limit=1800,
    soft_time_limit=1740,
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    max_retries=2,
)
def train_model_task(self, algorithm="xgb", data_path=None, segment=None):
    """Train a model asynchronously via Celery.

    `segment` (optional) narrows the training data to a single product
    segment (home_owner_occupier / home_investor / personal). When omitted
    the trainer produces a unified model that scores all applications.
    """
    import redis as _redis

    # Prevent concurrent training — acquire a Redis lock for 30 minutes
    redis_url = settings.CELERY_BROKER_URL
    redis_client = _redis.from_url(redis_url)
    lock = redis_client.lock("train_model_lock", timeout=1800, blocking=False)
    if not lock.acquire(blocking=False):
        logger.warning("Training already in progress — skipping duplicate task %s", self.request.id)
        return {"status": "skipped", "reason": "training_already_in_progress"}

    try:
        return _do_train(self, algorithm, data_path, lock, segment=segment)
    except Exception:
        logger.exception(
            "train_model_task failed for algorithm=%s version_id=%s",
            algorithm,
            self.request.id,
        )
        lock.release()
        raise


def _ensure_training_data(data_path, num_records=None):
    """Generate a synthetic training CSV at ``data_path`` if it is missing.

    "Train Model" reads the disposable .tmp/synthetic_loans.csv, which is
    gitignored and absent on a fresh clone or after .tmp is cleared. Rather than
    letting the trainer die with a cryptic FileNotFoundError, self-heal by
    generating a synthetic dataset on demand. Synthetic only — no live data or
    network calls. Callers hold the training lock, so there is no generation
    race. Returns True if a dataset was generated, False if one already existed.

    A 0-byte file is treated as missing: a torn/interrupted write would otherwise
    be trusted by an existence-only check and break every future run. The write
    itself is atomic (temp file + os.replace) so a partial CSV is never visible.
    """
    import os

    data_path = os.path.abspath(data_path)
    if os.path.exists(data_path) and os.path.getsize(data_path) > 0:
        return False

    from apps.ml_engine.services.datagen.data_generator import DataGenerator

    rows = num_records if num_records is not None else getattr(settings, "ML_AUTO_SEED_ROWS", 20000)
    logger.warning(
        "Training data %s not found — auto-generating %d synthetic rows (self-heal)",
        data_path,
        rows,
    )
    generator = DataGenerator()
    df = generator.generate(num_records=rows)
    # Atomic publish: write to a temp file in the same directory, then replace,
    # so an interrupted write never leaves a partial CSV the existence check
    # above would wrongly trust on the next run.
    tmp_path = f"{data_path}.tmp.{os.getpid()}"
    generator.save_to_csv(df, tmp_path)
    os.replace(tmp_path, data_path)
    logger.info("Auto-generated training dataset: %d rows -> %s", len(df), data_path)
    return True


def _do_train(task, algorithm, data_path, lock, *, segment=None):
    """Inner training logic — called with lock held."""
    from types import SimpleNamespace

    from apps.ml_engine.services.governance.fairness_gate_mode import (
        evaluate_fairness_gate_for_activation,
    )
    from apps.ml_engine.services.governance.promotion_gate_mode import (
        evaluate_promotion_gates_for_activation,
    )
    from apps.ml_engine.services.model_selector import promote_if_eligible
    from apps.ml_engine.services.scoring.predictor import clear_model_cache
    from apps.ml_engine.services.scoring.segmentation import SEGMENT_UNIFIED
    from apps.ml_engine.services.training.trainer import ModelTrainer
    from apps.ml_engine.services.validation_gate_mode import (
        ValidationSignoffBlocked,
        evaluate_validation_signoff_gate,
    )

    if data_path is None:
        data_path = str(settings.BASE_DIR / ".tmp" / "synthetic_loans.csv")

    # Self-heal: a fresh clone or cleared .tmp has no training CSV. Generate one
    # rather than failing the run with a cryptic FileNotFoundError.
    _ensure_training_data(data_path)

    segment = segment or SEGMENT_UNIFIED
    trainer = ModelTrainer()
    model, metrics = trainer.train(data_path, algorithm=algorithm, segment=segment)

    version_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_filename = f"{algorithm}_{version_str}.joblib"
    model_path = str(settings.ML_MODELS_DIR / model_filename)
    trainer.save_model(model, model_path)

    # Compute SHA-256 hash of saved model file for integrity verification
    sha256 = hashlib.sha256()
    with open(model_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    file_hash = sha256.hexdigest()

    # Pre-activation fairness gate. In `block` mode this raises
    # FairnessGateBlocked BEFORE the atomic activation block — old segment
    # models stay `is_active=True` because we never enter the transaction
    # below. The outer `train_model_task` wrapper releases the training
    # lock on the raise path. See
    # docs/superpowers/specs/2026-05-07-ml-fairness-gate-mode-design.md.
    fairness_data = metrics.get("fairness", {})
    gate_mode = getattr(settings, "ML_FAIRNESS_GATE_MODE", "warn")
    gate_decision = evaluate_fairness_gate_for_activation(fairness_data, gate_mode)

    # Pre-activation champion-challenger promotion gates. Build a transient
    # candidate stub from the in-memory metrics — promote_if_eligible reads
    # via getattr + training_metadata, no DB write needed. The pk=None makes
    # the .exclude(pk=...) clause inside promote_if_eligible a no-op which is
    # correct here (we want the existing active model excluded only if it
    # shares pk with us). In `block` mode this raises PromotionGateBlocked
    # BEFORE the atomic activation block. See
    # docs/superpowers/specs/2026-05-07-ml-promotion-gate-mode-design.md.
    candidate_stub = SimpleNamespace(
        id="(pre-activation)",
        pk=None,
        segment=segment,
        auc_roc=metrics["auc_roc"],
        ks_statistic=metrics["ks_statistic"],
        ece=metrics.get("calibration_data", {}).get("ece"),
        training_metadata=metrics.get("training_metadata", {}),
    )
    promotion_decision = promote_if_eligible(candidate_stub)
    promotion_mode = getattr(settings, "ML_PROMOTION_GATE_MODE", "warn")
    promotion_gate_decision = evaluate_promotion_gates_for_activation(promotion_decision, promotion_mode)

    # Deactivate old models and activate new one atomically — if create()
    # fails, the old active model remains active (no zero-model gap).
    from django.db import transaction

    with transaction.atomic():
        # Scope deactivation to the same segment so training a new
        # personal-loan model doesn't knock out the active home-loan model.
        ModelVersion.objects.filter(is_active=True, segment=segment).update(is_active=False, traffic_percentage=0)
        mv = ModelVersion.objects.create(
            algorithm=algorithm,
            version=version_str,
            file_path=model_path,
            file_hash=file_hash,
            is_active=True,
            segment=segment,
            accuracy=metrics["accuracy"],
            precision=metrics["precision"],
            recall=metrics["recall"],
            f1_score=metrics["f1_score"],
            auc_roc=metrics["auc_roc"],
            brier_score=metrics.get("brier_score"),
            gini_coefficient=metrics.get("gini_coefficient"),
            ks_statistic=metrics.get("ks_statistic"),
            log_loss_value=metrics.get("log_loss"),
            ece=metrics.get("calibration_data", {}).get("ece"),
            optimal_threshold=metrics.get("threshold_analysis", {}).get("youden_j_threshold"),
            confusion_matrix=metrics["confusion_matrix"],
            feature_importances=metrics["feature_importances"],
            roc_curve_data=metrics["roc_curve"],
            training_params=metrics["training_params"],
            calibration_data=metrics.get("calibration_data", {}),
            threshold_analysis=metrics.get("threshold_analysis", {}),
            decile_analysis=metrics.get("decile_analysis", {}),
            fairness_metrics=metrics.get("fairness", {}),
            training_metadata=metrics.get("training_metadata", {}),
            retraining_policy={
                "cadence_days": 90,
                "min_samples": 10000,
                "auc_improvement_threshold": 0.005,
                "max_psi_before_retrain": 0.25,
                "requires_fairness_audit": True,
                "validation": "New model AUC must exceed current model by 0.5% on holdout set",
            },
            next_review_date=(timezone.now() + timedelta(days=90)).date(),
        )

    # Validation sign-off gate (Codex v1.10.7 finding 2). The candidate now
    # has a real PK so the gate can query ModelValidationReport. In `block`
    # mode the gate raises — at training time there is by construction no
    # approved sign-off (the row was just created), so block mode demotes
    # the candidate to is_active=False rather than re-raising past the
    # already-completed activation transaction. Operators then create +
    # sign off a report and manually activate via ModelActivateView.
    validation_mode = getattr(settings, "ML_VALIDATION_SIGNOFF_GATE_MODE", "warn")
    validation_blocked_demoted = False
    try:
        validation_gate_decision = evaluate_validation_signoff_gate(mv, validation_mode)
    except ValidationSignoffBlocked as exc:
        logger.warning(
            "Model %s training-path activation blocked by validation gate: %s. "
            "Candidate retained as is_active=False; manual activation required after sign-off.",
            mv.id,
            exc,
        )
        ModelVersion.objects.filter(pk=mv.pk).update(is_active=False, traffic_percentage=0)
        mv.refresh_from_db()
        validation_gate_decision = {
            "action": "blocked_demoted",
            "decision": exc.payload,
            "mode": "block",
            "bypass": False,
        }
        validation_blocked_demoted = True

    # Record the gate decisions (mode + result) on the activated mv so the
    # MRM dossier §1 banner has the audit trail for both gates. In `warn`
    # mode a failed gate is logged + flagged; activation already happened.
    gate_meta = {
        **(mv.training_metadata or {}),
        "fairness_gate_mode": gate_decision["mode"],
        "promotion_gate_mode": promotion_gate_decision["mode"],
        "validation_gate_mode": validation_gate_decision["mode"],
    }
    validation_decision_payload = validation_gate_decision.get("decision")
    if validation_decision_payload is not None:
        gate_meta["validation_gate"] = (
            validation_decision_payload.to_dict()
            if hasattr(validation_decision_payload, "to_dict")
            else validation_decision_payload
        )
    if validation_blocked_demoted:
        gate_meta["validation_gate_blocked_demoted"] = True
    gate_result = gate_decision["gate_result"]
    if gate_result is not None:
        gate_meta["fairness_gate"] = gate_result
        if not gate_result["passed"]:
            logger.warning(
                "Model %s FAILED fairness gate (mode=%s, failing: %s, min DIR: %s). "
                "Model remains active but flagged for human review.",
                mv.id,
                gate_decision["mode"],
                gate_result["failing_attributes"],
                gate_result["minimum_dir"],
            )
            gate_meta["requires_fairness_review"] = True

    # Promotion gate decision — record only when the dispatcher inspected it
    # (None when mode == "off"). In `warn` mode log a clear line if rejected
    # so audit trails capture the regression-vs-champion verdict even though
    # activation proceeded.
    promo_decision_payload = promotion_gate_decision["decision"]
    if promo_decision_payload is not None:
        gate_meta["promotion_gate"] = promo_decision_payload.to_dict()
        if not promo_decision_payload.promoted:
            logger.warning(
                "Model %s REJECTED by promotion gates (mode=%s, reasons: %s). "
                "Model remains active but flagged for human review.",
                mv.id,
                promotion_gate_decision["mode"],
                "; ".join(promo_decision_payload.reasons),
            )
            gate_meta["requires_promotion_review"] = True
    mv.training_metadata = gate_meta
    mv.save(update_fields=["training_metadata"])

    # Invalidate cached models so workers pick up the new version
    clear_model_cache()

    # Release the training lock
    try:
        lock.release()
    except Exception as exc:
        logger.debug(
            "training_lock_release_noop",
            extra={"model_version_id": str(mv.id), "error": str(exc)},
        )

    return {"model_version_id": str(mv.id), "metrics": metrics}


@shared_task(
    bind=True,
    name="apps.ml_engine.tasks.run_prediction_task",
    time_limit=120,
    soft_time_limit=100,
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    max_retries=2,
)
def run_prediction_task(self, application_id):
    """Run ML prediction on a loan application."""
    from apps.ml_engine.services.scoring.predictor import ModelPredictor

    application = LoanApplication.objects.get(pk=application_id)
    try:
        application.transition_to("processing")
    except LoanApplication.InvalidStateTransition:
        logger.info(
            "Skipping prediction for application %s — status '%s' cannot transition to processing",
            application_id,
            application.status,
        )
        return {"application_id": str(application_id), "status": "skipped", "reason": application.status}

    try:
        predictor = ModelPredictor.for_application(application)
        result = predictor.predict(application)
    except ValueError as e:
        # No active model available — not a transient error; do not retry.
        # Revert to pending so the application can be processed once a model
        # is activated, and return a structured skipped result.
        logger.error(
            "run_prediction_task: no active model for application %s — %s",
            application_id,
            e,
        )
        application.status = "pending"
        application.save(update_fields=["status"])
        return {"status": "skipped", "reason": "no_active_model", "detail": str(e)}
    except Exception:
        # Revert status so the application isn't stuck in 'processing'
        application.transition_to("pending", details={"reason": "prediction_failed"})
        raise

    # Save prediction log
    PredictionLog.objects.create(
        model_version_id=result["model_version"],
        application=application,
        prediction=result["prediction"],
        probability=result["probability"],
        feature_importances=result["feature_importances"],
        processing_time_ms=result["processing_time_ms"],
    )

    # Save loan decision
    LoanDecision.objects.update_or_create(
        application=application,
        defaults={
            "decision": result["prediction"],
            "confidence": result["probability"],
            "feature_importances": result["feature_importances"],
            "shap_values": result.get("shap_values", {}),
            "decision_waterfall": [],
            "model_version": result["model_version"],
        },
    )

    # Flag borderline cases for human review ONLY when the standalone path is
    # explicitly enabled. The standalone task creates no escalated AgentRun, so
    # a 'review' transition here would be unresumable and would leave the ADM
    # disclosure stale (Phase-1 Issue 1). Default: apply the raw decision.
    standalone_enabled = getattr(settings, "ML_STANDALONE_PREDICT_ENABLED", False)
    if standalone_enabled and result.get("requires_human_review"):
        application.transition_to("review")
    else:
        application.transition_to(result["prediction"])

    return {
        "application_id": str(application_id),
        "prediction": result["prediction"],
        "probability": result["probability"],
    }


@shared_task(bind=True, name="apps.ml_engine.tasks.check_fairness_violations", time_limit=300, soft_time_limit=280)
def check_fairness_violations(self):
    """Weekly check of disparate impact ratios against the EEOC 80% rule.

    Creates an AuditLog entry for any active model whose fairness metrics
    show a disparate impact ratio below the configured threshold.
    """
    from apps.loans.models import AuditLog

    threshold = getattr(settings, "ML_FAIRNESS_TARGET_DI", 0.80)
    active_models = ModelVersion.objects.filter(is_active=True)

    violations = []
    for mv in active_models:
        fairness = mv.fairness_metrics or {}
        for attr, data in fairness.items():
            if not isinstance(data, dict):
                continue
            di_ratio = data.get("disparate_impact_ratio")
            if di_ratio is not None and di_ratio < threshold:
                violations.append(
                    {
                        "model_version": str(mv.id),
                        "algorithm": mv.algorithm,
                        "attribute": attr,
                        "disparate_impact_ratio": round(di_ratio, 4),
                        "threshold": threshold,
                    }
                )

    if violations:
        logger.warning(
            "Fairness violations detected: %d attribute(s) below %.0f%% DI threshold",
            len(violations),
            threshold * 100,
        )
        AuditLog.objects.create(
            action="fairness_violation_detected",
            resource_type="ModelVersion",
            resource_id=",".join(set(v["model_version"] for v in violations)),
            details={
                "violations": violations,
                "threshold": threshold,
                "checked_at": timezone.now().isoformat(),
            },
        )
    else:
        logger.info("Fairness check passed: all active models above %.0f%% DI threshold", threshold * 100)

    return {
        "status": "violations_found" if violations else "all_clear",
        "violation_count": len(violations),
        "violations": violations,
    }


@shared_task(bind=True, name="apps.ml_engine.tasks.compute_weekly_drift_report", time_limit=600, soft_time_limit=580)
def compute_weekly_drift_report(self):
    """Compute weekly drift report comparing recent predictions to training distribution."""
    active_version = ModelVersion.objects.filter(is_active=True).first()
    if not active_version:
        logger.warning("No active model version found; skipping drift report.")
        return {"status": "skipped", "reason": "no_active_model"}

    now = timezone.now().date()
    period_end = now
    period_start = now - timedelta(days=7)

    predictions = PredictionLog.objects.filter(
        model_version=active_version,
        created_at__date__gte=period_start,
        created_at__date__lte=period_end,
    )

    num_predictions = predictions.count()
    if num_predictions == 0:
        logger.info("No predictions in the last 7 days; skipping drift report.")
        return {"status": "skipped", "reason": "no_predictions"}

    probabilities = np.array(list(predictions.values_list("probability", flat=True)), dtype=float)

    # Compute prediction distribution stats
    mean_prob = float(np.mean(probabilities))
    std_prob = float(np.std(probabilities))
    # Approval rate from the ACTUAL recorded decisions (which already encode
    # group-adjusted thresholds + pricing-overlay denials), not a flat 0.5 cut
    # on raw probabilities — matches the on-demand approval-rate computation.
    approval_rate = predictions.filter(prediction="approved").count() / num_predictions

    # Compute PSI against training reference distribution
    training_meta = active_version.training_metadata or {}
    reference_probs = training_meta.get("reference_probabilities")

    psi_score = None
    psi_per_feature = {}

    if reference_probs:
        ref_array = np.array(reference_probs, dtype=float)
        psi_score = _compute_psi(ref_array, probabilities)

        # Per-feature PSI is surfaced via the on-demand /drift/ endpoint
        # (compute_on_demand_feature_psi); this weekly task tracks score-level PSI.

    # Determine alert level
    if psi_score is not None and psi_score >= 0.25:
        drift_detected = True
        alert_level = "significant"
    elif psi_score is not None and psi_score >= 0.1:
        drift_detected = True
        alert_level = "moderate"
    else:
        drift_detected = False
        alert_level = "none"

    report = DriftReport.objects.update_or_create(
        model_version=active_version,
        report_date=now,
        defaults={
            "period_start": period_start,
            "period_end": period_end,
            "num_predictions": num_predictions,
            "psi_score": psi_score,
            "psi_per_feature": psi_per_feature,
            "mean_probability": mean_prob,
            "std_probability": std_prob,
            "approval_rate": approval_rate,
            "drift_detected": drift_detected,
            "alert_level": alert_level,
        },
    )[0]

    if psi_score is not None and psi_score >= 0.25:
        logger.warning(
            "Significant model drift detected: PSI=%.4f for model %s (report %s)",
            psi_score,
            active_version.id,
            report.id,
        )

    return {
        "status": "completed",
        "report_id": str(report.id),
        "psi_score": psi_score,
        "alert_level": alert_level,
        "num_predictions": num_predictions,
    }


@shared_task(
    bind=True,
    name="apps.ml_engine.tasks.generate_mrm_dossier_task",
    time_limit=300,
    soft_time_limit=280,
    autoretry_for=(OSError,),
    retry_backoff=True,
    max_retries=1,
)
def generate_mrm_dossier_task(self, model_version_id: str):
    """Generate an MRM dossier for a ModelVersion on the `ml` queue.

    Invoked from the post_save signal on ModelVersion. Non-blocking:
    failures log a warning but do not surface back to the caller that
    created the model. Idempotent — overwriting an existing dossier is
    the correct behaviour when the metrics payload changes (e.g. a
    post-training fairness update calls save() again).
    """
    try:
        mv = ModelVersion.objects.get(pk=model_version_id)
    except ModelVersion.DoesNotExist:
        logger.warning("generate_mrm_dossier_task: ModelVersion %s not found", model_version_id)
        return {"status": "skipped", "reason": "model_not_found"}

    from apps.ml_engine.services.governance.mrm_dossier import write_dossier

    output_dir = str(settings.ML_MODELS_DIR)
    try:
        path = write_dossier(mv, output_dir)
    except Exception as exc:
        logger.warning(
            "generate_mrm_dossier_task: failed for %s: %s",
            model_version_id,
            exc,
            exc_info=True,
        )
        return {"status": "failed", "error": str(exc)}

    logger.info("MRM dossier written for model %s → %s", model_version_id, path)
    return {"status": "ok", "path": path}
