from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdmin
from apps.ml_engine.models import ModelVersion
from apps.ml_engine.tasks import run_prediction_task, train_model_task


class PredictView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, loan_id):
        """Trigger ML prediction for a loan application."""
        task = run_prediction_task.delay(str(loan_id))
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
            'algorithm': model_version.get_algorithm_display(),
            'version': model_version.version,
            'is_active': model_version.is_active,
            'accuracy': model_version.accuracy,
            'precision': model_version.precision,
            'recall': model_version.recall,
            'f1_score': model_version.f1_score,
            'auc_roc': model_version.auc_roc,
            'confusion_matrix': model_version.confusion_matrix,
            'feature_importances': model_version.feature_importances,
            'roc_curve_data': model_version.roc_curve_data,
            'training_params': model_version.training_params,
            'created_at': model_version.created_at.isoformat(),
        })


class TrainModelView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request):
        """Trigger model training (admin only)."""
        algorithm = request.data.get('algorithm', 'xgb')
        data_path = request.data.get('data_path', None)

        task = train_model_task.delay(algorithm=algorithm, data_path=data_path)
        return Response(
            {'task_id': task.id, 'status': 'training_queued'},
            status=status.HTTP_202_ACCEPTED,
        )
