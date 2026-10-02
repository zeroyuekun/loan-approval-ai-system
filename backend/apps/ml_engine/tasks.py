import logging
from datetime import datetime, timedelta

import numpy as np
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.loans.models import LoanApplication, LoanDecision
from apps.ml_engine.models import DriftReport, ModelVersion, PredictionLog
from apps.ml_engine.services.governance.drift_monitor import PSI_INVESTIGATE, PSI_STABLE
from apps.ml_engine.services.governance.drift_monitor import compute_psi as _compute_psi
from apps.ml_engine.services.scoring.prediction_cache import file_sha256

logger = logging.getLogger(__name__)

# Redis lock held for the duration of a training run. TrainModelView checks the
# same key to reject duplicate requests before queueing a task.
TRAIN_LOCK_KEY = "train_model_lock"


def model_version_metric_fields(metrics: dict) -> dict:
    """ModelVersion fields populated from a trainer ``metrics`` dict.

    Shared by the Celery training task and the ``train_model`` command.
    """
    return dict(
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
        # Persist the single operating threshold training selected on the
        # validation split (cost-optimal). Scoring applies it to every
        # applicant, so the reported and fairness metrics match deployment.
        optimal_threshold=metrics.get("optimal_threshold"),
        confusion_matrix=metrics["confusion_matrix"],
        feature_importances=metrics["feature_importances"],
        roc_curve_data=metrics["roc_curve"],
        training_params=metrics["training_params"],
        calibration_data=metrics.get("calibration_data", {}),
        threshold_analysis=metrics.get("threshold_analysis", {}),
        decile_analysis=metrics.get("decile_analysis", {}),
        fairness_metrics=metrics.get("fairness", {}),
        training_metadata=metrics.get("training_metadata", {}),
    )


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
    # Prevent concurrent training — the same Redis lock TrainModelView checks.
    lock = acquire_train_lock()
    if lock is None:
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
        release_train_lock(lock)
        raise


def acquire_train_lock():
    """Take the 30-minute training lock; return it, or None if a run holds it."""
    import redis as _redis

    redis_client = _redis.from_url(settings.CELERY_BROKER_URL)
    lock = redis_client.lock(TRAIN_LOCK_KEY, timeout=1800, blocking=False)
    return lock if lock.acquire(blocking=False) else None


