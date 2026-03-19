import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.linear_model import LogisticRegression
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

        # Cost-matrix optimal for banking: cost_FP=5, cost_FN=1
        # In lending, a false positive (approving a defaulter) is far more
        # expensive than a false negative (denying a good borrower):
        # - FP: loan loss, provisioning, collections, reputational damage
        # - FN: lost revenue only (customer can reapply or go elsewhere)
        # APRA's approach to credit risk (APS 220) weights default losses
        # heavily; Big 4 banks typically use 3:1 to 10:1 FP:FN cost ratios.
        def cost(entry):
            # Lower cost is better
            # cost = cost_FP * FPR + cost_FN * (1 - recall)
            return 5 * entry['fpr'] + 1 * (1 - entry['recall'])

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

    def compute_psi(self, expected, actual, n_bins=10):
        """Population Stability Index — measures distribution shift.

        Used by Australian banks under APRA CPG 235 (Managing Data Risk) to
        monitor whether the population applying for loans has shifted from the
        population the model was trained on.

        Interpretation (industry standard, also used by CBA/ANZ/Westpac/NAB):
          PSI < 0.10: No significant shift. Model is stable.
          0.10 <= PSI < 0.25: Moderate shift. Investigate and monitor.
          PSI >= 0.25: Significant shift. Model retraining recommended.

        Args:
            expected: array of values from the training/reference distribution
            actual: array of values from the current/production distribution
            n_bins: number of bins for the histogram comparison

        Returns:
            dict with psi value, per-bin breakdown, and status classification
        """
        expected = np.array(expected, dtype=float)
        actual = np.array(actual, dtype=float)

        # Remove NaN/Inf
        expected = expected[np.isfinite(expected)]
        actual = actual[np.isfinite(actual)]

        if len(expected) < n_bins or len(actual) < n_bins:
            return {
                'psi': 0.0,
                'status': 'insufficient_data',
                'bins': [],
            }

        # Use expected distribution to define bin edges
        bin_edges = np.percentile(expected, np.linspace(0, 100, n_bins + 1))
        # Ensure unique edges (can happen with highly concentrated features)
        bin_edges = np.unique(bin_edges)
        if len(bin_edges) < 3:
            return {
                'psi': 0.0,
                'status': 'insufficient_bins',
                'bins': [],
            }

        expected_counts = np.histogram(expected, bins=bin_edges)[0]
        actual_counts = np.histogram(actual, bins=bin_edges)[0]

        # Convert to proportions; epsilon only for zero-count bins to avoid log(0)
        eps = 1e-4
        expected_pct = np.maximum(expected_counts / len(expected), eps)
        actual_pct = np.maximum(actual_counts / len(actual), eps)

        # PSI = sum((actual% - expected%) * ln(actual% / expected%))
        psi_components = (actual_pct - expected_pct) * np.log(actual_pct / expected_pct)
        psi_value = float(np.sum(psi_components))

        if psi_value < 0.10:
            status = 'stable'
        elif psi_value < 0.25:
            status = 'moderate_shift'
        else:
            status = 'significant_shift'

        bins = []
        for i in range(len(bin_edges) - 1):
            bins.append({
                'bin_low': round(float(bin_edges[i]), 4),
                'bin_high': round(float(bin_edges[i + 1]), 4),
                'expected_pct': round(float(expected_pct[i]), 6),
                'actual_pct': round(float(actual_pct[i]), 6),
                'psi_component': round(float(psi_components[i]), 6),
            })

        return {
            'psi': round(psi_value, 4),
            'status': status,
            'bins': bins,
        }

    def compute_feature_psi(self, train_df, current_df, numeric_cols, n_bins=10):
        """Compute PSI for each numeric feature to identify which features drifted.

        Returns dict mapping feature name to PSI result.
        """
        results = {}
        for col in numeric_cols:
            if col in train_df.columns and col in current_df.columns:
                result = self.compute_psi(
                    train_df[col].values,
                    current_df[col].values,
                    n_bins=n_bins,
                )
                results[col] = {
                    'psi': result['psi'],
                    'status': result['status'],
                }
        return results

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

    # ==================================================================
    # WEIGHT OF EVIDENCE (WOE) AND INFORMATION VALUE (IV)
    #
    # WOE is the standard methodology used by Australian banks (and
    # globally under Basel III/APRA APS 113) for building credit
    # scorecards. It transforms each feature into its predictive power
    # by computing the log odds ratio per bin:
    #
    #   WOE_i = ln(% of approved in bin_i / % of denied in bin_i)
    #
    # Information Value summarises a feature's total predictive power:
    #
    #   IV = sum((% approved_i - % denied_i) * WOE_i)
    #
    # IV interpretation (industry standard):
    #   < 0.02: not predictive (drop from scorecard)
    #   0.02 - 0.10: weak predictor
    #   0.10 - 0.30: medium predictor
    #   0.30 - 0.50: strong predictor
    #   > 0.50: suspiciously strong (check for data leakage)
    #
    # Banks prefer WOE-binned logistic regression over tree models for
    # their primary scorecard because:
    # 1. Regulators (APRA, ASIC) require interpretability
    # 2. WOE naturally handles non-linear relationships via binning
    # 3. IV provides automatic feature selection
    # 4. The scorecard can be printed on a single page
    # ==================================================================

    def compute_woe_iv(self, feature_values, y_true, n_bins=10, feature_name='feature'):
        """Compute Weight of Evidence and Information Value for a single feature.

        Args:
            feature_values: array of feature values
            y_true: array of binary outcomes (1=approved, 0=denied)
            n_bins: number of bins for continuous features
            feature_name: name for labelling bins

        Returns:
            dict with 'iv' (total Information Value), 'woe_bins' (per-bin breakdown),
            and 'iv_interpretation' (human-readable strength classification).
        """
        feature_values = np.array(feature_values, dtype=float)
        y_true = np.array(y_true)

        # Remove NaN/Inf
        valid = np.isfinite(feature_values)
        feature_values = feature_values[valid]
        y_true = y_true[valid]

        if len(feature_values) < n_bins * 2:
            return {'iv': 0.0, 'woe_bins': [], 'iv_interpretation': 'insufficient_data'}

        # Detect discrete features (few unique values, e.g. number_of_dependants)
        # and bin by unique value instead of quantile to avoid degenerate bins.
        unique_vals = np.unique(feature_values)
        if len(unique_vals) <= n_bins:
            # Discrete feature: bin by unique value
            sorted_vals = np.sort(unique_vals)
            bin_edges = np.concatenate([
                [sorted_vals[0] - 0.5],
                (sorted_vals[:-1] + sorted_vals[1:]) / 2,
                [sorted_vals[-1] + 0.5],
            ])
        else:
            # Continuous feature: quantile binning
            try:
                bin_edges = np.unique(np.percentile(feature_values, np.linspace(0, 100, n_bins + 1)))
            except Exception:
                return {'iv': 0.0, 'woe_bins': [], 'iv_interpretation': 'binning_failed'}

        if len(bin_edges) < 3:
            return {'iv': 0.0, 'woe_bins': [], 'iv_interpretation': 'insufficient_bins'}

        bin_indices = np.digitize(feature_values, bin_edges[1:-1])

        total_approved = (y_true == 1).sum()
        total_denied = (y_true == 0).sum()
        if total_approved == 0 or total_denied == 0:
            return {'iv': 0.0, 'woe_bins': [], 'iv_interpretation': 'single_class'}

        eps = 1e-6  # avoid log(0)
        bins = []
        total_iv = 0.0

        for i in range(len(bin_edges) - 1):
            mask = bin_indices == i
            count = mask.sum()
            if count == 0:
                continue

            bin_approved = (y_true[mask] == 1).sum()
            bin_denied = (y_true[mask] == 0).sum()

            pct_approved = (bin_approved / total_approved) + eps
            pct_denied = (bin_denied / total_denied) + eps

            woe = float(np.log(pct_approved / pct_denied))
            iv_component = float((pct_approved - pct_denied) * woe)
            total_iv += iv_component

            bins.append({
                'bin_low': round(float(bin_edges[i]), 4),
                'bin_high': round(float(bin_edges[i + 1]), 4),
                'count': int(count),
                'approved': int(bin_approved),
                'denied': int(bin_denied),
                'approval_rate': round(float(bin_approved / count), 4) if count > 0 else 0.0,
                'woe': round(woe, 4),
                'iv_component': round(iv_component, 6),
            })

        # Classify IV strength
        if total_iv < 0.02:
            interpretation = 'not_predictive'
        elif total_iv < 0.10:
            interpretation = 'weak'
        elif total_iv < 0.30:
            interpretation = 'medium'
        elif total_iv < 0.50:
            interpretation = 'strong'
        else:
            interpretation = 'suspicious_check_leakage'

        return {
            'iv': round(total_iv, 4),
            'woe_bins': bins,
            'iv_interpretation': interpretation,
        }

    def compute_all_woe_iv(self, df, y_true, numeric_cols, n_bins=10):
        """Compute WOE/IV for all numeric features and return sorted by IV.

        This is the feature selection step in traditional scorecard development.
        Features with IV < 0.02 are typically dropped.
        """
        results = {}
        for col in numeric_cols:
            if col in df.columns:
                result = self.compute_woe_iv(
                    df[col].values, y_true, n_bins=n_bins, feature_name=col
                )
                results[col] = result

        # Sort by IV descending
        sorted_results = dict(
            sorted(results.items(), key=lambda x: x[1]['iv'], reverse=True)
        )
        return sorted_results

    def build_woe_scorecard(self, X_train, y_train, numeric_cols, n_bins=10,
                            X_test=None, y_test=None):
        """Build a traditional WOE logistic regression scorecard.

        This is the standard methodology used by APRA-regulated banks:
        1. Bin each feature and compute WOE values
        2. Replace raw features with their WOE values
        3. Fit logistic regression on WOE-transformed features
        4. Convert coefficients to scorecard points

        Returns the fitted model, WOE lookup tables, and scorecard points.
        The scorecard can be printed on a single page — a key regulatory
        requirement for APRA model documentation.
        """
        woe_tables = {}
        X_woe = pd.DataFrame(index=X_train.index)

        for col in numeric_cols:
            if col not in X_train.columns:
                continue

            result = self.compute_woe_iv(
                X_train[col].values, y_train.values, n_bins=n_bins, feature_name=col
            )

            # Skip features with IV < 0.02 (not predictive)
            if result['iv'] < 0.02 or not result['woe_bins']:
                continue

            woe_tables[col] = result

            # Transform training data: replace values with WOE
            bin_edges = [b['bin_low'] for b in result['woe_bins']] + [result['woe_bins'][-1]['bin_high']]
            woe_values = [b['woe'] for b in result['woe_bins']]
            bin_indices = np.clip(
                np.digitize(X_train[col].values, bin_edges[1:-1]), 0, len(woe_values) - 1
            )
            X_woe[col] = [woe_values[i] for i in bin_indices]

        if X_woe.empty:
            return None, {}, {}

        # Fit logistic regression on WOE features
        lr = LogisticRegression(random_state=42, max_iter=1000, solver='lbfgs')
        lr.fit(X_woe, y_train)

        # Convert to scorecard points (industry standard: base 600, PDO 20)
        # PDO = Points to Double the Odds
        base_score = 600
        pdo = 20  # every 20 points doubles the odds of approval
        factor = pdo / np.log(2)
        offset = base_score - factor * lr.intercept_[0]

        scorecard_points = {}
        for i, col in enumerate(X_woe.columns):
            coef = lr.coef_[0][i]
            woe_bins = woe_tables[col]['woe_bins']
            points = []
            for b in woe_bins:
                score_contribution = round(float(-coef * b['woe'] * factor), 1)
                points.append({
                    'bin_low': b['bin_low'],
                    'bin_high': b['bin_high'],
                    'woe': b['woe'],
                    'points': score_contribution,
                })
            scorecard_points[col] = {
                'coefficient': round(float(coef), 4),
                'iv': woe_tables[col]['iv'],
                'bins': points,
            }

        # Compute out-of-sample AUC if test data provided
        test_auc = None
        if X_test is not None and y_test is not None:
            try:
                X_test_woe = pd.DataFrame(index=X_test.index)
                for col in X_woe.columns:
                    result = woe_tables[col]
                    edges = [b['bin_low'] for b in result['woe_bins']] + [result['woe_bins'][-1]['bin_high']]
                    wvals = [b['woe'] for b in result['woe_bins']]
                    idx = np.clip(np.digitize(X_test[col].values, edges[1:-1]), 0, len(wvals) - 1)
                    X_test_woe[col] = [wvals[i] for i in idx]
                test_auc = round(float(roc_auc_score(y_test, lr.predict_proba(X_test_woe)[:, 1])), 4)
            except Exception:
                test_auc = None

        return lr, woe_tables, {
            'base_score': base_score,
            'pdo': pdo,
            'offset': round(float(offset), 2),
            'factor': round(float(factor), 2),
            'features': scorecard_points,
            'auc_train': round(float(roc_auc_score(y_train, lr.predict_proba(X_woe)[:, 1])), 4),
            'auc_test': test_auc,
        }

    # ==================================================================
    # EXPECTED LOSS (EL = PD x LGD x EAD) — Basel III / APRA APS 113
    # ==================================================================

    # LGD lookup table by loan purpose and LVR band.
    # Based on APRA APS 113 standardised approach and Big 4 bank disclosures.
    LGD_TABLE = {
        'home': {
            'lvr_lt_60': 0.15,    # well-secured, high equity
            'lvr_60_80': 0.22,    # standard home loan
            'lvr_80_90': 0.30,    # high LVR with LMI
            'lvr_gt_90': 0.40,    # very high LVR, limited recovery
        },
        'auto': 0.50,             # secured by depreciating asset
        'personal': 0.75,         # unsecured
        'education': 0.75,        # unsecured
        'business': 0.80,         # unsecured business, highest risk
    }

    def compute_expected_loss(self, pd_value, loan_amount, purpose, lvr=0.0,
                              credit_score=864):
        """Compute Expected Loss = PD x LGD x EAD.

        LGD is determined by loan purpose and LVR band, then adjusted by
        credit score. Higher credit scores reduce LGD because:
        - Better credit borrowers are more likely to cooperate with recovery
        - They have more assets and income to satisfy shortfalls
        - They're less likely to abandon the property (strategic default)

        This credit-score-sensitive LGD is standard practice at Big 4 banks
        under APRA APS 113. The adjustment range is +/-20% of base LGD.

        Args:
            pd_value: Probability of Default (from model)
            loan_amount: Exposure at Default (simplified as loan balance)
            purpose: Loan purpose for LGD lookup
            lvr: Loan-to-Value Ratio (for home loans)
            credit_score: Equifax score (0-1200) for LGD adjustment

        Returns:
            dict with el (dollar amount), pd, lgd, ead components.
        """
        ead = float(loan_amount)

        # Base LGD from lookup table
        if purpose == 'home':
            if lvr < 0.60:
                base_lgd = self.LGD_TABLE['home']['lvr_lt_60']
            elif lvr < 0.80:
                base_lgd = self.LGD_TABLE['home']['lvr_60_80']
            elif lvr < 0.90:
                base_lgd = self.LGD_TABLE['home']['lvr_80_90']
            else:
                base_lgd = self.LGD_TABLE['home']['lvr_gt_90']
        else:
            base_lgd = self.LGD_TABLE.get(purpose, 0.75)

        # Credit score adjustment: +/-20% of base LGD.
        # Score 864 (national avg) = no adjustment.
        # Score 1200 (perfect) = -20% LGD (better recovery).
        # Score 300 (worst) = +20% LGD (worse recovery).
        credit_norm = np.clip((credit_score - 300) / 900, 0, 1)  # 0-1 scale
        credit_adj = 1.0 + 0.20 * (0.5 - credit_norm)  # range 0.80 to 1.20
        lgd = float(np.clip(base_lgd * credit_adj, 0.05, 0.95))

        el = pd_value * lgd * ead

        return {
            'expected_loss': round(el, 2),
            'pd': round(pd_value, 4),
            'lgd': round(lgd, 4),
            'lgd_base': round(base_lgd, 4),
            'lgd_credit_adjustment': round(float(credit_adj), 4),
            'ead': round(ead, 2),
            'purpose': purpose,
            'lvr_used': round(lvr, 4) if purpose == 'home' else None,
        }

    # ==================================================================
    # ADVERSARIAL VALIDATION
    # ==================================================================

    def adversarial_validation(self, X_train, X_test):
        """Check if a classifier can distinguish training from test data.

        If AUC > 0.55, the distributions are measurably different, which
        means the model may not generalise well from train to test.
        AUC near 0.50 means the distributions are indistinguishable (good).
        """
        n_train = len(X_train)
        n_test = len(X_test)

        X_combined = np.vstack([X_train, X_test])
        y_combined = np.concatenate([np.zeros(n_train), np.ones(n_test)])

        lr = LogisticRegression(random_state=42, max_iter=500, solver='lbfgs')
        # Simple cross-val: train on 80%, test on 20%
        from sklearn.model_selection import cross_val_score
        scores = cross_val_score(lr, X_combined, y_combined, cv=3, scoring='roc_auc')
        mean_auc = float(np.mean(scores))

        return {
            'auc': round(mean_auc, 4),
            'distribution_match': mean_auc < 0.55,
            'status': 'good' if mean_auc < 0.55 else 'warning' if mean_auc < 0.60 else 'mismatch',
        }

    # ==================================================================
    # CONCENTRATION RISK — APRA APS 221
    # ==================================================================

    def compute_concentration_risk(self, df, group_col):
        """Compute Herfindahl-Hirschman Index (HHI) for portfolio concentration.

        HHI = sum(share_i^2) where share_i is the proportion in each segment.
        HHI ranges from 1/N (perfectly diversified) to 1.0 (fully concentrated).

        Industry thresholds:
          HHI < 0.15: well-diversified
          HHI 0.15-0.25: moderate concentration
          HHI > 0.25: high concentration (APRA APS 221 trigger)
        """
        if group_col not in df.columns:
            return {'hhi': 0.0, 'status': 'column_not_found', 'segments': {}}

        counts = df[group_col].value_counts()
        shares = counts / counts.sum()
        hhi = float((shares ** 2).sum())

        if hhi < 0.15:
            status = 'well_diversified'
        elif hhi < 0.25:
            status = 'moderate_concentration'
        else:
            status = 'high_concentration'

        max_segment = shares.idxmax()
        max_share = float(shares.max())

        return {
            'hhi': round(hhi, 4),
            'status': status,
            'max_segment': str(max_segment),
            'max_share': round(max_share, 4),
            'exceeds_40pct': max_share > 0.40,
            'segments': {str(k): round(float(v), 4) for k, v in shares.items()},
        }
