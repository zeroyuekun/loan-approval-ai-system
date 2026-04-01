from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdmin
from apps.loans.models import AuditLog, LoanApplication
from apps.loans.permissions import check_loan_access
from apps.ml_engine.models import DriftReport, ModelVersion, PredictionLog
from apps.ml_engine.tasks import run_prediction_task, train_model_task


class PredictionThrottle(UserRateThrottle):
    rate = "10/hour"


class PredictView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [PredictionThrottle]

    def post(self, request, loan_id):
        """Trigger ML prediction for a loan application."""
        check_loan_access(request, loan_id)

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
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return metrics for the active model."""
        model_version = ModelVersion.objects.filter(is_active=True).first()
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

    def post(self, request):
        """Trigger model training (admin only)."""
        algorithm = request.data.get("algorithm", "xgb")
        if algorithm not in ("rf", "xgb"):
            return Response(
                {"error": "algorithm must be one of: 'rf', 'xgb'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
        import numpy as np

        from apps.ml_engine.services.metrics import MetricsService
        from apps.ml_engine.services.predictor import ModelPredictor

        try:
            predictor = ModelPredictor()
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)

        ref_dist = predictor.reference_distribution
        if not ref_dist:
            return Response(
                {
                    "error": "No reference distribution stored in model bundle. Retrain the model to enable drift monitoring."
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Gather recent applications (last 30 days by default)
        from datetime import timedelta

        from django.utils import timezone

        try:
            days = int(request.query_params.get("days", 30))
        except (ValueError, TypeError):
            return Response({"error": "days must be an integer"}, status=400)
        cutoff = timezone.now() - timedelta(days=days)
        recent_apps = LoanApplication.objects.filter(created_at__gte=cutoff)

        if recent_apps.count() < 20:
            return Response(
                {
                    "warning": f"Only {recent_apps.count()} applications in the last {days} days. Need at least 20 for meaningful PSI.",
                    "application_count": recent_apps.count(),
                    "days": days,
                }
            )

        # Build DataFrame from recent applications
        metrics_service = MetricsService()
        numeric_cols = predictor.numeric_cols or list(ref_dist.keys())

        feature_psi = {}
        overall_status = "stable"

        for col in numeric_cols:
            if col not in ref_dist:
                continue

            ref = ref_dist[col]
            hist_counts = ref.get("histogram_counts", [])
            hist_edges = ref.get("histogram_edges", [])

            # Fall back to percentiles for models trained before histogram storage
            if not hist_counts or not hist_edges:
                percentiles = ref.get("percentiles", [])
                if not percentiles:
                    continue
                # Legacy path: use percentiles as raw values for PSI
                # (less accurate but functional)

            # Get actual values from recent applications
            field_map = {
                "annual_income": "annual_income",
                "credit_score": "credit_score",
                "loan_amount": "loan_amount",
                "loan_term_months": "loan_term_months",
                "debt_to_income": "debt_to_income",
                "employment_length": "employment_length",
                "has_cosigner": "has_cosigner",
                "property_value": "property_value",
                "deposit_amount": "deposit_amount",
                "monthly_expenses": "monthly_expenses",
                "existing_credit_card_limit": "existing_credit_card_limit",
                "number_of_dependants": "number_of_dependants",
                "has_hecs": "has_hecs",
                "has_bankruptcy": "has_bankruptcy",
            }
            db_field = field_map.get(col, col)

            try:
                actual_vals = np.array(
                    list(recent_apps.values_list(db_field, flat=True)),
                    dtype=float,
                )
                actual_vals = actual_vals[np.isfinite(actual_vals)]
            except (ValueError, TypeError):
                continue

            if len(actual_vals) < 10:
                continue

            # Use stored histogram bins for proper PSI computation
            if hist_counts and hist_edges and len(hist_edges) >= 3:
                bin_edges = np.array(hist_edges)
                expected_counts = np.array(hist_counts, dtype=float)
                actual_counts = np.histogram(actual_vals, bins=bin_edges)[0].astype(float)

                # Convert to proportions with epsilon to avoid division by zero
                eps = 1e-4
                expected_pct = expected_counts / expected_counts.sum() + eps
                actual_pct = actual_counts / actual_counts.sum() + eps

                psi_components = (actual_pct - expected_pct) * np.log(actual_pct / expected_pct)
                psi_value = float(np.sum(psi_components))

                if psi_value < 0.10:
                    psi_status = "stable"
                elif psi_value < 0.25:
                    psi_status = "moderate_shift"
                else:
                    psi_status = "significant_shift"

                result = {"psi": round(psi_value, 4), "status": psi_status}
            else:
                # Legacy fallback: pass percentiles as expected values
                expected_vals = np.array(ref.get("percentiles", []))
                result = metrics_service.compute_psi(expected_vals, actual_vals)
            feature_psi[col] = {
                "psi": result["psi"],
                "status": result["status"],
                "training_mean": round(ref.get("mean", 0), 2),
                "training_std": round(ref.get("std", 0), 2),
                "current_mean": round(float(np.mean(actual_vals)), 2),
                "current_std": round(float(np.std(actual_vals)), 2),
            }

            if result["status"] == "significant_shift":
                overall_status = "significant_shift"
            elif result["status"] == "moderate_shift" and overall_status == "stable":
                overall_status = "moderate_shift"

        return Response(
            {
                "model_version": str(predictor.model_version.id),
                "days_analysed": days,
                "application_count": recent_apps.count(),
                "overall_status": overall_status,
                "feature_psi": feature_psi,
                "interpretation": {
                    "stable": "PSI < 0.10 — No significant population shift detected.",
                    "moderate_shift": "PSI 0.10-0.25 — Moderate shift detected. Investigate whether the applicant population has changed.",
                    "significant_shift": "PSI >= 0.25 — Significant shift detected. Model retraining is recommended.",
                },
            }
        )


class ModelCardView(APIView):
    """Structured model card for regulatory compliance and transparency.

    Returns a comprehensive model card generated by ``ModelCardGenerator``
    covering model details, intended use, training data, performance,
    fairness analysis, limitations, and regulatory compliance — aligned
    with APRA CPG 235 requirements.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.ml_engine.services.model_card import ModelCardGenerator

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

    permission_classes = [IsAuthenticated]

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


