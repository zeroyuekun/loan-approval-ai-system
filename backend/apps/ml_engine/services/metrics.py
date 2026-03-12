import numpy as np
from sklearn.metrics import (
    accuracy_score,
    auc,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)


class MetricsService:
    """Computes and formats model evaluation metrics."""

    def compute_metrics(self, y_true, y_pred, y_prob):
        """Compute standard classification metrics."""
        return {
            'accuracy': round(float(accuracy_score(y_true, y_pred)), 4),
            'precision': round(float(precision_score(y_true, y_pred)), 4),
            'recall': round(float(recall_score(y_true, y_pred)), 4),
            'f1_score': round(float(f1_score(y_true, y_pred)), 4),
            'auc_roc': round(float(roc_auc_score(y_true, y_prob)), 4),
        }

    def confusion_matrix_data(self, y_true, y_pred):
        """Return confusion matrix in a frontend-friendly format."""
        cm = confusion_matrix(y_true, y_pred)
        return {
            'true_negatives': int(cm[0][0]),
            'false_positives': int(cm[0][1]),
            'false_negatives': int(cm[1][0]),
            'true_positives': int(cm[1][1]),
            'matrix': cm.tolist(),
        }

    def roc_curve_data(self, y_true, y_prob):
        """Return ROC curve data for frontend charting."""
        fpr, tpr, thresholds = roc_curve(y_true, y_prob)
        return {
            'fpr': [round(float(x), 4) for x in fpr],
            'tpr': [round(float(x), 4) for x in tpr],
            'thresholds': [round(float(x), 4) for x in thresholds],
            'auc': round(float(auc(fpr, tpr)), 4),
        }

    def feature_importance_data(self, model, feature_names):
        """Return sorted feature importances."""
        if hasattr(model, 'feature_importances_'):
            importances = model.feature_importances_
        else:
            return []

        items = [
            {'feature': name, 'importance': round(float(imp), 4)}
            for name, imp in zip(feature_names, importances)
        ]
        return sorted(items, key=lambda x: x['importance'], reverse=True)
