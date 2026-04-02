import logging
import os
import time

import joblib
import numpy as np
import pandas as pd
from django.conf import settings
from sklearn.ensemble import RandomForestClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GridSearchCV, RandomizedSearchCV, StratifiedKFold, cross_val_score, train_test_split
from sklearn.preprocessing import StandardScaler

from .metrics import MetricsService

logger = logging.getLogger(__name__)


class _CalibratedModel:
    """Wraps a fitted classifier with probability calibration.

    Supports adaptive calibration method selection:
    - isotonic: for >= 1000 validation samples (more flexible, non-parametric)
    - sigmoid (Platt scaling): for < 1000 samples (avoids overfitting)

    Replaces sklearn's CalibratedClassifierCV(cv='prefit') which was
    removed in scikit-learn 1.8.
    """

    def __init__(self, estimator, X_val, y_val, calibration_method=None):
        self.estimator = estimator
        val_probs = estimator.predict_proba(X_val)[:, 1]

        # Adaptive calibration method selection
        if calibration_method is None:
            if len(X_val) >= 1000:
                calibration_method = "isotonic"
                logger.info("Using isotonic calibration (%d validation samples >= 1000 threshold)", len(X_val))
            else:
                calibration_method = "sigmoid"
                logger.info(
                    "Using Platt scaling (%d validation samples < 1000 threshold — isotonic would overfit)", len(X_val)
                )

        self.calibration_method = calibration_method

        if calibration_method == "isotonic":
            self._calibrator = IsotonicRegression(out_of_bounds="clip")
            self._calibrator.fit(val_probs, y_val)
        else:
            # Platt scaling: logistic regression on predicted probabilities
            from sklearn.linear_model import LogisticRegression as _PlattLR

            self._calibrator = _PlattLR(max_iter=1000)
            self._calibrator.fit(val_probs.reshape(-1, 1), y_val)

    def predict(self, X):
        return self.estimator.predict(X)

    def predict_proba(self, X):
        raw_probs = self.estimator.predict_proba(X)[:, 1]
        # Backward compat: old model bundles may not have calibration_method attribute
        method = getattr(self, "calibration_method", "isotonic")
        if method == "isotonic":
            calibrated = self._calibrator.predict(raw_probs)
        else:
            calibrated = self._calibrator.predict_proba(raw_probs.reshape(-1, 1))[:, 1]
        calibrated = np.clip(calibrated, 0.0, 1.0)
        return np.column_stack([1 - calibrated, calibrated])

    def get_underlying_estimator(self):
        """Return the raw tree model for SHAP explainability."""
        return self.estimator

    @property
    def feature_importances_(self):
        return self.estimator.feature_importances_


