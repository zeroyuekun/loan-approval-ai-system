import numpy as np
from sklearn.calibration import calibration_curve
from sklearn.metrics import (
    accuracy_score,
    auc,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)


class MetricsService:
    """Helpers for computing classification metrics."""

    def compute_metrics(self, y_true, y_pred, y_prob):
        """Compute standard classification metrics."""
        return {
            'accuracy': round(float(accuracy_score(y_true, y_pred)), 4),
            'precision': round(float(precision_score(y_true, y_pred)), 4),
            'recall': round(float(recall_score(y_true, y_pred)), 4),
            'f1_score': round(float(f1_score(y_true, y_pred)), 4),
            'auc_roc': round(float(roc_auc_score(y_true, y_prob)), 4),
            'brier_score': round(float(brier_score_loss(y_true, y_prob)), 4),
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

        def _safe_float(x):
            val = float(x)
            if np.isinf(val) or np.isnan(val):
                return None
            return round(val, 4)

        return {
            'fpr': [round(float(x), 4) for x in fpr],
            'tpr': [round(float(x), 4) for x in tpr],
            'thresholds': [_safe_float(x) for x in thresholds],
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

    def compute_gini(self, y_true, y_prob):
        """Gini coefficient: 2 * AUC - 1. Primary discrimination metric for banks."""
        auc_val = roc_auc_score(y_true, y_prob)
        return round(2 * float(auc_val) - 1, 4)

    def compute_ks_statistic(self, y_true, y_prob):
        """KS statistic: max separation between approved/denied distributions."""
        fpr, tpr, thresholds = roc_curve(y_true, y_prob)
        ks_values = tpr - fpr
        max_idx = np.argmax(ks_values)
        return {
            'ks_statistic': round(float(ks_values[max_idx]), 4),
            'ks_threshold': round(float(thresholds[max_idx]), 4) if max_idx < len(thresholds) else None,
        }

    def compute_log_loss(self, y_true, y_prob):
        """Log loss (cross-entropy). Complements brier score."""
        return round(float(log_loss(y_true, y_prob)), 4)

    def compute_calibration_data(self, y_true, y_prob, n_bins=10):
        """Calibration curve data + Expected Calibration Error (ECE)."""
        fraction_of_positives, mean_predicted_value = calibration_curve(
            y_true, y_prob, n_bins=n_bins, strategy='uniform'
        )
        # ECE: weighted average of |actual - predicted| per bin
        bin_edges = np.linspace(0, 1, n_bins + 1)
        bin_indices = np.digitize(y_prob, bin_edges[1:-1])
        ece = 0.0
        total = len(y_prob)
        for i in range(n_bins):
            mask = bin_indices == i
            count = mask.sum()
            if count > 0:
                bin_acc = float(np.array(y_true)[mask].mean())
                bin_conf = float(np.array(y_prob)[mask].mean())
                ece += (count / total) * abs(bin_acc - bin_conf)

        return {
            'fraction_of_positives': [round(float(x), 4) for x in fraction_of_positives],
            'mean_predicted_value': [round(float(x), 4) for x in mean_predicted_value],
            'ece': round(ece, 4),
            'n_bins': n_bins,
        }

    def compute_threshold_analysis(self, y_true, y_prob):
        """Sweep thresholds 0.05-0.95 and find optimal thresholds."""
        thresholds = np.arange(0.05, 1.0, 0.05)
        sweep = []
        for t in thresholds:
            y_pred_t = (np.array(y_prob) >= t).astype(int)
            tp = ((y_pred_t == 1) & (np.array(y_true) == 1)).sum()
            fp = ((y_pred_t == 1) & (np.array(y_true) == 0)).sum()
            fn = ((y_pred_t == 0) & (np.array(y_true) == 1)).sum()
            tn = ((y_pred_t == 0) & (np.array(y_true) == 0)).sum()

            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
            fpr_val = fp / (fp + tn) if (fp + tn) > 0 else 0.0
            approval_rate = y_pred_t.mean()

            sweep.append({
                'threshold': round(float(t), 2),
                'precision': round(prec, 4),
                'recall': round(rec, 4),
                'f1': round(f1, 4),
                'fpr': round(fpr_val, 4),
                'approval_rate': round(float(approval_rate), 4),
            })

        # F1-optimal threshold
        f1_optimal = max(sweep, key=lambda x: x['f1'])['threshold']

        # Youden's J: max(TPR - FPR) = max(recall - fpr)
        youden_j = max(sweep, key=lambda x: x['recall'] - x['fpr'])['threshold']

        # Cost-matrix optimal: cost_FN=5, cost_FP=1
        def cost(entry):
            # Lower cost is better; entry has fpr and recall relative to total
            # Use raw counts approach: cost = cost_FP * FP + cost_FN * FN
            # Since we only have rates, use: cost = 1 * fpr + 5 * (1 - recall)
            return 1 * entry['fpr'] + 5 * (1 - entry['recall'])

        cost_optimal = min(sweep, key=cost)['threshold']

        return {
            'sweep': sweep,
            'f1_optimal_threshold': f1_optimal,
            'youden_j_threshold': youden_j,
            'cost_optimal_threshold': cost_optimal,
        }

    def compute_decile_analysis(self, y_true, y_prob):
        """Partition into 10 deciles by predicted probability."""
        y_true = np.array(y_true)
        y_prob = np.array(y_prob)
        order = np.argsort(y_prob)
        y_true_sorted = y_true[order]
        y_prob_sorted = y_prob[order]

        n = len(y_true)
        decile_size = n // 10
        overall_rate = y_true.mean()
        deciles = []
        cumulative_positive = 0
        cumulative_total = 0

        for i in range(10):
            start = i * decile_size
            end = start + decile_size if i < 9 else n
            group_true = y_true_sorted[start:end]
            count = len(group_true)
            actual_rate = float(group_true.mean()) if count > 0 else 0.0
            cumulative_positive += group_true.sum()
            cumulative_total += count
            cumulative_rate = float(cumulative_positive / cumulative_total) if cumulative_total > 0 else 0.0
            lift = actual_rate / overall_rate if overall_rate > 0 else 0.0

            deciles.append({
                'decile': i + 1,
                'count': int(count),
                'actual_rate': round(actual_rate, 4),
                'cumulative_rate': round(cumulative_rate, 4),
                'lift': round(lift, 4),
            })

        return {'deciles': deciles}

    def compute_fairness_metrics(self, y_true, y_pred, y_prob, group_labels):
        """Compute per-group fairness metrics with disparate impact and equalized odds."""
        y_true = np.array(y_true)
        y_pred = np.array(y_pred)
        y_prob = np.array(y_prob)
        group_labels = np.array(group_labels)
        unique_groups = np.unique(group_labels)

        group_metrics = {}
        approval_rates = []

        for group in unique_groups:
            mask = group_labels == group
            count = int(mask.sum())
            if count == 0:
                continue
            g_true = y_true[mask]
            g_pred = y_pred[mask]
            g_prob = y_prob[mask]

            approval_rate = float(g_pred.mean())
            # TPR = recall for positive class
            tp = ((g_pred == 1) & (g_true == 1)).sum()
            fn = ((g_pred == 0) & (g_true == 1)).sum()
            tpr = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
            # FPR
            fp = ((g_pred == 1) & (g_true == 0)).sum()
            tn = ((g_pred == 0) & (g_true == 0)).sum()
            fpr_val = float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0

            group_metrics[str(group)] = {
                'count': count,
                'actual_approval_rate': round(float(g_true.mean()), 4),
                'predicted_approval_rate': round(approval_rate, 4),
                'tpr': round(tpr, 4),
                'fpr': round(fpr_val, 4),
            }
            approval_rates.append(approval_rate)

        # Disparate impact ratio: min(rate) / max(rate). EEOC 80% rule: must be > 0.80
        if len(approval_rates) >= 2 and max(approval_rates) > 0:
            disparate_impact = min(approval_rates) / max(approval_rates)
        else:
            disparate_impact = 1.0

        # Equalized odds difference: max gap in TPR or FPR across groups
        tprs = [m['tpr'] for m in group_metrics.values()]
        fprs = [m['fpr'] for m in group_metrics.values()]
        eq_odds_diff = max(
            (max(tprs) - min(tprs)) if tprs else 0.0,
            (max(fprs) - min(fprs)) if fprs else 0.0,
        )

        return {
            'groups': group_metrics,
            'disparate_impact_ratio': round(disparate_impact, 4),
            'equalized_odds_difference': round(eq_odds_diff, 4),
            'passes_80_percent_rule': disparate_impact >= 0.80,
        }
