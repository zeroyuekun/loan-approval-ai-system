from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdmin
from apps.loans.models import AuditLog, LoanApplication
from apps.ml_engine.models import ModelVersion
from apps.ml_engine.tasks import run_prediction_task, train_model_task


class PredictionThrottle(UserRateThrottle):
    rate = '10/hour'


class PredictView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [PredictionThrottle]

    def post(self, request, loan_id):
        """Trigger ML prediction for a loan application."""
        try:
            application = LoanApplication.objects.get(pk=loan_id)
        except LoanApplication.DoesNotExist:
            return Response(
                {'error': 'Loan application not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        user = request.user
        if user.role not in ('admin', 'officer') and application.applicant_id != user.id:
            return Response(
                {'error': 'You do not have permission to access this loan application'},
                status=status.HTTP_403_FORBIDDEN,
            )

        task = run_prediction_task.delay(str(loan_id))

        AuditLog.objects.create(
            user=request.user,
            action='prediction_run',
            resource_type='LoanApplication',
            resource_id=str(loan_id),
            details={'task_id': task.id},
            ip_address=request.META.get('REMOTE_ADDR'),
        )

        return Response(
            {'task_id': task.id, 'status': 'prediction_queued'},
            status=status.HTTP_202_ACCEPTED,
        )


class ModelMetricsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return metrics for the active model."""
        model_version = ModelVersion.objects.filter(is_active=True).first()
        if not model_version:
            return Response(
                {'error': 'No active model found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response({
            'id': str(model_version.id),
            'algorithm': model_version.algorithm,
            'version': model_version.version,
            'is_active': model_version.is_active,
            'accuracy': model_version.accuracy,
            'precision': model_version.precision,
            'recall': model_version.recall,
            'f1_score': model_version.f1_score,
            'auc_roc': model_version.auc_roc,
            'brier_score': model_version.brier_score,
            'gini_coefficient': model_version.gini_coefficient,
            'ks_statistic': model_version.ks_statistic,
            'log_loss': model_version.log_loss_value,
            'ece': model_version.ece,
            'optimal_threshold': model_version.optimal_threshold,
            'confusion_matrix': model_version.confusion_matrix,
            'feature_importances': model_version.feature_importances,
            'roc_curve_data': model_version.roc_curve_data,
            'training_params': model_version.training_params,
            'calibration_data': model_version.calibration_data,
            'threshold_analysis': model_version.threshold_analysis,
            'decile_analysis': model_version.decile_analysis,
            'fairness_metrics': model_version.fairness_metrics,
            'training_metadata': model_version.training_metadata,
            'created_at': model_version.created_at.isoformat(),
        })


class TrainModelView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request):
        """Trigger model training (admin only)."""
        algorithm = request.data.get('algorithm', 'xgb')
        if algorithm not in ('rf', 'xgb'):
            return Response(
                {'error': "algorithm must be one of: 'rf', 'xgb'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        task = train_model_task.delay(algorithm=algorithm, data_path=None)

        AuditLog.objects.create(
            user=request.user,
            action='model_trained',
            resource_type='ModelVersion',
            resource_id='pending',
            details={'algorithm': algorithm, 'task_id': task.id},
            ip_address=request.META.get('REMOTE_ADDR'),
        )

        return Response(
            {'task_id': task.id, 'status': 'training_queued'},
            status=status.HTTP_202_ACCEPTED,
        )
