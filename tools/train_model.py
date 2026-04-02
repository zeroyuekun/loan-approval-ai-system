#!/usr/bin/env python3
"""Train Random Forest and/or XGBoost models on loan application data.

Loads a CSV dataset, preprocesses features, performs hyperparameter tuning
with Optuna (XGBoost) or GridSearchCV (RF), and saves the best model(s) with joblib.

Usage:
    python tools/train_model.py
    python tools/train_model.py --data-path .tmp/synthetic_loans.csv --algorithm both
    python tools/train_model.py --algorithm rf --output-dir backend/ml_models
"""

import argparse
import json
import os
import sys
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    roc_auc_score,
)
from sklearn.model_selection import GridSearchCV, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, OneHotEncoder, StandardScaler


# Feature definitions (must match DataGenerator output columns)
NUMERIC_FEATURES = [
    "annual_income",
    "credit_score",
    "loan_amount",
    "loan_term_months",
    "debt_to_income",
    "employment_length",
    "property_value",
    "deposit_amount",
    "monthly_expenses",
    "existing_credit_card_limit",
    "number_of_dependants",
]
CATEGORICAL_FEATURES = ["purpose", "home_ownership", "employment_type", "applicant_type"]
BINARY_FEATURES = ["has_cosigner"]
TARGET = "approved"


def load_and_validate(data_path: str) -> pd.DataFrame:
    """Load CSV and perform basic validation.

    Args:
        data_path: Path to the CSV file.

    Returns:
        Validated DataFrame.

    Raises:
        FileNotFoundError: If data file does not exist.
        ValueError: If required columns are missing.
    """
    if not os.path.exists(data_path):
        raise FileNotFoundError(f"Data file not found: {data_path}")

    df = pd.read_csv(data_path)
    print(f"Loaded {len(df)} records from {data_path}")

    if len(df) < 500:
        print("WARNING: Dataset has fewer than 500 rows. Results may be unreliable.")

    required_cols = NUMERIC_FEATURES + CATEGORICAL_FEATURES + BINARY_FEATURES + [TARGET]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Handle missing values
    total_missing = df[required_cols].isnull().sum()
    cols_high_missing = total_missing[total_missing > len(df) * 0.3]
    if len(cols_high_missing) > 0:
        print(
            f"WARNING: Columns with >30% missing values: {list(cols_high_missing.index)}. "
            "Consider dropping these features."
        )

    # Drop rows with >50% missing across features
    feature_cols = NUMERIC_FEATURES + CATEGORICAL_FEATURES + BINARY_FEATURES
    row_missing_pct = df[feature_cols].isnull().mean(axis=1)
    rows_to_drop = (row_missing_pct > 0.5).sum()
    if rows_to_drop > 0:
        df = df[row_missing_pct <= 0.5].copy()
        print(f"Dropped {rows_to_drop} rows with >50% missing values.")

    # Impute remaining missing values
    for col in NUMERIC_FEATURES + BINARY_FEATURES:
        if df[col].isnull().any():
            median_val = df[col].median()
            df[col] = df[col].fillna(median_val)
            print(f"  Imputed {col} missing values with median ({median_val})")

    for col in CATEGORICAL_FEATURES:
        if df[col].isnull().any():
            mode_val = df[col].mode()[0]
            df[col] = df[col].fillna(mode_val)
            print(f"  Imputed {col} missing values with mode ({mode_val})")

    return df