def release_train_lock(lock):
    # Guard the release: after a long train the 30-min lock may already have
    # expired, and releasing an expired/unowned redis lock raises — which
    # would mask the real training error a caller may be re-raising.
    try:
        lock.release()
    except Exception:
        logger.warning("train_model lock release failed (likely expired); ignoring")


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
    """Train, register and (gates permitting) activate a model. Lock held by the caller.

    The new ModelVersion is created inactive and handed to the activation
    service, which checks the artefact, runs the fairness / promotion /
    validation gates in their configured modes, and only then retires the
    segment's champion — all under the segment lock. In ``block`` mode a
    failing gate leaves the candidate inactive (traffic 0) for sign-off and
    manual activation, and the champion keeps serving. Shared by the Celery
    task and the ``train_model`` command.
    """
    from django.db import transaction

    from apps.ml_engine.services.activation import ActivationBlocked, activate_model_version
    from apps.ml_engine.services.scoring.segmentation import SEGMENT_UNIFIED
    from apps.ml_engine.services.training.trainer import ModelTrainer

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

    file_hash = file_sha256(model_path)  # integrity check at load time

    # One transaction: the row, the activation and the gate record commit
    # together, so the MRM dossier (enqueued on commit) sees the gate verdicts.
    with transaction.atomic():
        mv = ModelVersion.objects.create(
            algorithm=algorithm,
            version=version_str,
            file_path=model_path,
            file_hash=file_hash,
            is_active=False,
            traffic_percentage=0,
            segment=segment,
            **model_version_metric_fields(metrics),
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

        try:
            gates = activate_model_version(mv, actor=None, source="training")
            blocked_gates = []
        except ActivationBlocked as exc:
            gates, blocked_gates = exc.gates, exc.blocked_gates
            logger.warning(
                "Model %s not activated: blocked by %s. Candidate kept inactive; "
                "the current champion keeps serving. Sign off and activate it manually.",
                mv.id,
                ", ".join(blocked_gates),
            )

        mv.refresh_from_db()
        mv.training_metadata = {**(mv.training_metadata or {}), **_gate_metadata(mv, gates, blocked_gates)}
        mv.save(update_fields=["training_metadata"])

    release_train_lock(lock)
    return {"model_version_id": str(mv.id), "metrics": metrics, "activated": not blocked_gates}


def _gate_metadata(mv, gates: dict, blocked_gates: list[str]) -> dict:
    """The gate verdicts in the training_metadata keys the MRM dossier reads."""
    meta = {
        "fairness_gate_mode": gates["fairness"]["mode"],
        "promotion_gate_mode": gates["promotion"]["mode"],
        "validation_gate_mode": gates["validation"]["mode"],
    }
    if blocked_gates:
        meta["activation_blocked"] = blocked_gates
    if gates["validation"]["result"] is not None:
        meta["validation_gate"] = gates["validation"]["result"]

    fairness = gates["fairness"]["result"]
    if fairness is not None:
        meta["fairness_gate"] = fairness
        if not fairness["passed"]:
            logger.warning(
                "Model %s FAILED fairness gate (mode=%s, failing: %s, min DIR: %s).",
                mv.id,
                gates["fairness"]["mode"],
                fairness["failing_attributes"],
                fairness["minimum_dir"],
            )
            meta["requires_fairness_review"] = True

    promotion = gates["promotion"]["result"]
    if promotion is not None:
        meta["promotion_gate"] = promotion
        if not promotion["promoted"]:
            logger.warning(
                "Model %s REJECTED by promotion gates (mode=%s, reasons: %s).",
                mv.id,
                gates["promotion"]["mode"],
                "; ".join(promotion["reasons"]),
            )
            meta["requires_promotion_review"] = True
    return meta


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
    from apps.ml_engine.services.model_selector import NoActiveModelError
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
    except NoActiveModelError as e:
        # Not transient; do not retry. Back to pending (audited) so the
        # application can be processed once a model is activated.
        logger.error("run_prediction_task: no active model for application %s — %s", application_id, e)
        application.transition_to("pending", details={"reason": "no_active_model", "error": str(e)[:500]})
        return {"status": "skipped", "reason": "no_active_model", "detail": str(e)}
    except Exception as e:
        # Anything else (artefact integrity failure, path rejection, input
        # validation, consistency failure, transient I/O) surfaces: revert so
        # the application isn't stuck in 'processing', then re-raise.
        application.transition_to("pending", details={"reason": "prediction_failed", "error": str(e)[:500]})
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
            "risk_grade": result.get("risk_grade", ""),
            "feature_importances": result["feature_importances"],
            "shap_values": result.get("shap_values", {}),
            "decision_waterfall": [],
            "model_version": result["model_version"],
        },
    )

    # Apply the model decision. Refer reasons (borderline / drift / policy
    # refer) never route to the review queue, which is only for bias flags.
    application.transition_to(
        result["prediction"],
        details={"refer_reasons": result.get("refer_reasons") or []},
    )

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
    if psi_score is not None and psi_score >= PSI_INVESTIGATE:
        drift_detected = True
        alert_level = "significant"
    elif psi_score is not None and psi_score >= PSI_STABLE:
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

    if alert_level == "significant":
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

    Queued once per new ModelVersion, after the creating transaction commits
    (post_save signal + on_commit). Later save() calls do not re-queue it;
    regenerate with `manage.py generate_mrm_dossier`. Non-blocking:
    failures log a warning but do not surface back to the caller that
    created the model. Idempotent — overwriting an existing dossier is safe.
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