class ModelTrainer:
    """Handles model training with GridSearchCV."""

    CATEGORICAL_COLS = [
        "purpose",
        "home_ownership",
        "employment_type",
        "applicant_type",
        "state",
        "savings_trend_3m",
        "industry_risk_tier",
        "sa3_region",
        "industry_anzsic",
    ]
    NUMERIC_COLS = [
        "annual_income",
        "credit_score",
        "loan_amount",
        "loan_term_months",
        "debt_to_income",
        "employment_length",
        "has_cosigner",
        "property_value",
        "deposit_amount",
        "monthly_expenses",
        "existing_credit_card_limit",
        "number_of_dependants",
        "has_hecs",
        "has_bankruptcy",
        # Bureau features (Equifax/Illion credit report data)
        "num_credit_enquiries_6m",
        "worst_arrears_months",
        "num_defaults_5yr",
        "credit_history_months",
        "total_open_accounts",
        "num_bnpl_accounts",
        # Behavioural features (existing customer internal data)
        "is_existing_customer",
        "savings_balance",
        "salary_credit_regularity",
        "num_dishonours_12m",
        "avg_monthly_savings_rate",
        "days_in_overdraft_12m",
        # Macroeconomic context
        "rba_cash_rate",
        "unemployment_rate",
        "property_growth_12m",
        "consumer_confidence",
        # Application integrity
        "income_verification_gap",
        "document_consistency_score",
        # Derived ratios
        "lvr",
        "loan_to_income",
        "credit_card_burden",
        "expense_to_income",
        # Feature interactions (standard in Big 4 bank scorecards)
        "lvr_x_dti",
        "income_credit_interaction",
        "serviceability_ratio",
        "employment_stability",
        # Additional features (Prospa/Athena-style — improves discrimination)
        "deposit_ratio",
        "monthly_repayment_ratio",
        "net_monthly_surplus",
        "income_per_dependant",
        "credit_score_x_tenure",
        # Bureau-derived
        "enquiry_intensity",
        "bureau_risk_score",
        "rate_stress_buffer",
        # Open Banking features (Plaid/Basiq-inspired)
        "discretionary_spend_ratio",
        "gambling_transaction_flag",
        "bnpl_active_count",
        "overdraft_frequency_90d",
        "income_verification_score",
        # CCR features
        "num_late_payments_24m",
        "worst_late_payment_days",
        "total_credit_limit",
        "credit_utilization_pct",
        "num_hardship_flags",
        "months_since_last_default",
        "num_credit_providers",
        # BNPL-specific
        "bnpl_total_limit",
        "bnpl_utilization_pct",
        "bnpl_late_payments_12m",
        "bnpl_monthly_commitment",
        # CDR/Open Banking transaction features
        "income_source_count",
        "rent_payment_regularity",
        "utility_payment_regularity",
        "essential_to_total_spend",
        "subscription_burden",
        "balance_before_payday",
        "min_balance_30d",
        "days_negative_balance_90d",
        # Geographic risk
        "postcode_default_rate",
        # APRA stress test derived
        "stressed_repayment",
        "stressed_dsr",
        "hem_surplus",
        "uncommitted_monthly_income",
        # Additional derived ratios
        "savings_to_loan_ratio",
        "debt_service_coverage",
        "bnpl_to_income_ratio",
        "enquiry_to_account_ratio",
        "stress_index",
        "log_annual_income",
        "log_loan_amount",
        # New calibration variables (APRA/ABS/Equifax 2025-2026)
        "hecs_debt_balance",
        "existing_property_count",
        "cash_advance_count_12m",
        "monthly_rent",
        "gambling_spend_ratio",
        # Sub-state geography and industry (webscraping enhancement)
        "help_repayment_monthly",
    ]

    def __init__(self):
        self.scaler = StandardScaler()
        self.ohe_columns = None  # column names after one-hot encoding
        self.metrics_service = MetricsService()
        self._reference_distribution = None  # saved for PSI drift detection
        self._imputation_values = {}  # stored in model bundle for predictor alignment

    def add_derived_features(self, df):
        """Add engineered features: LVR, loan-to-income, credit card burden, expense-to-income.

        Handles missing values (NaN) in optional fields by imputing with
        sensible defaults before computing derived features.
        Stores imputation values so the predictor can use the same ones.

        Delegates actual feature computation to the shared
        feature_engineering module (single source of truth).
        """
        from .feature_engineering import (
            DEFAULT_IMPUTATION_VALUES,
            compute_derived_features,
            impute_missing_values,
        )

        df = df.copy()

        # Compute data-dependent imputation values: use training data medians
        # for all numeric columns, with shared defaults as fallback.
        data_medians = {}
        for col in self.NUMERIC_COLS:
            if col in df.columns and df[col].notna().any():
                data_medians[col] = float(df[col].median())
        self._imputation_values = {**DEFAULT_IMPUTATION_VALUES, **data_medians}

        df = impute_missing_values(df, self._imputation_values)
        df = compute_derived_features(df)
        return df

    def fit_preprocess(self, df):
        """Fit encoders/scaler on training data and transform it.

        Returns (transformed DataFrame, feature column names).
        """
        df = df.copy()

        # Add derived features before encoding/scaling
        df = self.add_derived_features(df)

        # One-hot encode categorical columns
        df = pd.get_dummies(df, columns=self.CATEGORICAL_COLS, dtype=float)

        # Determine feature columns: numeric + all one-hot columns
        ohe_cols = [c for c in df.columns if any(c.startswith(cat + "_") for cat in self.CATEGORICAL_COLS)]
        feature_cols = self.NUMERIC_COLS + sorted(ohe_cols)
        self.ohe_columns = feature_cols  # save for transform

        # Fit and transform numeric + encoded features
        df[feature_cols] = self.scaler.fit_transform(df[feature_cols])

        return df, feature_cols

    def transform(self, df):
        """Transform new data using already-fit scaler and column schema.

        Must call fit_preprocess first.
        """
        if self.ohe_columns is None:
            raise RuntimeError("Must call fit_preprocess before transform")

        df = df.copy()

        # Add derived features before encoding/scaling
        df = self.add_derived_features(df)

        # One-hot encode categorical columns
        df = pd.get_dummies(df, columns=self.CATEGORICAL_COLS, dtype=float)

        # Align columns: add missing columns as 0, drop extra columns from new categories
        for col in self.ohe_columns:
            if col not in df.columns:
                df[col] = 0.0
        extra_cols = [c for c in df.columns if c not in self.ohe_columns]
        df = df[self.ohe_columns + extra_cols]

        # Scale using already-fit scaler
        df[self.ohe_columns] = self.scaler.transform(df[self.ohe_columns])

        return df, self.ohe_columns

    # ------------------------------------------------------------------
    # Data splitting strategies
    # ------------------------------------------------------------------

    def _split_data(self, df, y):
        """Split data into train/val/test. Uses temporal split if possible."""
        if "application_quarter" in df.columns:
            result = self._temporal_split(df, y)
            if result is not None:
                return result
            logger.warning("Temporal split failed; falling back to random split")
        return self._random_split(df, y)

    def _random_split(self, df, y):
        """Standard 80/10/10 random stratified split."""
        df_train, df_temp, y_train, y_temp = train_test_split(df, y, test_size=0.2, random_state=42, stratify=y)
        df_val, df_test, y_val, y_test = train_test_split(
            df_temp, y_temp, test_size=0.5, random_state=42, stratify=y_temp
        )
        return (
            df_train,
            df_val,
            df_test,
            y_train,
            y_val,
            y_test,
            {
                "split_strategy": "random_stratified",
            },
        )

    def _temporal_split(self, df, y):
        """Time-based split: train on earlier quarters, validate/test on later.

        Returns None if temporal split is not viable (too few quarters or
        insufficient class variety in a split).
        """
        quarters = sorted(df["application_quarter"].unique())
        n_q = len(quarters)
        if n_q < 3:
            logger.info("Only %d quarter(s) — need >=3 for temporal split", n_q)
            return None

        # Train: first ~75%, Val: next slice, Test: last slice
        train_end = max(1, int(n_q * 0.75))
        val_end = train_end + max(1, (n_q - train_end) // 2)

        train_quarters = list(quarters[:train_end])
        val_quarters = list(quarters[train_end:val_end])
        test_quarters = list(quarters[val_end:])

        # Ensure test is not empty
        if not test_quarters:
            test_quarters = [quarters[-1]]
            if quarters[-1] in val_quarters:
                val_quarters.remove(quarters[-1])

        train_mask = df["application_quarter"].isin(train_quarters)
        val_mask = df["application_quarter"].isin(val_quarters)
        test_mask = df["application_quarter"].isin(test_quarters)

        # Both classes must be present in val and test
        if y[val_mask].nunique() < 2 or y[test_mask].nunique() < 2:
            logger.info("Temporal split has insufficient class variety in val/test")
            return None

        meta = {
            "split_strategy": "temporal",
            "train_quarters": train_quarters,
            "val_quarters": val_quarters,
            "test_quarters": test_quarters,
        }
        return (
            df[train_mask],
            df[val_mask],
            df[test_mask],
            y[train_mask],
            y[val_mask],
            y[test_mask],
            meta,
        )

    def train(self, data_path, algorithm="xgb", use_reject_inference=True, reject_inference_labels=None):
        """Train model with GridSearchCV and return model + metrics.

        Parameters
        ----------
        data_path : str
            Path to CSV training data.
        algorithm : str
            'xgb' or 'rf'.
        use_reject_inference : bool
            If True and reject_inference_labels is provided, augment training
            data with denied applications at reduced weight (0.5) to mitigate
            selection bias from only training on approved loans.
        reject_inference_labels : pd.Series or None
            Series of inferred outcomes for denied applications, indexed to
            match the rows in the CSV. Typically from
            DataGenerator.reject_inference_labels.
        """
        start_time = time.time()

        # Load data
        df = pd.read_csv(data_path)

        if len(df) < 20:
            raise ValueError(f"Dataset too small for training: {len(df)} rows (minimum 20 required)")

        y = df["approved"]
        class_counts = y.value_counts()
        if class_counts.min() < 5:
            raise ValueError(f"Insufficient class balance: {dict(class_counts)}. Each class needs at least 5 samples.")

        # Split BEFORE preprocessing to avoid data leakage.
        # Uses temporal split (by application_quarter) if available,
        # otherwise falls back to random stratified 80/10/10.
        df_train, df_val, df_test, y_train, y_val, y_test, split_meta = self._split_data(df, y)

        # Drop application_quarter from feature DataFrames (used only for splitting)
        for split_df in [df_train, df_val, df_test]:
            if "application_quarter" in split_df.columns:
                split_df.drop(columns=["application_quarter"], inplace=True)
        if "application_quarter" in df.columns:
            df = df.drop(columns=["application_quarter"])

        # Capture reference distribution for PSI drift detection (APRA CPG 235).
        # Computed on training data ONLY (not full dataset) to avoid data leakage.
        # Stores both percentile summaries and histogram bin counts/edges for PSI.
        ref_dist = {}
        for col in self.NUMERIC_COLS:
            if col in df_train.columns:
                vals = df_train[col].dropna().values
                if len(vals) > 0:
                    percentiles = np.percentile(vals, np.arange(0, 101, 10)).tolist()
                    # Histogram bins for proper PSI computation
                    bin_edges = np.percentile(vals, np.linspace(0, 100, 11))
                    bin_edges = np.unique(bin_edges)
                    if len(bin_edges) >= 3:
                        hist_counts = np.histogram(vals, bins=bin_edges)[0]
                    else:
                        hist_counts = np.array([])
                        bin_edges = np.array([])
                    ref_dist[col] = {
                        "percentiles": percentiles,
                        "mean": float(np.mean(vals)),
                        "std": float(np.std(vals)),
                        "n": len(vals),
                        "histogram_counts": hist_counts.tolist(),
                        "histogram_edges": bin_edges.tolist(),
                    }
        self._reference_distribution = ref_dist

        # Data-driven feature bounds: [1st percentile, 99th percentile]
        feature_bounds = {}
        for col in self.NUMERIC_COLS:
            if col in df_train.columns:
                vals = df_train[col].dropna().values
                if len(vals) > 10:
                    p1, p99 = float(np.percentile(vals, 1)), float(np.percentile(vals, 99))
                    feature_bounds[col] = (p1, p99)
        self._feature_bounds = feature_bounds

        # Save original test indices before transform() resets them
        test_original_indices = df_test.index.copy()

        # Save raw copies BEFORE preprocessing for WOE scorecard (C4 fix).
        # WOE bins must be in interpretable units (credit_score 650-750),
        # not z-score units from StandardScaler.
        df_train_raw = self.add_derived_features(df_train.copy())
        df_test_raw = self.add_derived_features(df_test.copy())

        # ------------------------------------------------------------------
        # IV-based feature selection: keep only features with meaningful
        # predictive power (IV >= 0.02) and flag potential leakage (IV > 0.5).
        # Runs on raw training data BEFORE scaling to get interpretable IV.
        # ------------------------------------------------------------------
        from .feature_engineering import DERIVED_FEATURE_NAMES
        from .feature_selection import select_features_by_iv

        all_numeric = [c for c in self.NUMERIC_COLS if c in df_train_raw.columns]
        derived_in_raw = [c for c in DERIVED_FEATURE_NAMES if c in df_train_raw.columns]
        # Deduplicate: some derived features may already be in NUMERIC_COLS
        iv_candidates = list(dict.fromkeys(all_numeric + derived_in_raw))

        # iv_max=1.5: on synthetic data, core credit features (DTI, LVR,
        # loan_to_income) legitimately have IV > 0.5 because the data
        # generator uses them directly. Only flag truly extreme IV (>1.5)
        # as potential leakage.
        iv_result = select_features_by_iv(
            df_train_raw,
            iv_candidates,
            target="approved",
            iv_min=0.02,
            iv_max=1.5,
        )
        selected_numeric = iv_result["selected_features"]
        self._iv_result = iv_result  # store for metrics later
        self._original_numeric_cols = list(self.NUMERIC_COLS)

        logger.info(
            "IV feature selection: %d/%d features retained (excluded %d weak, %d leakage)",
            len(selected_numeric),
            len(iv_candidates),
            len(iv_result["excluded_weak"]),
            len(iv_result["excluded_leakage"]),
        )
        if iv_result["excluded_leakage"]:
            logger.warning("Leakage suspects: %s", iv_result["excluded_leakage"])

        # Override NUMERIC_COLS for this training run so fit_preprocess
        # only assembles the selected features
        self.NUMERIC_COLS = selected_numeric

        # Fit preprocessing on training data only
        df_train, feature_cols = self.fit_preprocess(df_train)
        X_train = df_train[feature_cols]

        # Transform val and test using already-fit encoders/scaler
        df_val, _ = self.transform(df_val)
        X_val = df_val[feature_cols]

        df_test, _ = self.transform(df_test)
        X_test = df_test[feature_cols]

        # Fairness reweighting: compute sample weights to reduce employment
        # type disparate impact (DI). Without this, DI ~0.38 (failing EEOC 80%
        # rule). Reweighting assigns higher weights to underrepresented
        # employment groups so the model doesn't systematically deny them.
        # See: MATLAB bias mitigation methodology (mathworks.com/help/risk/
        # bias-mitigation-for-credit-scoring-model-by-reweighting.html)
        sample_weights = None
        if "employment_type" in df_train.columns:
            emp_groups = df_train["employment_type"]
            group_counts = emp_groups.value_counts()
            total = len(emp_groups)
            n_groups = len(group_counts)
            # Weight = (total / n_groups) / group_count — equalises group representation
            weight_map = {group: (total / n_groups) / count for group, count in group_counts.items()}
            sample_weights = emp_groups.map(weight_map).values
            # Normalise so weights sum to len(y_train)
            sample_weights = sample_weights * total / sample_weights.sum()
            logger.info(
                "Fairness reweighting applied: %s",
                {g: round(w, 3) for g, w in weight_map.items()},
            )

        # ------------------------------------------------------------------
        # Reject-inference-aware training: include denied applications at
        # reduced weight to mitigate selection bias (only training on
        # approved loans would teach the model that approved-looking
        # profiles are always good).
        # ------------------------------------------------------------------
        if use_reject_inference and reject_inference_labels is not None:
            # Identify denied rows in the TRAINING split only (avoid leakage)
            denied_mask = df_train["approved"] == 0
            denied_indices = df_train.index[denied_mask]
            # Keep only denied rows that have reject inference labels
            ri_available = denied_indices.intersection(reject_inference_labels.index)
            if len(ri_available) > 0:
                ri_labels = reject_inference_labels.loc[ri_available]
                # Preprocess denied rows through the already-fit pipeline
                df_denied = df_train.loc[ri_available].copy()
                df_denied_transformed, _ = self.transform(df_denied)
                X_denied = df_denied_transformed[feature_cols]

                # Augment training data
                X_train = pd.concat([X_train, X_denied], ignore_index=True)
                y_train = pd.concat(
                    [y_train.reset_index(drop=True), ri_labels.reset_index(drop=True)], ignore_index=True
                )

                # Build reject-inference weight vector: 1.0 for original, 0.5 for inferred
                n_original = len(y_train) - len(ri_labels)
                ri_weights = np.concatenate(
                    [
                        np.ones(n_original),
                        np.full(len(ri_labels), 0.5),
                    ]
                )

                # Multiply with existing fairness weights if present
                if sample_weights is not None:
                    # Extend fairness weights for the new denied rows (use 1.0 — no group info after OHE)
                    extended_fairness = np.concatenate(
                        [
                            sample_weights,
                            np.ones(len(ri_labels)),
                        ]
                    )
                    sample_weights = extended_fairness * ri_weights
                else:
                    sample_weights = ri_weights

                # Re-normalise so weights sum to len(y_train)
                sample_weights = sample_weights * len(y_train) / sample_weights.sum()

                logger.info(
                    "Reject inference: augmented training set with %d denied applications at 0.5 weight "
                    "(total training size: %d)",
                    len(ri_labels),
                    len(y_train),
                )
            else:
                logger.info("Reject inference: no matching denied rows in training split, skipping")

        # ------------------------------------------------------------------
        # K-fold cross-validation for robust metric estimation.
        # Runs BEFORE the final model training to get an unbiased estimate
        # of generalisation performance across multiple data splits.
        # ------------------------------------------------------------------
        logger.info("Running 3-fold stratified cross-validation...")
        cv = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
        neg_count_cv = int((y_train == 0).sum())
        pos_count_cv = int((y_train == 1).sum())
        from xgboost import XGBClassifier as _CVXGBClassifier

        cv_model = _CVXGBClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.1,
            random_state=42,
            eval_metric="logloss",
            n_jobs=1,
            scale_pos_weight=neg_count_cv / pos_count_cv if pos_count_cv > 0 else 1.0,
        )
        cv_scores = cross_val_score(cv_model, X_train, y_train, cv=cv, scoring="roc_auc")
        cv_mean = float(cv_scores.mean())
        cv_std = float(cv_scores.std())
        logger.info("3-fold CV AUC-ROC: %.4f +/- %.4f", cv_mean, cv_std)
        # Flag instability if any fold deviates >3% from mean (range > 6%)
        cv_unstable = bool(cv_scores.max() - cv_scores.min() > 0.06)
        if cv_unstable:
            logger.warning(
                "CV fold variance is high (range %.4f) — model may be unstable",
                cv_scores.max() - cv_scores.min(),
            )

        cv_report = {
            "n_splits": 3,
            "strategy": "StratifiedKFold",
            "scoring": "roc_auc",
            "fold_scores": cv_scores.tolist(),
            "mean": cv_mean,
            "std": cv_std,
            "min": float(cv_scores.min()),
            "max": float(cv_scores.max()),
            "range": float(cv_scores.max() - cv_scores.min()),
            "unstable": cv_unstable,
        }

        if algorithm == "xgb":
            raw_model, best_params = self._train_xgb(X_train, y_train, X_val, y_val, sample_weights=sample_weights)
        else:
            raw_model, best_params = self._train_rf(X_train, y_train, X_val, y_val, sample_weights=sample_weights)

        # Probability calibration on validation set only (avoids data leakage
        # since GridSearchCV already used cross-validation on the training set).
        # Adaptive method: isotonic for >= 1000 samples, Platt scaling otherwise.
        model = _CalibratedModel(raw_model, X_val, y_val)

        # Cost-optimal threshold via MetricsService (FP:FN = 5:1 banking cost matrix)
        val_probs = model.predict_proba(X_val)[:, 1]
        metrics_svc = MetricsService()
        val_threshold_analysis = metrics_svc.compute_threshold_analysis(y_val, val_probs)
        optimal_threshold = float(val_threshold_analysis["cost_optimal_threshold"])
        f1_threshold = float(val_threshold_analysis["f1_optimal_threshold"])
        logger.info("Cost-optimal threshold: %.3f (F1-optimal: %.3f)", optimal_threshold, f1_threshold)

        # Conformal prediction: compute nonconformity scores on validation set.
        # These are stored in the model bundle and used at inference time to
        # produce prediction intervals with guaranteed coverage.
        # Nonconformity score = |predicted_prob - actual_outcome|
        y_val_prob = model.predict_proba(X_val)[:, 1]
        self._conformal_scores = np.sort(np.abs(y_val_prob - y_val.values))

        # Evaluate on test set only (val was used implicitly via GridSearchCV)
        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1]

        metrics = self.metrics_service.compute_metrics(y_test, y_pred, y_prob)
        metrics["confusion_matrix"] = self.metrics_service.confusion_matrix_data(y_test, y_pred)
        metrics["roc_curve"] = self.metrics_service.roc_curve_data(y_test, y_prob)
        metrics["feature_importances"] = self.metrics_service.feature_importance_data(model, feature_cols)
        metrics["training_params"] = best_params

        # New banking metrics
        metrics["gini_coefficient"] = self.metrics_service.compute_gini(y_test, y_prob)
        ks_result = self.metrics_service.compute_ks_statistic(y_test, y_prob)
        metrics["ks_statistic"] = ks_result["ks_statistic"]
        metrics["log_loss"] = self.metrics_service.compute_log_loss(y_test, y_prob)
        metrics["calibration_data"] = self.metrics_service.compute_calibration_data(y_test, y_prob)
        metrics["threshold_analysis"] = self.metrics_service.compute_threshold_analysis(y_test, y_prob)
        metrics["decile_analysis"] = self.metrics_service.compute_decile_analysis(y_test, y_prob)

        # Overfitting detection — derive predictions from probabilities
        # to avoid a redundant full inference pass on the training set
        y_train_pred_prob = model.predict_proba(X_train)[:, 1]
        train_auc = round(float(roc_auc_score(y_train, y_train_pred_prob)), 4)
        test_auc = metrics["auc_roc"]
        overfitting_gap = round(train_auc - test_auc, 4)
        if overfitting_gap > 0.05:
            logger.warning(
                "Overfitting detected: train AUC %.4f vs test AUC %.4f (gap: %.4f)",
                train_auc,
                test_auc,
                overfitting_gap,
            )

        training_time = round(time.time() - start_time, 2)
        metrics["training_time_seconds"] = training_time
        metrics["optimal_threshold"] = optimal_threshold
        metrics["training_metadata"] = {
            "train_size": len(y_train),
            "val_size": len(y_val),
            "test_size": len(y_test),
            "class_balance": round(float(y.mean()), 4),
            "training_time_seconds": training_time,
            "overfitting_gap": overfitting_gap,
            "train_auc": round(train_auc, 4),
            "n_features": len(feature_cols),
            "cv_auc_mean": cv_mean,
            "cv_auc_std": cv_std,
            "cv_auc_per_fold": cv_scores.tolist(),
            "cv_unstable": cv_unstable,
            "cv_report": cv_report,
            "optimal_threshold": optimal_threshold,
            "calibration_method": getattr(model, "calibration_method", "unknown"),
            "group_thresholds": getattr(self, "_group_thresholds", {}),
            "iv_features_selected": len(getattr(self, "_iv_result", {}).get("selected_features", [])),
            "iv_features_excluded_weak": len(getattr(self, "_iv_result", {}).get("excluded_weak", [])),
            "iv_features_excluded_leakage": len(getattr(self, "_iv_result", {}).get("excluded_leakage", [])),
            **split_meta,
        }

        # Fairness metrics with full TPR/FPR/disparate impact
        fairness_metrics = {}
        for col in ["employment_type", "applicant_type", "state"]:
            if col in df.columns:
                test_indices = test_original_indices
                original_vals = df.loc[test_indices, col] if col in df.columns else pd.Series()
                if len(original_vals) > 0:
                    fairness_result = self.metrics_service.compute_fairness_metrics(
                        y_test.values, y_pred, y_prob, original_vals.values
                    )
                    fairness_metrics[col] = fairness_result
        metrics["fairness"] = fairness_metrics

        # Post-processing: per-group threshold adjustment for employment_type
        # Ensures disparate impact meets EEOC 80% rule (DI >= 0.80)
        group_thresholds = {}
        target_di = getattr(settings, "ML_FAIRNESS_TARGET_DI", 0.80)

        if "employment_type" in fairness_metrics and "employment_type" in df_test_raw.columns:
            emp_groups = fairness_metrics["employment_type"]["groups"]
            max_approval = max(g["predicted_approval_rate"] for g in emp_groups.values())
            target_approval = max_approval * target_di

            # Use raw test data for group membership (before one-hot encoding)
            test_emp_values = df_test_raw["employment_type"].values

            for group_name, group_data in emp_groups.items():
                if group_data["predicted_approval_rate"] >= target_approval:
                    group_thresholds[group_name] = optimal_threshold
                else:
                    group_mask = test_emp_values == group_name
                    group_probs = y_prob[group_mask]
                    if len(group_probs) == 0:
                        group_thresholds[group_name] = optimal_threshold
                        continue
                    # Lower threshold until approval rate meets target
                    for t in np.arange(optimal_threshold, 0.05, -0.01):
                        rate = float((group_probs >= t).mean())
                        if rate >= target_approval:
                            group_thresholds[group_name] = float(round(t, 2))
                            break
                    else:
                        group_thresholds[group_name] = 0.05  # floor

            logger.info(
                "Per-group fairness thresholds: %s (target DI: %.2f, target approval: %.3f)",
                group_thresholds,
                target_di,
                target_approval,
            )

        self._group_thresholds = group_thresholds

        # WOE/IV analysis on RAW (unscaled) data so bin edges are in
        # interpretable units (credit_score 650-750, not z-scores).
        try:
            woe_iv = self.metrics_service.compute_all_woe_iv(
                df_test_raw[self.NUMERIC_COLS], y_test, self.NUMERIC_COLS, n_bins=10
            )
            metrics["woe_iv"] = {
                col: {"iv": v["iv"], "interpretation": v["iv_interpretation"]}
                for col, v in woe_iv.items()
                if v["iv"] >= 0.02
            }
        except Exception:
            logger.warning("WOE/IV computation failed", exc_info=True)
            metrics["woe_iv"] = {}

        # WOE logistic regression scorecard on RAW data with out-of-sample AUC.
        try:
            _, _, scorecard = self.metrics_service.build_woe_scorecard(
                df_train_raw[self.NUMERIC_COLS],
                y_train,
                self.NUMERIC_COLS,
                n_bins=10,
                X_test=df_test_raw[self.NUMERIC_COLS],
                y_test=y_test,
            )
            if scorecard:
                metrics["woe_scorecard"] = scorecard
        except Exception:
            logger.warning("WOE scorecard build failed", exc_info=True)

        # Adversarial validation: can a classifier distinguish train from test?
        try:
            adv = self.metrics_service.adversarial_validation(X_train.values, X_test.values)
            metrics["adversarial_validation"] = adv
        except Exception:
            logger.warning("Adversarial validation failed", exc_info=True)

        # Concentration risk (APRA APS 221)
        try:
            metrics["concentration_risk"] = {}
            for col in ["purpose", "employment_type", "state"]:
                if col in df.columns:
                    metrics["concentration_risk"][col] = self.metrics_service.compute_concentration_risk(df, col)
        except Exception:
            logger.warning("Concentration risk computation failed", exc_info=True)

        # Vintage analysis (if temporal data present)
        if all(c in df_test_raw.columns for c in ["origination_quarter", "months_on_book"]):
            from .metrics import VintageAnalyser

            test_with_temporal = df_test_raw.copy()
            test_with_temporal["default_flag"] = y_test
            test_with_temporal["prediction_probability"] = y_prob

            vintage_curves = VintageAnalyser.compute_vintage_curves(test_with_temporal)
            survival = VintageAnalyser.compute_survival_metrics(test_with_temporal)
            temporal_psi = VintageAnalyser.compute_temporal_psi(test_with_temporal)
            concentration = VintageAnalyser.compute_concentration_by_vintage(test_with_temporal)

            metrics["vintage_analysis"] = {
                "vintage_curves": vintage_curves,
                "survival_metrics": survival,
                "temporal_psi": temporal_psi,
                "concentration_by_vintage": concentration,
            }

        # TSTR validation: estimate real-world performance degradation
        try:
            from .tstr_validator import TSTRValidator

            tstr = TSTRValidator()
            tstr_result = tstr.validate(metrics)
            metrics["tstr_validation"] = tstr_result
            metrics["training_metadata"]["tstr_validation"] = tstr_result
            logger.info("TSTR validation: %s", tstr_result.get("summary", ""))
        except Exception:
            logger.warning("TSTR validation failed", exc_info=True)

        return model, metrics

    def _train_rf(self, X_train, y_train, X_val, y_val, sample_weights=None):
        """Train Random Forest with GridSearchCV."""
        param_grid = {
            "n_estimators": [100, 200],
            "max_depth": [10, 20, None],
            "min_samples_split": [2, 5],
        }
        rf = RandomForestClassifier(random_state=42, class_weight="balanced")
        grid = GridSearchCV(
            rf,
            param_grid,
            cv=StratifiedKFold(n_splits=3, shuffle=True, random_state=42),
            scoring="roc_auc",
            n_jobs=-1,
            verbose=0,
        )
        fit_params = {}
        if sample_weights is not None:
            fit_params["sample_weight"] = sample_weights
        grid.fit(X_train, y_train, **fit_params)
        return grid.best_estimator_, grid.best_params_

    def _build_monotonic_constraints(self, feature_cols):
        """Build monotonic constraint vector for XGBoost.

        In credit risk modelling, certain relationships MUST be monotonic:
        - Higher credit score → higher approval probability (positive)
        - Higher income → higher approval probability (positive)
        - Higher debt-to-income → lower approval probability (negative)
        - Higher employment length → higher approval probability (positive)
        - Bankruptcy → lower approval probability (negative)

        XGBoost enforces these during tree construction, preventing the
        model from learning spurious non-monotonic patterns from noise.
        This is a regulatory expectation: APRA and ASIC expect that a
        model won't approve someone with a lower credit score over
        someone identical but with a higher score.

        Returns a tuple of (1, -1, 0) for each feature:
          1 = monotonically increasing (more → more likely approved)
         -1 = monotonically decreasing (more → less likely approved)
          0 = unconstrained
        """
        # Up to 21 constraints. Using max_bin=512 to compensate for the larger
        # constraint set and preserve sufficient split candidates.
        constraints = {
            # Positive: higher value → more likely approved
            "credit_score": 1,
            "annual_income": 1,
            "employment_length": 1,
            "savings_balance": 1,
            "credit_history_months": 1,
            "salary_credit_regularity": 1,
            "income_verification_score": 1,
            # Additional positive: higher value → more likely approved
            "property_value": 1,
            "deposit_amount": 1,
            "has_cosigner": 1,
            "on_time_payment_pct": 1,
            "savings_to_loan_ratio": 1,
            "debt_service_coverage": 1,
            # Negative: higher value → less likely approved
            "debt_to_income": -1,
            "num_defaults_5yr": -1,
            "worst_arrears_months": -1,
            # Additional negative: higher value → less likely approved
            "existing_credit_card_limit": -1,
            "monthly_expenses": -1,
            "num_credit_enquiries_6m": -1,
            "bureau_risk_score": -1,
            "stressed_dsr": -1,
        }
        return tuple(constraints.get(col, 0) for col in feature_cols)

    def _train_xgb(self, X_train, y_train, X_val, y_val, sample_weights=None):
        """Train XGBoost with RandomizedSearchCV, monotonic constraints, and early stopping."""
        from xgboost import XGBClassifier

        # Handle class imbalance
        neg_count = int((y_train == 0).sum())
        pos_count = int((y_train == 1).sum())
        scale_pos_weight = neg_count / pos_count if pos_count > 0 else 1.0

        # Build monotonic constraints from feature names
        monotonic = self._build_monotonic_constraints(list(X_train.columns))

        param_grid = {
            "n_estimators": [200, 300],
            "max_depth": [4, 6],
            "learning_rate": [0.05, 0.1],
            "subsample": [0.8, 1.0],
            "min_child_weight": [1, 5],
            "colsample_bytree": [0.8, 1.0],
            "reg_lambda": [1, 5],
        }
        # n_jobs=1 here so XGBoost does NOT spawn its own thread pool
        # inside each RandomizedSearchCV worker (n_jobs=-1 below).
        # Without this, N sklearn workers × N XGBoost threads causes
        # thread oversubscription and makes training slower, not faster.
        xgb = XGBClassifier(
            random_state=42,
            eval_metric="logloss",
            scale_pos_weight=scale_pos_weight,
            monotone_constraints=monotonic,
            max_bin=getattr(settings, "ML_MAX_BIN", 512),
            n_jobs=1,
        )
        search = RandomizedSearchCV(
            xgb,
            param_grid,
            n_iter=12,
            cv=StratifiedKFold(n_splits=3, shuffle=True, random_state=42),
            scoring="roc_auc",
            n_jobs=-1,
            verbose=0,
            random_state=42,
        )
        fit_params = {}
        if sample_weights is not None:
            fit_params["sample_weight"] = sample_weights
        search.fit(X_train, y_train, **fit_params)
        best_params = search.best_params_

        # Refit with early stopping using validation set.
        # n_jobs=-1 is safe here: single model, use all cores for tree building.
        final_model = XGBClassifier(
            **best_params,
            random_state=42,
            eval_metric="logloss",
            scale_pos_weight=scale_pos_weight,
            monotone_constraints=monotonic,
            early_stopping_rounds=getattr(settings, "ML_EARLY_STOPPING_ROUNDS", 30),
            max_bin=getattr(settings, "ML_MAX_BIN", 512),
            n_jobs=-1,
        )
        fit_kwargs = {
            "eval_set": [(X_val, y_val)],
            "verbose": False,
        }
        if sample_weights is not None:
            fit_kwargs["sample_weight"] = sample_weights
        final_model.fit(X_train, y_train, **fit_kwargs)

        return final_model, best_params

    def save_model(self, model, path):
        """Save model bundle (model, scaler, column names, reference distribution) to disk."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        bundle = {
            "model": model,
            "scaler": self.scaler,
            "feature_cols": self.ohe_columns,
            "categorical_cols": self.CATEGORICAL_COLS,
            "numeric_cols": self.NUMERIC_COLS,
            # Reference distribution for PSI drift detection (APRA CPG 235).
            # Stores raw numeric feature values from training data so that
            # incoming applications can be compared against what the model
            # was trained on.
            "reference_distribution": self._reference_distribution,
            # Imputation values used during training so the predictor can
            # apply identical imputation (prevents train/serve skew).
            "imputation_values": self._imputation_values,
            # Conformal prediction nonconformity scores (split conformal method).
            # Used at inference to compute prediction intervals with guaranteed
            # coverage. Stored as sorted array for fast quantile lookup.
            "conformal_scores": getattr(self, "_conformal_scores", np.array([])),
            "feature_bounds": getattr(self, "_feature_bounds", {}),
            "group_thresholds": getattr(self, "_group_thresholds", {}),
        }
        # Self-healing: validate pipeline consistency before saving
        self._validate_pipeline_consistency(bundle)
        joblib.dump(bundle, path)
        return path

    def _validate_pipeline_consistency(self, bundle):
        """Post-training validation to catch pipeline inconsistencies.

        Runs automatically before every model save. If any check fails,
        training raises a clear error rather than saving a broken model.
        """
        errors = []

        # 1. Categorical cols match between trainer and predictor
        from apps.ml_engine.services.predictor import ModelPredictor

        if set(self.CATEGORICAL_COLS) != set(ModelPredictor.CATEGORICAL_COLS):
            errors.append(
                f"CATEGORICAL_COLS mismatch: trainer={self.CATEGORICAL_COLS}, "
                f"predictor={ModelPredictor.CATEGORICAL_COLS}"
            )

        # 2. Feature cols present in bundle
        if not bundle.get("feature_cols"):
            errors.append("Model bundle missing 'feature_cols'")

        # 3. Imputation values present
        if not bundle.get("imputation_values"):
            errors.append("Model bundle missing 'imputation_values'")

        # 4. Reference distribution present
        if not bundle.get("reference_distribution"):
            errors.append("Model bundle missing 'reference_distribution'")

        if errors:
            raise ValueError("Pipeline consistency check FAILED:\n" + "\n".join(f"  - {e}" for e in errors))
        logger.info("Pipeline consistency check passed: %d validations OK", 4)