def build_preprocessor() -> ColumnTransformer:
    """Build a sklearn ColumnTransformer for feature preprocessing.

    Returns:
        Configured ColumnTransformer.
    """
    return ColumnTransformer(
        transformers=[
            ("num", StandardScaler(), NUMERIC_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
            ("bin", "passthrough", BINARY_FEATURES),
        ]
    )


def split_data(df: pd.DataFrame):
    """Split data into 80/10/10 train/val/test sets.

    Args:
        df: Input DataFrame.

    Returns:
        Tuple of (X_train, X_val, X_test, y_train, y_val, y_test).
    """
    feature_cols = NUMERIC_FEATURES + CATEGORICAL_FEATURES + BINARY_FEATURES
    X = df[feature_cols]
    y = df[TARGET]

    # Check class balance
    approval_rate = y.mean()
    print(f"Class distribution: {approval_rate:.1%} approved, {1 - approval_rate:.1%} denied")

    # 80/20 split first, then split the 20% into 10/10
    X_train, X_temp, y_train, y_temp = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    X_val, X_test, y_val, y_test = train_test_split(
        X_temp, y_temp, test_size=0.5, random_state=42, stratify=y_temp
    )

    print(f"Split: train={len(X_train)}, val={len(X_val)}, test={len(X_test)}")
    return X_train, X_val, X_test, y_train, y_val, y_test


def train_random_forest(X_train, y_train, preprocessor) -> Pipeline:
    """Train a Random Forest model with GridSearchCV.

    Args:
        X_train: Training features.
        y_train: Training labels.
        preprocessor: Fitted ColumnTransformer.

    Returns:
        Best pipeline from grid search.
    """
    print("\n--- Training Random Forest ---")

    pipeline = Pipeline([
        ("preprocessor", preprocessor),
        ("classifier", RandomForestClassifier(random_state=42, class_weight="balanced")),
    ])

    param_grid = {
        "classifier__n_estimators": [100, 200, 300],
        "classifier__max_depth": [10, 20, None],
        "classifier__min_samples_split": [2, 5],
    }

    grid_search = GridSearchCV(
        pipeline,
        param_grid,
        cv=5,
        scoring="f1_weighted",
        n_jobs=-1,
        verbose=1,
    )

    grid_search.fit(X_train, y_train)

    print(f"Best params: {grid_search.best_params_}")
    print(f"Best CV F1 (weighted): {grid_search.best_score_:.4f}")

    return grid_search.best_estimator_


def train_xgboost(X_train, y_train, preprocessor) -> Pipeline:
    """Train an XGBoost model with Optuna Bayesian optimization.

    Args:
        X_train: Training features.
        y_train: Training labels.
        preprocessor: Fitted ColumnTransformer.

    Returns:
        Best pipeline from Optuna optimization.
    """
    try:
        from xgboost import XGBClassifier
    except ImportError:
        print("ERROR: xgboost is not installed. Install with: pip install xgboost")
        sys.exit(1)

    try:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        print("ERROR: optuna is not installed. Install with: pip install optuna")
        sys.exit(1)

    print("\n--- Training XGBoost (Optuna Bayesian optimization) ---")

    # Calculate scale_pos_weight for class imbalance
    neg_count = (y_train == 0).sum()
    pos_count = (y_train == 1).sum()
    scale_pos_weight = neg_count / pos_count if pos_count > 0 else 1.0

    # Preprocess training data once
    X_train_processed = preprocessor.transform(X_train)

    from sklearn.model_selection import StratifiedKFold, cross_val_score

    def objective(trial):
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 100, 300),
            "max_depth": trial.suggest_int("max_depth", 4, 10),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1.0, 50.0, log=True),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
            "gamma": trial.suggest_float("gamma", 0.0, 5.0),
            "random_state": 42,
            "scale_pos_weight": scale_pos_weight,
            "eval_metric": "logloss",
            "n_jobs": 1,
        }
        model = XGBClassifier(**params)
        cv = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
        scores = cross_val_score(model, X_train_processed, y_train, cv=cv, scoring="roc_auc")
        return scores.mean()

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
    )
    study.optimize(objective, n_trials=50, timeout=1200, show_progress_bar=False)

    print(f"Best Optuna AUC-ROC: {study.best_value:.4f}")
    print(f"Best params: {study.best_params}")

    # Refit with best params
    best_model = XGBClassifier(
        **study.best_params,
        random_state=42,
        scale_pos_weight=scale_pos_weight,
        eval_metric="logloss",
        n_jobs=-1,
    )
    best_model.fit(X_train_processed, y_train)

    pipeline = Pipeline([
        ("preprocessor", preprocessor),
        ("classifier", best_model),
    ])

    return pipeline


