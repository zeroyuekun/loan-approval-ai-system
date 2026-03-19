import logging
import os
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GridSearchCV, RandomizedSearchCV, train_test_split
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

from .metrics import MetricsService


class _CalibratedModel:
    """Wraps a fitted classifier with isotonic probability calibration.

    Replaces sklearn's CalibratedClassifierCV(cv='prefit') which was
    removed in scikit-learn 1.8.
    """

    def __init__(self, estimator, X_val, y_val):
        self.estimator = estimator
        val_probs = estimator.predict_proba(X_val)[:, 1]
        self._calibrator = IsotonicRegression(out_of_bounds='clip')
        self._calibrator.fit(val_probs, y_val)

    def predict(self, X):
        return self.estimator.predict(X)

    def predict_proba(self, X):
        raw_probs = self.estimator.predict_proba(X)[:, 1]
        calibrated = self._calibrator.predict(raw_probs)
        calibrated = np.clip(calibrated, 0.0, 1.0)
        return np.column_stack([1 - calibrated, calibrated])

    @property
    def feature_importances_(self):
        return self.estimator.feature_importances_


class ModelTrainer:
    """Handles model training with GridSearchCV."""

    CATEGORICAL_COLS = ['purpose', 'home_ownership', 'employment_type', 'applicant_type', 'state']
    NUMERIC_COLS = [
        'annual_income', 'credit_score', 'loan_amount', 'loan_term_months',
        'debt_to_income', 'employment_length', 'has_cosigner',
        'property_value', 'deposit_amount', 'monthly_expenses',
        'existing_credit_card_limit', 'number_of_dependants',
        'has_hecs', 'has_bankruptcy',
        'lvr', 'loan_to_income', 'credit_card_burden', 'expense_to_income',
        # Feature interactions (standard in Big 4 bank scorecards)
        'lvr_x_dti', 'income_credit_interaction',
        'serviceability_ratio', 'employment_stability',
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
        """
        df = df.copy()

        # Impute missing values and store the values used so the predictor
        # can apply identical imputation (prevents train/serve skew).
        expenses_median = float(df['monthly_expenses'].median()) if df['monthly_expenses'].notna().any() else 2500.0
        self._imputation_values = {
            'monthly_expenses': expenses_median,
            'existing_credit_card_limit': 0.0,
            'property_value': 0.0,
            'deposit_amount': 0.0,
        }
        df['monthly_expenses'] = df['monthly_expenses'].fillna(expenses_median)
        df['existing_credit_card_limit'] = df['existing_credit_card_limit'].fillna(0)
        df['property_value'] = df['property_value'].fillna(0)
        df['deposit_amount'] = df['deposit_amount'].fillna(0)

        df['lvr'] = np.where(
            df['property_value'] > 0,
            df['loan_amount'] / df['property_value'],
            0.0,
        )
        df['loan_to_income'] = df['loan_amount'] / df['annual_income']
        monthly_income = df['annual_income'] / 12.0
        df['credit_card_burden'] = np.where(
            monthly_income > 0,
            df['existing_credit_card_limit'] * 0.03 / monthly_income,
            0.0,
        )
        df['expense_to_income'] = np.where(
            df['annual_income'] > 0,
            df['monthly_expenses'] * 12 / df['annual_income'],
            0.0,
        )

        # ---------------------------------------------------------------
        # FEATURE INTERACTIONS
        #
        # Real bank scorecards capture cross-feature signals that single
        # features miss. These interactions model the combinatorial risk
        # that underwriters assess intuitively:
        #
        # - A high LVR alone is manageable; high LVR + high DTI together
        #   is much riskier than the sum of parts (compounding leverage)
        # - High income partially compensates for high DTI (more buffer)
        # - Long employment for a casual worker is very different from
        #   long employment for a permanent worker
        # - Credit score + income together predict serviceability better
        #   than either alone (creditworthiness x capacity)
        #
        # These are standard features in Big 4 bank scorecards. APRA CPG
        # 235 specifically mentions interaction effects in model risk
        # management requirements.
        # ---------------------------------------------------------------

        # Leverage interaction: LVR x DTI — compounding risk.
        # High LVR (little equity) + high DTI (stretched income) is the
        # profile most likely to default under stress (RBA FSR 2022).
        df['lvr_x_dti'] = df['lvr'] * df['debt_to_income']

        # Capacity interaction: income normalised credit score.
        # High credit + high income = strong applicant. Low credit + low
        # income = weak. This captures the joint effect better than either
        # feature alone.
        df['income_credit_interaction'] = (
            np.log1p(df['annual_income']) * df['credit_score'] / 1200
        )

        # Serviceability buffer: how much monthly income remains after
        # all commitments as a ratio. Directly models the bank's
        # serviceability assessment.
        monthly_commitments = (
            df['existing_credit_card_limit'] * 0.03
            + df['monthly_expenses']
        )
        df['serviceability_ratio'] = np.where(
            monthly_income > 0,
            np.clip(1.0 - monthly_commitments / monthly_income, -1.0, 1.0),
            0.0,
        )

        # Employment stability score: employment type quality x tenure.
        # Permanent with 10 years = very stable; casual with 1 year = risky.
        emp_type_weight = df.get('employment_type', pd.Series(dtype=str)).map({
            'payg_permanent': 1.0,
            'contract': 0.7,
            'self_employed': 0.6,
            'payg_casual': 0.4,
        }).fillna(0.5)
        df['employment_stability'] = emp_type_weight * np.log1p(df['employment_length'])

        # Ensure new columns exist with defaults if missing from older datasets
        if 'has_hecs' not in df.columns:
            df['has_hecs'] = 0
        if 'has_bankruptcy' not in df.columns:
            df['has_bankruptcy'] = 0
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
        ohe_cols = [c for c in df.columns if any(c.startswith(cat + '_') for cat in self.CATEGORICAL_COLS)]
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

        # Align columns: add missing columns as 0, drop extra columns
        for col in self.ohe_columns:
            if col not in df.columns:
                df[col] = 0.0
        df = df[self.ohe_columns + [c for c in df.columns if c not in self.ohe_columns]]

        # Scale using already-fit scaler
        df[self.ohe_columns] = self.scaler.transform(df[self.ohe_columns])

        return df, self.ohe_columns

    def train(self, data_path, algorithm='xgb'):
        """Train model with GridSearchCV and return model + metrics."""
        start_time = time.time()

        # Load data
        df = pd.read_csv(data_path)

        if len(df) < 20:
            raise ValueError(f'Dataset too small for training: {len(df)} rows (minimum 20 required)')

        y = df['approved']
        class_counts = y.value_counts()
        if class_counts.min() < 5:
            raise ValueError(
                f'Insufficient class balance: {dict(class_counts)}. '
                f'Each class needs at least 5 samples.'
            )

        # 80/10/10 split BEFORE preprocessing to avoid data leakage
        df_train, df_temp, y_train, y_temp = train_test_split(
            df, y, test_size=0.2, random_state=42, stratify=y
        )
        df_val, df_test, y_val, y_test = train_test_split(
            df_temp, y_temp, test_size=0.5, random_state=42, stratify=y_temp
        )

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
                        'percentiles': percentiles,
                        'mean': float(np.mean(vals)),
                        'std': float(np.std(vals)),
                        'n': len(vals),
                        'histogram_counts': hist_counts.tolist(),
                        'histogram_edges': bin_edges.tolist(),
                    }
        self._reference_distribution = ref_dist

        # Save original test indices before transform() resets them
        test_original_indices = df_test.index.copy()

        # Save raw copies BEFORE preprocessing for WOE scorecard (C4 fix).
        # WOE bins must be in interpretable units (credit_score 650-750),
        # not z-score units from StandardScaler.
        df_train_raw = self.add_derived_features(df_train.copy())
        df_test_raw = self.add_derived_features(df_test.copy())

        # Fit preprocessing on training data only
        df_train, feature_cols = self.fit_preprocess(df_train)
        X_train = df_train[feature_cols]

        # Transform val and test using already-fit encoders/scaler
        df_val, _ = self.transform(df_val)
        X_val = df_val[feature_cols]

        df_test, _ = self.transform(df_test)
        X_test = df_test[feature_cols]

        if algorithm == 'xgb':
            raw_model, best_params = self._train_xgb(X_train, y_train, X_val, y_val)
        else:
            raw_model, best_params = self._train_rf(X_train, y_train, X_val, y_val)

        # Probability calibration on validation set only (avoids data leakage
        # since GridSearchCV already used cross-validation on the training set)
        model = _CalibratedModel(raw_model, X_val, y_val)

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
        metrics['confusion_matrix'] = self.metrics_service.confusion_matrix_data(y_test, y_pred)
        metrics['roc_curve'] = self.metrics_service.roc_curve_data(y_test, y_prob)
        metrics['feature_importances'] = self.metrics_service.feature_importance_data(
            model, feature_cols
        )
        metrics['training_params'] = best_params

        # New banking metrics
        metrics['gini_coefficient'] = self.metrics_service.compute_gini(y_test, y_prob)
        ks_result = self.metrics_service.compute_ks_statistic(y_test, y_prob)
        metrics['ks_statistic'] = ks_result['ks_statistic']
        metrics['log_loss'] = self.metrics_service.compute_log_loss(y_test, y_prob)
        metrics['calibration_data'] = self.metrics_service.compute_calibration_data(y_test, y_prob)
        metrics['threshold_analysis'] = self.metrics_service.compute_threshold_analysis(y_test, y_prob)
        metrics['decile_analysis'] = self.metrics_service.compute_decile_analysis(y_test, y_prob)

        # Overfitting detection — derive predictions from probabilities
        # to avoid a redundant full inference pass on the training set
        y_train_pred_prob = model.predict_proba(X_train)[:, 1]
        train_auc = round(float(roc_auc_score(y_train, y_train_pred_prob)), 4)
        test_auc = metrics['auc_roc']
        overfitting_gap = round(train_auc - test_auc, 4)
        if overfitting_gap > 0.05:
            logger.warning(
                "Overfitting detected: train AUC %.4f vs test AUC %.4f (gap: %.4f)",
                train_auc, test_auc, overfitting_gap,
            )

        training_time = round(time.time() - start_time, 2)
        metrics['training_time_seconds'] = training_time
        metrics['training_metadata'] = {
            'train_size': len(y_train),
            'val_size': len(y_val),
            'test_size': len(y_test),
            'class_balance': round(float(y.mean()), 4),
            'training_time_seconds': training_time,
            'overfitting_gap': overfitting_gap,
            'train_auc': round(train_auc, 4),
            'n_features': len(feature_cols),
        }

        # Fairness metrics with full TPR/FPR/disparate impact
        fairness_metrics = {}
        for col in ['employment_type', 'applicant_type', 'state']:
            if col in df.columns:
                test_indices = test_original_indices
                original_vals = df.loc[test_indices, col] if col in df.columns else pd.Series()
                if len(original_vals) > 0:
                    fairness_result = self.metrics_service.compute_fairness_metrics(
                        y_test.values, y_pred, y_prob, original_vals.values
                    )
                    fairness_metrics[col] = fairness_result
        metrics['fairness'] = fairness_metrics

        # WOE/IV analysis on RAW (unscaled) data so bin edges are in
        # interpretable units (credit_score 650-750, not z-scores).
        try:
            woe_iv = self.metrics_service.compute_all_woe_iv(
                df_test_raw[self.NUMERIC_COLS], y_test, self.NUMERIC_COLS, n_bins=10
            )
            metrics['woe_iv'] = {
                col: {'iv': v['iv'], 'interpretation': v['iv_interpretation']}
                for col, v in woe_iv.items()
                if v['iv'] >= 0.02
            }
        except Exception:
            logger.warning("WOE/IV computation failed", exc_info=True)
            metrics['woe_iv'] = {}

        # WOE logistic regression scorecard on RAW data with out-of-sample AUC.
        try:
            _, _, scorecard = self.metrics_service.build_woe_scorecard(
                df_train_raw[self.NUMERIC_COLS], y_train, self.NUMERIC_COLS, n_bins=10,
                X_test=df_test_raw[self.NUMERIC_COLS], y_test=y_test,
            )
            if scorecard:
                metrics['woe_scorecard'] = scorecard
        except Exception:
            logger.warning("WOE scorecard build failed", exc_info=True)

        # Adversarial validation: can a classifier distinguish train from test?
        try:
            adv = self.metrics_service.adversarial_validation(
                X_train.values, X_test.values
            )
            metrics['adversarial_validation'] = adv
        except Exception:
            logger.warning("Adversarial validation failed", exc_info=True)

        # Concentration risk (APRA APS 221)
        try:
            metrics['concentration_risk'] = {}
            for col in ['purpose', 'employment_type', 'state']:
                if col in df.columns:
                    metrics['concentration_risk'][col] = (
                        self.metrics_service.compute_concentration_risk(df, col)
                    )
        except Exception:
            logger.warning("Concentration risk computation failed", exc_info=True)

        return model, metrics

    def _train_rf(self, X_train, y_train, X_val, y_val):
        """Train Random Forest with GridSearchCV."""
        param_grid = {
            'n_estimators': [100, 200],
            'max_depth': [10, 20, None],
            'min_samples_split': [2, 5],
        }
        rf = RandomForestClassifier(random_state=42, class_weight='balanced')
        grid = GridSearchCV(rf, param_grid, cv=5, scoring='f1', n_jobs=-1, verbose=0)
        grid.fit(X_train, y_train)
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
        constraints = {
            'annual_income': 1,         # more income → more likely approved
            'credit_score': 1,          # better credit → more likely approved
            'debt_to_income': -1,       # higher DTI → less likely approved
            'employment_length': 1,     # longer tenure → more likely approved
            'has_cosigner': 1,          # cosigner helps
            'has_bankruptcy': -1,       # bankruptcy hurts
            # has_hecs: unconstrained (0) — effect is income-mediated, not unconditional.
            # High-income HECS holders are barely affected; forcing monotonicity
            # would unfairly penalise them.
            'loan_to_income': -1,       # higher loan relative to income → riskier
            'expense_to_income': -1,    # higher expenses relative to income → riskier
            # lvr: unconstrained (0) — non-home loans have LVR=0.0, which is
            # semantically "no property", not "best possible LVR". A -1
            # constraint would force the model to approve LVR=0 (personal loans)
            # more than any home loan with a deposit.
            'credit_card_burden': -1,   # higher CC burden → riskier
            # Interaction features
            'lvr_x_dti': -1,            # compounding leverage → riskier
            'income_credit_interaction': 1,  # higher income x credit → safer
            'serviceability_ratio': 1,   # more buffer after commitments → safer
            'employment_stability': 1,   # more stable employment → safer
        }
        return tuple(constraints.get(col, 0) for col in feature_cols)

    def _train_xgb(self, X_train, y_train, X_val, y_val):
        """Train XGBoost with RandomizedSearchCV, monotonic constraints, and early stopping."""
        from xgboost import XGBClassifier

        # Handle class imbalance
        neg_count = int((y_train == 0).sum())
        pos_count = int((y_train == 1).sum())
        scale_pos_weight = neg_count / pos_count if pos_count > 0 else 1.0

        # Build monotonic constraints from feature names
        monotonic = self._build_monotonic_constraints(list(X_train.columns))

        param_grid = {
            'n_estimators': [100, 200, 300],
            'max_depth': [3, 6, 9],
            'learning_rate': [0.01, 0.1],
            'subsample': [0.8, 1.0],
            'min_child_weight': [1, 5],
            'colsample_bytree': [0.8, 1.0],
            'reg_alpha': [0, 0.1],
            'reg_lambda': [1, 5],
        }
        # n_jobs=1 here so XGBoost does NOT spawn its own thread pool
        # inside each RandomizedSearchCV worker (n_jobs=-1 below).
        # Without this, N sklearn workers × N XGBoost threads causes
        # thread oversubscription and makes training slower, not faster.
        xgb = XGBClassifier(
            random_state=42,
            eval_metric='logloss',
            scale_pos_weight=scale_pos_weight,
            monotone_constraints=monotonic,
            n_jobs=1,
        )
        search = RandomizedSearchCV(
            xgb, param_grid, n_iter=50, cv=3, scoring='f1',
            n_jobs=-1, verbose=0, random_state=42,
        )
        search.fit(X_train, y_train)
        best_params = search.best_params_

        # Refit with early stopping using validation set.
        # n_jobs=-1 is safe here: single model, use all cores for tree building.
        final_model = XGBClassifier(
            **best_params,
            random_state=42,
            eval_metric='logloss',
            scale_pos_weight=scale_pos_weight,
            monotone_constraints=monotonic,
            early_stopping_rounds=20,
            n_jobs=-1,
        )
        final_model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )

        return final_model, best_params

    def save_model(self, model, path):
        """Save model bundle (model, scaler, column names, reference distribution) to disk."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        bundle = {
            'model': model,
            'scaler': self.scaler,
            'feature_cols': self.ohe_columns,
            'categorical_cols': self.CATEGORICAL_COLS,
            'numeric_cols': self.NUMERIC_COLS,
            # Reference distribution for PSI drift detection (APRA CPG 235).
            # Stores raw numeric feature values from training data so that
            # incoming applications can be compared against what the model
            # was trained on.
            'reference_distribution': self._reference_distribution,
            # Imputation values used during training so the predictor can
            # apply identical imputation (prevents train/serve skew).
            'imputation_values': self._imputation_values,
            # Conformal prediction nonconformity scores (split conformal method).
            # Used at inference to compute prediction intervals with guaranteed
            # coverage. Stored as sorted array for fast quantile lookup.
            'conformal_scores': getattr(self, '_conformal_scores', np.array([])),
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
        if not bundle.get('feature_cols'):
            errors.append("Model bundle missing 'feature_cols'")

        # 3. Imputation values present
        if not bundle.get('imputation_values'):
            errors.append("Model bundle missing 'imputation_values'")

        # 4. Reference distribution present
        if not bundle.get('reference_distribution'):
            errors.append("Model bundle missing 'reference_distribution'")

        if errors:
            raise ValueError(
                "Pipeline consistency check FAILED:\n" + "\n".join(f"  - {e}" for e in errors)
            )
        logger.info("Pipeline consistency check passed: %d validations OK", 4)