class ModelActivateView(APIView):
    """Activate a model as champion with 100% traffic."""

    permission_classes = [IsAdmin]

    def post(self, request, pk):
        try:
            version = ModelVersion.objects.get(pk=pk)
        except ModelVersion.DoesNotExist:
            return Response({"error": "Model not found"}, status=status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            ModelVersion.objects.filter(is_active=True).update(
                is_active=False,
                traffic_percentage=0,
            )
            version.is_active = True
            version.traffic_percentage = 100
            version.save()

        return Response(
            {
                "message": f"Model {version.version} activated as champion (100% traffic)",
                "model_id": str(version.id),
            }
        )


class ModelTrafficView(APIView):
    """Adjust traffic percentage for a model version."""

    permission_classes = [IsAdmin]

    def patch(self, request, pk):
        try:
            version = ModelVersion.objects.get(pk=pk)
        except ModelVersion.DoesNotExist:
            return Response({"error": "Model not found"}, status=status.HTTP_404_NOT_FOUND)

        traffic = request.data.get("traffic_percentage")
        if traffic is None or not isinstance(traffic, (int, float)) or not (0 <= traffic <= 100):
            return Response(
                {"error": "traffic_percentage must be an integer 0-100"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        version.traffic_percentage = int(traffic)
        version.is_active = version.traffic_percentage > 0
        try:
            version.save()
        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

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

        active_models = ModelVersion.objects.filter(is_active=True)
        if active_models.count() < 2:
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
            ) & set(
                PredictionLog.objects.filter(model_version=m2).values_list("application_id", flat=True)
            )
            if shared_apps:
                m1_preds = dict(
                    PredictionLog.objects.filter(model_version=m1, application_id__in=shared_apps)
                    .values_list("application_id", "prediction")
                )
                m2_preds = dict(
                    PredictionLog.objects.filter(model_version=m2, application_id__in=shared_apps)
                    .values_list("application_id", "prediction")
                )
                agreements = sum(1 for app_id in shared_apps if m1_preds.get(app_id) == m2_preds.get(app_id))
                agreement_rate = round(agreements / len(shared_apps), 4)

        return Response({"comparison": comparison, "agreement_rate": agreement_rate})


class DriftReportListView(APIView):
    """List drift reports for the active model."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        active_model = ModelVersion.objects.filter(is_active=True).first()
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