def evaluate_model(model, X, y, dataset_name: str = "test") -> dict:
    """Evaluate a trained model and print metrics.

    Args:
        model: Trained sklearn Pipeline.
        X: Feature data.
        y: True labels.
        dataset_name: Label for the dataset (e.g., 'val', 'test').

    Returns:
        Dict of evaluation metrics.
    """
    y_pred = model.predict(X)
    y_proba = model.predict_proba(X)[:, 1]

    acc = accuracy_score(y, y_pred)
    f1 = f1_score(y, y_pred, average="weighted")
    auc = roc_auc_score(y, y_proba)
    cm = confusion_matrix(y, y_pred)

    print(f"\n=== {dataset_name.upper()} Set Results ===")
    print(f"Accuracy:  {acc:.4f}")
    print(f"F1 (wt):   {f1:.4f}")
    print(f"AUC-ROC:   {auc:.4f}")
    print(f"\nConfusion Matrix:\n{cm}")
    print(f"\nClassification Report:\n{classification_report(y, y_pred)}")

    return {
        "dataset": dataset_name,
        "accuracy": round(acc, 4),
        "f1_weighted": round(f1, 4),
        "auc_roc": round(auc, 4),
        "confusion_matrix": cm.tolist(),
    }


def save_model(model, algorithm: str, output_dir: str, metrics: dict) -> str:
    """Save trained model and metrics.

    Args:
        model: Trained sklearn Pipeline.
        algorithm: Algorithm name ('rf' or 'xgb').
        output_dir: Directory to save the model.
        metrics: Evaluation metrics dict.

    Returns:
        Path to the saved model file.
    """
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_filename = f"{algorithm}_model_{timestamp}.joblib"
    model_path = os.path.join(output_dir, model_filename)

    joblib.dump(model, model_path)
    print(f"\nModel saved to: {model_path}")

    # Save metrics alongside
    metrics_path = os.path.join(output_dir, f"{algorithm}_metrics_{timestamp}.json")
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"Metrics saved to: {metrics_path}")

    return model_path


def main():
    """Parse arguments and run the training pipeline."""
    parser = argparse.ArgumentParser(
        description="Train RF and/or XGBoost models on loan application data."
    )
    parser.add_argument(
        "--data-path",
        type=str,
        default=".tmp/synthetic_loans.csv",
        help="Path to training data CSV (default: .tmp/synthetic_loans.csv)",
    )
    parser.add_argument(
        "--algorithm",
        type=str,
        choices=["rf", "xgb", "both"],
        default="both",
        help="Algorithm to train: rf, xgb, or both (default: both)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="backend/ml_models",
        help="Directory to save trained models (default: backend/ml_models)",
    )
    args = parser.parse_args()

    # Load and validate data
    df = load_and_validate(args.data_path)

    # Split data
    X_train, X_val, X_test, y_train, y_val, y_test = split_data(df)

    # Build preprocessor
    preprocessor = build_preprocessor()

    algorithms_to_train = []
    if args.algorithm in ("rf", "both"):
        algorithms_to_train.append("rf")
    if args.algorithm in ("xgb", "both"):
        algorithms_to_train.append("xgb")

    for alg in algorithms_to_train:
        # Train
        if alg == "rf":
            model = train_random_forest(X_train, y_train, preprocessor)
        else:
            model = train_xgboost(X_train, y_train, preprocessor)

        # Evaluate on validation set
        val_metrics = evaluate_model(model, X_val, y_val, dataset_name="validation")

        # Evaluate on test set
        test_metrics = evaluate_model(model, X_test, y_test, dataset_name="test")

        # Check for overfitting
        val_acc = val_metrics["accuracy"]
        test_acc = test_metrics["accuracy"]
        if val_acc - test_acc > 0.05:
            print(
                f"\nWARNING: Possible overfitting detected for {alg.upper()}. "
                f"Val accuracy ({val_acc:.4f}) is significantly higher than "
                f"test accuracy ({test_acc:.4f}). Consider reducing model complexity."
            )

        # Save
        combined_metrics = {
            "algorithm": alg,
            "validation": val_metrics,
            "test": test_metrics,
            "trained_at": datetime.now().isoformat(),
        }
        save_model(model, alg, args.output_dir, combined_metrics)

    print("\nTraining complete.")


if __name__ == "__main__":
    main()
