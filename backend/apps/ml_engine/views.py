import logging

import redis
from django.conf import settings as django_settings
from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdmin, IsAdminOrOfficer
from apps.loans.models import AuditLog
from apps.loans.permissions import check_loan_access
from apps.ml_engine.models import DriftReport, ModelVersion, PredictionLog
from apps.ml_engine.services.model_selector import NoActiveModelError
from apps.ml_engine.services.scoring.adhoc import AdhocApplicantSerializer, input_error_detail, score_applicant
from apps.ml_engine.services.scoring.policy_overlay import PolicyOverlayUnavailable
from apps.ml_engine.tasks import TRAIN_LOCK_KEY, run_prediction_task, train_model_task

logger = logging.getLogger(__name__)


class PredictionThrottle(UserRateThrottle):
    # Own scope so this cap doesn't share the global UserRateThrottle's
    # "throttle_user_<id>" cache key (see accounts.views.RefreshRateThrottle).
    scope = "ml_predict"
    rate = "10/hour"


class PredictView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [PredictionThrottle]

    def post(self, request, loan_id):
        """Trigger ML prediction for a loan application."""
        check_loan_access(request, loan_id)

        if not getattr(django_settings, "ML_STANDALONE_PREDICT_ENABLED", False):
            return Response(
                {"detail": "Standalone prediction is disabled; use the agent orchestrator."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        task = run_prediction_task.delay(str(loan_id))

        AuditLog.objects.create(
            user=request.user,
            action="prediction_run",
            resource_type="LoanApplication",
            resource_id=str(loan_id),
            details={"task_id": task.id},
            ip_address=request.META.get("REMOTE_ADDR"),
        )

        return Response(
            {"task_id": task.id, "status": "prediction_queued"},
            status=status.HTTP_202_ACCEPTED,
        )


class ModelMetricsView(APIView):
    permission_classes = [IsAdminOrOfficer]

    def get(self, request):
        """Return metrics for the active model (the unified champion)."""
        from apps.ml_engine.services.model_selector import monitoring_model_version

        model_version = monitoring_model_version()
        if not model_version:
            return Response(
                {"error": "No active model found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "id": str(model_version.id),
                "algorithm": model_version.algorithm,
                "version": model_version.version,
                "is_active": model_version.is_active,
                "accuracy": model_version.accuracy,
                "precision": model_version.precision,
                "recall": model_version.recall,
                "f1_score": model_version.f1_score,
                "auc_roc": model_version.auc_roc,
                "brier_score": model_version.brier_score,
                "gini_coefficient": model_version.gini_coefficient,
                "ks_statistic": model_version.ks_statistic,
                "log_loss": model_version.log_loss_value,
                "ece": model_version.ece,
                "optimal_threshold": model_version.optimal_threshold,
                "confusion_matrix": model_version.confusion_matrix,
                "feature_importances": model_version.feature_importances,
                "roc_curve_data": model_version.roc_curve_data,
                "training_params": model_version.training_params,
                "calibration_data": model_version.calibration_data,
                "threshold_analysis": model_version.threshold_analysis,
                "decile_analysis": model_version.decile_analysis,
                "fairness_metrics": model_version.fairness_metrics,
                "training_metadata": model_version.training_metadata,
                "created_at": model_version.created_at.isoformat(),
            }
        )


class TrainModelView(APIView):
    permission_classes = [IsAdmin]

    TRAIN_LOCK_KEY = TRAIN_LOCK_KEY

    def post(self, request):
        """Trigger model training (admin only)."""
        algorithm = request.data.get("algorithm", "xgb")
        if algorithm not in ("rf", "xgb"):
            return Response(
                {"error": "algorithm must be one of: 'rf', 'xgb'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Reject duplicate training requests at the API layer. The Celery task
        # also holds this same Redis lock as a backstop, but checking here
        # prevents recording misleading audit events for no-op runs.
        try:
            redis_client = redis.from_url(django_settings.CELERY_BROKER_URL)
            if redis_client.exists(self.TRAIN_LOCK_KEY):
                return Response(
                    {
                        "error": "A training job is already in progress. Please wait for it to complete before starting another.",
                        "code": "training_in_progress",
                    },
                    status=status.HTTP_409_CONFLICT,
                )
        except redis.RedisError:
            # If Redis is unreachable the Celery task itself will fail fast;
            # don't block the user here on a transient broker blip.
            pass

        task = train_model_task.delay(algorithm=algorithm, data_path=None)

        AuditLog.objects.create(
            user=request.user,
            action="model_trained",
            resource_type="ModelVersion",
            resource_id="pending",
            details={"algorithm": algorithm, "task_id": task.id},
            ip_address=request.META.get("REMOTE_ADDR"),
        )

        return Response(
            {"task_id": task.id, "status": "training_queued"},
            status=status.HTTP_202_ACCEPTED,
        )


class ModelDriftView(APIView):
    """Monitor model drift using Population Stability Index (PSI).

    Compares the distribution of recent loan applications against the
    training distribution stored in the model bundle. This fulfils APRA
    CPG 235 (Managing Data Risk) requirements for ongoing model monitoring.

    PSI interpretation:
      < 0.10: Stable — no action needed
      0.10-0.25: Moderate shift — investigate
      >= 0.25: Significant shift — retrain recommended
    """

    permission_classes = [IsAdmin]

    def get(self, request):
        """Compute PSI for recent applications vs training distribution."""
        from apps.ml_engine.services.governance.drift_monitor import compute_on_demand_feature_psi
        from apps.ml_engine.services.model_selector import monitoring_model_version

        try:
            days = int(request.query_params.get("days", 30))
        except (ValueError, TypeError):
            return Response({"error": "days must be an integer"}, status=400)
        if not 1 <= days <= 365:
            return Response({"error": "days must be between 1 and 365"}, status=400)

        # Resolve the active ModelVersion directly — avoids constructing a full
        # ModelPredictor (which joblib.load-s the model bundle) only to throw
        # the model object away before compute_on_demand_feature_psi builds its
        # own ModelPredictor internally.  One joblib.load per drift check.
        # Same model as the metrics page (monitoring_model_version), not the
        # weighted A/B draw, so the report never flips to a challenger.
        model_version = monitoring_model_version()
        if model_version is None:
            return Response({"error": "No active model found"}, status=status.HTTP_404_NOT_FOUND)

        result = compute_on_demand_feature_psi(model_version, days=days)

        if result.get("error") == "no_reference_distribution":
            return Response(
                {
                    "error": "No reference distribution stored in model bundle. Retrain the model to enable drift monitoring."
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        if result.get("insufficient_data"):
            return Response(
                {
                    "warning": f"Only {result['application_count']} applications in the last {result['days']} days. Need at least 20 for meaningful PSI.",
                    "application_count": result["application_count"],
                    "days": result["days"],
                }
            )

        result["interpretation"] = {
            "stable": "PSI < 0.10 — No significant population shift detected.",
            "moderate_shift": "PSI 0.10-0.25 — Moderate shift detected. Investigate whether the applicant population has changed.",
            "significant_shift": "PSI >= 0.25 — Significant shift detected. Model retraining is recommended.",
        }
        return Response(result)


class ModelCardView(APIView):
    """Structured model card for regulatory compliance and transparency.

    Returns a comprehensive model card generated by ``ModelCardGenerator``
    covering model details, intended use, training data, performance,
    fairness analysis, limitations, and regulatory compliance — aligned
    with APRA CPG 235 requirements.
    """

    permission_classes = [IsAdminOrOfficer]

    def get(self, request):
        from apps.ml_engine.services.governance.model_card import ModelCardGenerator

        try:
            generator = ModelCardGenerator()
        except ValueError:
            return Response(
                {"error": "No active model found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response({"model_card": generator.generate()})


class ModelVersionListView(APIView):
    """List all model versions with metrics and traffic configuration."""

    permission_classes = [IsAdminOrOfficer]

    def get(self, request):
        versions = ModelVersion.objects.all().order_by("-created_at")[:20]
        data = []
        for v in versions:
            data.append(
                {
                    "id": str(v.id),
                    "algorithm": v.algorithm,
                    "version": v.version,
                    "is_active": v.is_active,
                    "traffic_percentage": v.traffic_percentage,
                    "auc_roc": v.auc_roc,
                    "gini_coefficient": v.gini_coefficient,
                    "accuracy": v.accuracy,
                    "created_at": v.created_at.isoformat(),
                }
            )
        return Response({"models": data})


def _refused_response(exc):
    """HTTP 409 for an activation the service refused (no row changed)."""
    from apps.ml_engine.services.activation import ActivationBlocked, ArtefactUnusable

    if isinstance(exc, ActivationBlocked):
        return Response(
            {
                "error": "activation_blocked",
                "blocked_gates": exc.blocked_gates,
                "gates": exc.gates,
                "hint": (
                    "Fix what the gate reports (e.g. create and sign off a ModelValidationReport), "
                    "or pass ?force=true on /activate/ (audited override)."
                ),
            },
            status=status.HTTP_409_CONFLICT,
        )
    code = "artefact_unusable" if isinstance(exc, ArtefactUnusable) else "segment_would_be_empty"
    return Response({"error": code, "detail": str(exc)}, status=status.HTTP_409_CONFLICT)


class ModelActivateView(APIView):
    """Activate a model as its segment's champion with 100% traffic.

    Goes through the activation service: artefact check, governance gates
    (``?force=true`` is the audited override), segment lock, audit.
    """

    permission_classes = [IsAdmin]

    def post(self, request, pk):
        from apps.ml_engine.services.activation import ActivationRefused, activate_model_version

        try:
            version = ModelVersion.objects.get(pk=pk)
        except ModelVersion.DoesNotExist:
            return Response({"error": "Model not found"}, status=status.HTTP_404_NOT_FOUND)

        force = request.query_params.get("force", "").lower() == "true"
        try:
            gates = activate_model_version(
                version,
                actor=request.user,
                source="api",
                force=force,
                ip_address=request.META.get("REMOTE_ADDR"),
            )
        except ActivationRefused as exc:
            return _refused_response(exc)

        return Response(
            {
                "message": f"Model {version.version} activated as champion (100% traffic)",
                "model_id": str(version.id),
                "segment": version.segment,
                "validation_gate": gates["validation"]["mode"],
                "force": force,
            }
        )


class ModelTrafficView(APIView):
    """Adjust traffic percentage for a model version (through the activation service)."""

    permission_classes = [IsAdmin]

    def patch(self, request, pk):
        from apps.ml_engine.services.activation import ActivationRefused, set_traffic

        try:
            version = ModelVersion.objects.get(pk=pk)
        except ModelVersion.DoesNotExist:
            return Response({"error": "Model not found"}, status=status.HTTP_404_NOT_FOUND)

        traffic = request.data.get("traffic_percentage")
        # bool is an int subclass (True would become 1%), and 50.9 must not
        # silently truncate to 50: only a whole number 0-100 is accepted.
        is_whole = isinstance(traffic, int) or (isinstance(traffic, float) and traffic.is_integer())
        if isinstance(traffic, bool) or not is_whole or not (0 <= traffic <= 100):
            return Response(
                {"error": "traffic_percentage must be an integer 0-100"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            set_traffic(version, int(traffic), actor=request.user, ip_address=request.META.get("REMOTE_ADDR"))
        except ActivationRefused as exc:
            return _refused_response(exc)
        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        version.refresh_from_db()
        return Response(
            {
                "model_id": str(version.id),
                "traffic_percentage": version.traffic_percentage,
                "is_active": version.is_active,
            }
        )


class ModelCompareView(APIView):
    """Compare champion vs challenger model performance from PredictionLog."""

    permission_classes = [IsAdmin]

    def get(self, request):
        from django.db.models import Avg, Count

        from apps.ml_engine.services.model_selector import CHAMPION_ORDERING, pick_monitoring_model

        # Champion first, then the rest by traffic and age — a fixed order so
        # the agreement rate below always compares the champion with its peer.
        ranked = list(ModelVersion.objects.filter(is_active=True).order_by(*CHAMPION_ORDERING))
        champion = pick_monitoring_model(ranked)
        active_models = [champion, *(m for m in ranked if m is not champion)] if champion else []
        if len(active_models) < 2:
            return Response(
                {"message": "Need at least 2 active models for comparison"},
                status=status.HTTP_200_OK,
            )

        comparison = []
        for model in active_models:
            logs = PredictionLog.objects.filter(model_version=model)
            stats = logs.aggregate(
                total=Count("id"),
                avg_probability=Avg("probability"),
                avg_latency=Avg("processing_time_ms"),
            )
            approval_count = logs.filter(prediction="approved").count()
            total = stats["total"] or 0

            comparison.append(
                {
                    "model_id": str(model.id),
                    "version": model.version,
                    "algorithm": model.algorithm,
                    "traffic_percentage": model.traffic_percentage,
                    "total_predictions": total,
                    "approval_rate": round(approval_count / total, 4) if total > 0 else None,
                    "avg_confidence": round(stats["avg_probability"], 4) if stats["avg_probability"] else None,
                    "avg_latency_ms": round(stats["avg_latency"], 1) if stats["avg_latency"] else None,
                    "training_auc": model.auc_roc,
                    "fairness_gate": (model.training_metadata or {}).get("fairness_gate"),
                }
            )

        # Agreement rate: how often champion and challenger agree on the same applications
        agreement_rate = None
        if len(comparison) == 2:
            m1, m2 = active_models[0], active_models[1]
            shared_apps = set(
                PredictionLog.objects.filter(model_version=m1).values_list("application_id", flat=True)
            ) & set(PredictionLog.objects.filter(model_version=m2).values_list("application_id", flat=True))
            if shared_apps:
                m1_preds = dict(
                    PredictionLog.objects.filter(model_version=m1, application_id__in=shared_apps).values_list(
                        "application_id", "prediction"
                    )
                )
                m2_preds = dict(
                    PredictionLog.objects.filter(model_version=m2, application_id__in=shared_apps).values_list(
                        "application_id", "prediction"
                    )
                )
                agreements = sum(1 for app_id in shared_apps if m1_preds.get(app_id) == m2_preds.get(app_id))
                agreement_rate = round(agreements / len(shared_apps), 4)

        return Response({"comparison": comparison, "agreement_rate": agreement_rate})


class DriftReportListView(APIView):
    """List drift reports for the active model."""

    permission_classes = [IsAdminOrOfficer]

    def get(self, request):
        from apps.ml_engine.services.model_selector import monitoring_model_version

        active_model = monitoring_model_version()
        if not active_model:
            return Response(
                {"error": "No active model found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            limit = min(max(int(request.query_params.get("limit", 12)), 1), 100)
        except (ValueError, TypeError):
            limit = 12

        reports = DriftReport.objects.filter(
            model_version=active_model,
        ).order_by("-report_date")[:limit]

        data = []
        for r in reports:
            data.append(
                {
                    "id": str(r.id),
                    "report_date": r.report_date.isoformat(),
                    "psi_score": r.psi_score,
                    "psi_per_feature": r.psi_per_feature,
                    "mean_probability": r.mean_probability,
                    "std_probability": r.std_probability,
                    "approval_rate": r.approval_rate,
                    "drift_detected": r.drift_detected,
                    "alert_level": r.alert_level,
                    "num_predictions": r.num_predictions,
                    "period_start": r.period_start.isoformat(),
                    "period_end": r.period_end.isoformat(),
                }
            )

        return Response(data)


class AdhocScoreThrottle(UserRateThrottle):
    # Own scope: without it the cap shares "throttle_user_<id>" with the
    # global UserRateThrottle and both limits count each other's requests.
    scope = "adhoc_score"
    rate = "30/hour"


class AdhocScoreView(APIView):
    """Score one applicant's facts against the active model.

    Builds nothing durable: no `LoanApplication` row, no referral-audit
    save, no shadow-scoring `PredictionLog` row (see `ModelPredictor.predict
    (..., persist=False)`). Staff-only — this is an underwriting tool, not
    a customer-facing pre-qualification endpoint.
    """

    permission_classes = [IsAdminOrOfficer]
    throttle_classes = [AdhocScoreThrottle]

    def post(self, request):
        serializer = AdhocApplicantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = score_applicant(serializer.validated_data)
        except NoActiveModelError:  # a ValueError subclass, so it must come first
            return Response({"detail": "No active model"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except PolicyOverlayUnavailable as exc:
            # Class name only: the exception text can carry applicant figures.
            logger.warning("adhoc_score_unavailable: %s", type(exc).__name__)
            return Response(
                {"detail": "Credit policy rules are unavailable right now. Try again shortly."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except ValueError as exc:
            logger.warning("adhoc_score_rejected: %s", type(exc).__name__)
            return Response({"detail": input_error_detail(exc)}, status=status.HTTP_400_BAD_REQUEST)

        AuditLog.objects.create(
            user=request.user,
            action="adhoc_score",
            resource_type="ModelVersion",
            resource_id=result["model_version"],
            details={"fields": sorted(serializer.validated_data.keys())},
            ip_address=request.META.get("REMOTE_ADDR"),
        )

        return Response(result, status=status.HTTP_200_OK)
