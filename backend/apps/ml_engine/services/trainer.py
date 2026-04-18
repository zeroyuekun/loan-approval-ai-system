"""XGBoost + Random-Forest model trainer with calibration and segmented training.

Entry point `ModelTrainer.train(segment=...)` builds the preprocessing pipeline,
runs Optuna-tuned XGBoost training with monotone constraints, calibrates via isotonic
regression, computes holdout metrics (AUC/KS/Brier/PSI/ECE), and persists a
`ModelVersion` row keyed by segment. Aligns with APRA CPS 220 MRM evidence logging.
"""

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
from sklearn.model_selection import GridSearchCV, StratifiedKFold, cross_val_score, train_test_split
from sklearn.preprocessing import StandardScaler

from .metrics import (
    MetricsService,
    brier_decomposition,
    ks_statistic,
    psi_by_feature,
)
from .monotone_constraints import (
    assert_rationale_coverage,
    build_xgboost_monotone_spec,
)

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
        return self.estimator

    @property
    def feature_importances_(self):
        return self.estimator.feature_importances_


class ModelTrainer:
    """Handles model training with Optuna (XGBoost) and GridSearchCV (RF)."""

    CATEGORICAL_COLS = [
        "purpose",
        "home_ownership",
        "employment_type",
        "applicant_type",
        "state",
        "savings_trend_3m",
        "industry_risk_tier",
        # sa3_region excluded: ~50 categories causes OHE explosion; geographic
        # signal is carried by postcode_default_rate and derived LVR features
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
        # Underwriter-internal policy variables (exposed as features so the
        # model can learn HEM floor + LMI capitalisation policy directly)
        "hem_benchmark",
        "hem_gap",
        "lmi_premium",
        "effective_loan_amount",
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
        # Research-backed interactions (LendingClub/Big 4 practice)
        "lvr_x_property_growth",
        "deposit_x_income_stability",
        "dti_x_rate_sensitivity",
        "credit_x_employment",
    ]

    def __init__(self):
        self.scaler = StandardScaler()
        self.ohe_columns = None  # column names after one-hot encoding
        self.metrics_service = MetricsService()
        self._reference_distribution = None  # saved for PSI drift detection
        self._imputation_values = {}  # stored in model bundle for predictor alignment

    def add_derived_features(self, df):
        """Impute missing values and compute derived features via shared module."""
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
        """Fit encoders/scaler on training data. Returns (transformed df, feature cols)."""
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
        """Transform new data using already-fit scaler. Must call fit_preprocess first."""
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
        if "application_quarter" in df.columns:
            result = self._temporal_split(df, y)
            if result is not None:
                return result
            logger.warning("Temporal split failed; falling back to random split")
        return self._random_split(df, y)

    def _random_split(self, df, y):
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
        """Time-based split. Returns None if not viable (< 3 quarters or single-class splits)."""
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

    # ------------------------------------------------------------------
    # Diagnostic helpers — baseline comparison and temporal CV
    # ------------------------------------------------------------------

    _BASELINE_CANDIDATE_FEATURES = (
        "credit_score",
        "annual_income",
        "loan_amount",
        "debt_to_income",
    )

    def _train_credit_score_baseline(self, X_train, y_train, X_test, y_test):
        """Fit a logistic-regression baseline on a handful of core credit features.

        The purpose is to report an honest lift number for the main model:
        "XGBoost AUC minus credit-score-only-baseline AUC". This answers the
        standard credit-risk interview question "how much better is your model
        than a naive scorecard?" without requiring a full champion/challenger
        comparison.

        Returns a dict with keys: baseline_auc (float or None),
        baseline_features (list[str]), error (str or None).

        Fails soft — any exception returns baseline_auc=None and logs a
        warning, so training continues without the diagnostic.
        """
        from sklearn.linear_model import LogisticRegression

        available = [c for c in self._BASELINE_CANDIDATE_FEATURES if c in X_train.columns]
        if len(available) < 2:
            logger.info(
                "Baseline LR skipped — only %d candidate features present (need >=2): %s",
                len(available),
                available,
            )
            return {
                "baseline_auc": None,
                "baseline_features": available,
                "error": f"insufficient_features ({len(available)})",
            }

        try:
            baseline = LogisticRegression(max_iter=1000, random_state=42, solver="liblinear")
            baseline.fit(X_train[available], y_train)
            probs = baseline.predict_proba(X_test[available])[:, 1]
            auc = float(roc_auc_score(y_test, probs))
            return {
                "baseline_auc": round(auc, 4),
                "baseline_features": list(available),
                "error": None,
            }
        except Exception as exc:
            logger.warning("Baseline LR training failed: %s", exc)
            return {
                "baseline_auc": None,
                "baseline_features": list(available),
                "error": str(exc),
            }

    def _compute_temporal_cv_auc(self, X_train, y_train, train_quarters, max_folds=3):
        """Walk-forward temporal cross-validation on the training set.

        For each of the last ``max_folds`` quarters in ``train_quarters``,
        fit a lightweight XGBoost on everything from earlier quarters and
        score it on that held-out quarter. Return the mean fold AUC and the
        number of folds actually used.

        Unlike the standard stratified CV, this splits by time — if the
        model secretly relies on features that drift across quarters, this
        number will be lower than the random-CV number, and the gap is a
        usable drift signal.

        Returns (mean_auc, n_folds_used) or (None, 0) if there are fewer
        than 3 quarters, insufficient data per fold, or the same class in
        every validation slice.
        """
        from xgboost import XGBClassifier as _TemporalCVClassifier

        if train_quarters is None or len(train_quarters) != len(y_train):
            return None, 0

        unique_quarters = sorted(set(train_quarters))
        if len(unique_quarters) < 3:
            return None, 0

        # Walk-forward: last N quarters become successive validation folds.
        # Leave at least one quarter for the initial training prefix.
        n_folds = min(max_folds, len(unique_quarters) - 1)
        fold_quarters = unique_quarters[-n_folds:]

        neg = int((y_train == 0).sum())
        pos = int((y_train == 1).sum())
        scale_pos = neg / pos if pos > 0 else 1.0
        n_jobs = getattr(settings, "ML_XGB_N_JOBS", 2)

        fold_aucs = []
        quarters_arr = np.asarray(train_quarters)
        y_train_arr = np.asarray(y_train)

        for fold_q in fold_quarters:
            train_mask = quarters_arr < fold_q
            val_mask = quarters_arr == fold_q

            if train_mask.sum() < 50 or val_mask.sum() < 20:
                continue
            if len(np.unique(y_train_arr[val_mask])) < 2:
                continue

            X_train_fold = X_train.iloc[train_mask] if hasattr(X_train, "iloc") else X_train[train_mask]
            X_val_fold = X_train.iloc[val_mask] if hasattr(X_train, "iloc") else X_train[val_mask]
            y_train_fold = y_train_arr[train_mask]
            y_val_fold = y_train_arr[val_mask]

            model = _TemporalCVClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.1,
                random_state=42,
                eval_metric="logloss",
                n_jobs=n_jobs,
                scale_pos_weight=scale_pos,
                # Mirror the final-model constraints so temporal-CV AUC is
                # comparable to the production point estimate.
                monotone_constraints=build_xgboost_monotone_spec(list(X_train_fold.columns)),
            )
            model.fit(X_train_fold, y_train_fold)
            probs = model.predict_proba(X_val_fold)[:, 1]
            fold_aucs.append(float(roc_auc_score(y_val_fold, probs)))

        if not fold_aucs:
            return None, 0
        return round(float(np.mean(fold_aucs)), 4), len(fold_aucs)

    def train(
        self,
        data_path,
        algorithm="xgb",
        use_reject_inference=True,
        reject_inference_labels=None,
        *,
        segment=None,
    ):
        """Train model with Optuna (XGBoost) or GridSearchCV (RF) and return model + metrics.

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
        segment : str or None
            When provided (home_owner_occupier / home_investor / personal),
            narrows the training DataFrame to rows matching that product
            segment. Falls back to unified training when the segment slice
            is below SEGMENT_MIN_SAMPLES to avoid noisy per-segment models.
        """
        from apps.ml_engine.services.segmentation import (
            SEGMENT_FILTERS,
            SEGMENT_MIN_SAMPLES,
            SEGMENT_UNIFIED,
        )

        start_time = time.time()

        # Load data
        df = pd.read_csv(data_path)

        if len(df) < 20:
            raise ValueError(f"Dataset too small for training: {len(df)} rows (minimum 20 required)")

        # Segment slicing: narrow the training frame before any splitting so
        # the holdout and CV reflect the segment only.
        if segment and segment != SEGMENT_UNIFIED:
            seg_filter = SEGMENT_FILTERS.get(segment)
            if seg_filter is None:
                raise ValueError(f"Unknown segment '{segment}'")
            mask = df.apply(lambda row: seg_filter(row.to_dict()), axis=1)
            df_seg = df[mask].copy()
            if len(df_seg) < SEGMENT_MIN_SAMPLES:
                logger.warning(
                    "Segment '%s' has %d rows (< %d threshold) — falling back to unified training",
                    segment,
                    len(df_seg),
                    SEGMENT_MIN_SAMPLES,
                )
                segment = SEGMENT_UNIFIED
            else:
                logger.info(
                    "Training segment-specific model '%s' on %d rows (of %d total)",
                    segment,
                    len(df_seg),
                    len(df),
                )
                df = df_seg

        y = df["approved"]
        class_counts = y.value_counts()
        if class_counts.min() < 5:
            raise ValueError(f"Insufficient class balance: {dict(class_counts)}. Each class needs at least 5 samples.")

        # Split BEFORE preprocessing to avoid data leakage.
        # Uses temporal split (by application_quarter) if available,
        # otherwise falls back to random stratified 80/10/10.
        df_train, df_val, df_test, y_train, y_val, y_test, split_meta = self._split_data(df, y)

        # Snapshot training-set quarter values BEFORE the column is dropped.
        # Used later for the diagnostic temporal CV pass that produces
        # training_metadata["temporal_cv_auc_mean"] alongside the standard
        # random-stratified CV number.
        if "application_quarter" in df_train.columns:
            train_quarters_snapshot = df_train["application_quarter"].to_numpy()
        else:
            train_quarters_snapshot = None

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

        # Snapshot employment_type BEFORE OHE for fairness reweighting
        _emp_type_raw = df_train["employment_type"].copy() if "employment_type" in df_train.columns else None

        # Fit preprocessing on training data only
        df_train, feature_cols = self.fit_preprocess(df_train)
        _train_imputation = dict(self._imputation_values)  # snapshot train-only values
        X_train = df_train[feature_cols]

        # Transform val and test using already-fit encoders/scaler
        df_val, _ = self.transform(df_val)
        X_val = df_val[feature_cols]

        df_test, _ = self.transform(df_test)
        X_test = df_test[feature_cols]

        # Restore train-based imputation values (transform may have overwritten)
        self._imputation_values = _train_imputation

        # Fairness reweighting: compute sample weights to reduce employment
        # type disparate impact (DI). Without this, DI ~0.38 (failing EEOC 80%
        # rule). Reweighting assigns higher weights to underrepresented
        # employment groups so the model doesn't systematically deny them.
        # See: MATLAB bias mitigation methodology (mathworks.com/help/risk/
        # bias-mitigation-for-credit-scoring-model-by-reweighting.html)
        sample_weights = None
        if _emp_type_raw is not None:
            emp_groups = _emp_type_raw
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
                # Use already-preprocessed rows from X_train (df_train is post-OHE+scaled).
                # Do NOT re-transform — that would double-scale the features.
                X_denied = X_train.loc[X_train.index.intersection(ri_available)]

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
            # Mirror the final-model constraints so stability-CV AUC is
            # comparable to the production point estimate.
            monotone_constraints=build_xgboost_monotone_spec(list(X_train.columns)),
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

        # Diagnostic: time-based CV alongside the random-stratified CV.
        # Random CV tells us how well the model generalises across random folds;
        # temporal CV tells us how well it generalises across time — a harder,
        # more production-realistic question. The gap between the two is a
        # drift signal that interviewers want to see.
        temporal_cv_auc_mean = None
        temporal_cv_folds_used = 0
        cv_drift_signal = None
        # Align the quarter snapshot to the current X_train rows. Reject-inference
        # augmentation (below) happens AFTER this block for the XGB path, so we
        # run the temporal CV on pre-augmented indices; but X_train may still
        # have been trimmed by preprocessing earlier, so guard on length.
        if train_quarters_snapshot is not None and len(train_quarters_snapshot) == len(y_train):
            try:
                temporal_cv_auc_mean, temporal_cv_folds_used = self._compute_temporal_cv_auc(
                    X_train, y_train, train_quarters_snapshot
                )
                if temporal_cv_auc_mean is not None:
                    cv_drift_signal = round(cv_mean - temporal_cv_auc_mean, 4)
                    logger.info(
                        "Temporal CV AUC: %.4f over %d quarter folds (drift signal vs random CV: %+.4f)",
                        temporal_cv_auc_mean,
                        temporal_cv_folds_used,
                        cv_drift_signal,
                    )
                else:
                    logger.info("Temporal CV skipped — insufficient quarters in training set")
            except Exception as exc:
                logger.warning("Temporal CV failed: %s", exc)
        else:
            logger.info(
                "Temporal CV skipped — quarter snapshot unavailable or length mismatch (snapshot=%s, y_train=%d)",
                "None" if train_quarters_snapshot is None else len(train_quarters_snapshot),
                len(y_train),
            )

        if algorithm == "xgb":
            raw_model, best_params = self._train_xgb(X_train, y_train, X_val, y_val, sample_weights=sample_weights)
        else:
            raw_model, best_params = self._train_rf(X_train, y_train, X_val, y_val, sample_weights=sample_weights)

        # Probability calibration on validation set only (avoids data leakage
        # since Optuna/GridSearchCV already used cross-validation on the training set).
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

        # Evaluate on test set only (val was used for calibration and early stopping)
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

        # D5 — production-grade metrics for champion-challenger promotion.
        # `ks` is the bare float, distinct from `ks_statistic` (rounded) so
        # gate comparisons carry full precision. Brier decomposition lets the
        # MRM dossier and promotion gate separate calibration error
        # (reliability) from discriminative power (resolution).
        metrics["ks"] = round(ks_statistic(y_test, y_prob), 6)
        metrics["brier_decomp"] = brier_decomposition(y_test, y_prob)
        # Per-feature PSI of test distribution vs train distribution — feeds
        # the promotion gate's max-PSI check and the MRM dossier.
        try:
            metrics["psi_by_feature"] = psi_by_feature(
                X_train if isinstance(X_train, pd.DataFrame) else pd.DataFrame(X_train, columns=feature_cols),
                X_test if isinstance(X_test, pd.DataFrame) else pd.DataFrame(X_test, columns=feature_cols),
                feature_cols,
            )
        except Exception as _psi_exc:
            logger.warning("psi_by_feature computation failed: %s", _psi_exc)
            metrics["psi_by_feature"] = {}

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

        # Logistic-regression baseline on core credit features. Lets us report
        # the XGBoost lift over a simple scorecard — the credit-risk interview
        # question "how much better is your model than credit_score alone?"
        baseline_result = self._train_credit_score_baseline(X_train, y_train, X_test, y_test)
        xgb_lift_over_baseline = None
        if baseline_result["baseline_auc"] is not None:
            xgb_lift_over_baseline = round(metrics["auc_roc"] - baseline_result["baseline_auc"], 4)
            logger.info(
                "Baseline LR AUC: %.4f on %s; XGBoost lift: %+.4f",
                baseline_result["baseline_auc"],
                baseline_result["baseline_features"],
                xgb_lift_over_baseline,
            )

        training_time = round(time.time() - start_time, 2)
        metrics["training_time_seconds"] = training_time
        metrics["optimal_threshold"] = optimal_threshold
        metrics["training_metadata"] = {
            "segment": segment or "unified",
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
            "temporal_cv_auc_mean": temporal_cv_auc_mean,
            "temporal_cv_folds_used": temporal_cv_folds_used,
            "cv_drift_signal": cv_drift_signal,
            "baseline_auc": baseline_result["baseline_auc"],
            "baseline_features": baseline_result["baseline_features"],
            "xgb_lift_over_baseline": xgb_lift_over_baseline,
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
            # sklearn 1.6+ requires fit params via set_params or direct kwargs
            fit_params["sample_weight"] = sample_weights
        grid.fit(X_train, y_train, **fit_params)
        return grid.best_estimator_, grid.best_params_

    def _build_monotonic_constraints(self, feature_cols):
        """Delegate to the module-level schedule in monotone_constraints.py.

        The schedule was extracted out of trainer.py so it can be referenced
        from the MRM dossier generator and audited in isolation. Calling
        assert_rationale_coverage() here causes a sign-flip or undocumented
        new constraint to fail training rather than ship silently.
        """
        assert_rationale_coverage()
        return build_xgboost_monotone_spec(feature_cols)

    def _train_xgb(self, X_train, y_train, X_val, y_val, sample_weights=None):
        """Train XGBoost with Optuna hyperparameter search and early stopping."""
        import optuna
        from xgboost import XGBClassifier

        # Suppress Optuna's per-trial logging (we log the summary)
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        # Handle class imbalance
        neg_count = int((y_train == 0).sum())
        pos_count = int((y_train == 1).sum())
        scale_pos_weight = neg_count / pos_count if pos_count > 0 else 1.0

        # Build monotonic constraints from feature names
        monotonic = self._build_monotonic_constraints(list(X_train.columns))
        max_bin = getattr(settings, "ML_MAX_BIN", 512)
        n_optuna_trials = getattr(settings, "ML_OPTUNA_TRIALS", 50)

        # 3-fold stratified CV for objective evaluation
        cv = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)

        def objective(trial):
            params = {
                "n_estimators": trial.suggest_int("n_estimators", 200, 600, step=100),
                "max_depth": trial.suggest_int("max_depth", 4, 10),
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
                "subsample": trial.suggest_float("subsample", 0.6, 1.0),
                "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
                "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
                "reg_lambda": trial.suggest_float("reg_lambda", 1.0, 50.0, log=True),
                "reg_alpha": trial.suggest_float("reg_alpha", 0.01, 10.0, log=True),
                "gamma": trial.suggest_float("gamma", 0.0, 5.0),
            }

            model = XGBClassifier(
                **params,
                random_state=42,
                eval_metric="logloss",
                scale_pos_weight=scale_pos_weight,
                monotone_constraints=monotonic,
                max_bin=max_bin,
                # Matches the celery_worker_ml container's cpus: '2.0' quota.
                # Setting n_jobs=1 left half the allocated CPU idle during
                # training; Optuna itself is sequential so there is no
                # oversubscription risk.
                n_jobs=getattr(settings, "ML_XGB_N_JOBS", 2),
            )

            cv_fit_params = {}
            if sample_weights is not None:
                cv_fit_params["sample_weight"] = sample_weights

            scores = cross_val_score(model, X_train, y_train, cv=cv, scoring="roc_auc", params=cv_fit_params)
            return scores.mean()

        study = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=42),
            # MedianPruner removed: cross_val_score is a batch call with no
            # intermediate trial.report() steps, so the pruner has no effect.
        )
        # Reserve 600s for final refit, calibration, saving, and DB writes
        study.optimize(objective, n_trials=n_optuna_trials, timeout=1200, show_progress_bar=False)

        if not study.best_trial:
            raise RuntimeError("Optuna completed no trials within time budget")

        best_params = study.best_params
        logger.info(
            "Optuna optimization: best AUC=%.4f after %d trials. Params: %s",
            study.best_value,
            len(study.trials),
            best_params,
        )

        # Refit with early stopping using validation set.
        # n_jobs=-1 is safe here: single model, use all cores for tree building.
        final_model = XGBClassifier(
            **best_params,
            random_state=42,
            eval_metric="logloss",
            scale_pos_weight=scale_pos_weight,
            monotone_constraints=monotonic,
            early_stopping_rounds=getattr(settings, "ML_EARLY_STOPPING_ROUNDS", 30),
            max_bin=max_bin,
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
        """Sanity-check the bundle before saving. Raises ValueError on mismatch."""
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
