#!/usr/bin/env python3
"""Evaluate a trained loan approval model against test data.

Loads a saved joblib model and test dataset, then generates a comprehensive
evaluation report including accuracy, precision, recall, F1, AUC-ROC,
confusion matrix data, ROC curve data, and feature importances.

Usage:
    python tools/evaluate_model.py --model-path backend/ml_models/rf_model.joblib --test-data-path .tmp/synthetic_loans.csv
    python tools/evaluate_model.py --model-path backend/ml_models/xgb_model.joblib
"""

import argparse
import json
import os
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)


# Feature definitions (must match training)
NUMERIC_FEATURES = [
    "income",
    "credit_score",
    "loan_amount",
    "debt_to_income",
    "employment_length",
    "annual_income",
]
CATEGORICAL_FEATURES = ["purpose", "home_ownership"]
BINARY_FEATURES = ["has_cosigner"]
TARGET = "approved"


def load_model(model_path: str):
    """Load a trained model from disk.

    Args:
        model_path: Path to the .joblib model file.

    Returns:
        Loaded sklearn Pipeline.

    Raises:
        FileNotFoundError: If model file does not exist.
    """
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model file not found: {model_path}")

    model = joblib.load(model_path)
    print(f"Loaded model from: {model_path}")
    return model


def load_test_data(data_path: str) -> pd.DataFrame:
    """Load test data from CSV.

    Args:
        data_path: Path to the CSV file.

    Returns:
        DataFrame with test data.

    Raises:
        FileNotFoundError: If data file does not exist.
    """
    if not os.path.exists(data_path):
        raise FileNotFoundError(f"Data file not found: {data_path}")

    df = pd.read_csv(data_path)
    print(f"Loaded {len(df)} records from {data_path}")

    required_cols = NUMERIC_FEATURES + CATEGORICAL_FEATURES + BINARY_FEATURES + [TARGET]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    return df


def extract_feature_importances(model) -> dict:
    """Extract feature importances from the model pipeline.

    Args:
        model: Trained sklearn Pipeline with a preprocessor and classifier.

    Returns:
        Dict mapping feature names to importance values.
    """
    try:
        classifier = model.named_steps["classifier"]
        preprocessor = model.named_steps["preprocessor"]
    except (AttributeError, KeyError):
        print("WARNING: Could not extract feature importances (unexpected pipeline structure).")
        return {}

    # Get feature names from preprocessor
    try:
        feature_names = preprocessor.get_feature_names_out()
    except AttributeError:
        # Fallback: construct names manually
        feature_names = NUMERIC_FEATURES.copy()
        for col in CATEGORICAL_FEATURES:
            feature_names.append(f"{col}_encoded")
        feature_names.extend(BINARY_FEATURES)

    # Get importances
    try:
        importances = classifier.feature_importances_
    except AttributeError:
        print("WARNING: Classifier does not support feature_importances_.")
        return {}

    # Build mapping
    importance_dict = {}
    for name, imp in zip(feature_names, importances):
        # Clean up sklearn-generated names
        clean_name = str(name).replace("num__", "").replace("cat__", "").replace("bin__", "")
        importance_dict[clean_name] = round(float(imp), 6)

    # Sort by importance descending
    importance_dict = dict(
        sorted(importance_dict.items(), key=lambda x: x[1], reverse=True)
    )

    return importance_dict


def evaluate(model, df: pd.DataFrame) -> dict:
    """Run full evaluation of a model against a dataset.

    Args:
        model: Trained sklearn Pipeline.
        df: DataFrame with features and target.

    Returns:
        Comprehensive evaluation report as a dict.
    """
    feature_cols = NUMERIC_FEATURES + CATEGORICAL_FEATURES + BINARY_FEATURES
    X = df[feature_cols]
    y = df[TARGET]

    # Predictions
    y_pred = model.predict(X)
    y_proba = model.predict_proba(X)[:, 1]

    # Core metrics
    acc = accuracy_score(y, y_pred)
    precision = precision_score(y, y_pred, average="weighted")
    recall = recall_score(y, y_pred, average="weighted")
    f1 = f1_score(y, y_pred, average="weighted")
    auc = roc_auc_score(y, y_proba)

    # Confusion matrix
    cm = confusion_matrix(y, y_pred)
    tn, fp, fn, tp = cm.ravel()

    # ROC curve data (sampled for JSON size)
    fpr, tpr, thresholds = roc_curve(y, y_proba)
    # Sample up to 100 points for the ROC curve
    if len(fpr) > 100:
        indices = np.linspace(0, len(fpr) - 1, 100, dtype=int)
        fpr_sampled = fpr[indices].tolist()
        tpr_sampled = tpr[indices].tolist()
        thresholds_sampled = thresholds[indices].tolist()
    else:
        fpr_sampled = fpr.tolist()
        tpr_sampled = tpr.tolist()
        thresholds_sampled = thresholds.tolist()

    # Feature importances
    feature_importances = extract_feature_importances(model)

    # Check for dominant feature
    if feature_importances:
        top_feature, top_importance = next(iter(feature_importances.items()))
        if top_importance > 0.5:
            print(
                f"\nWARNING: Feature '{top_feature}' has {top_importance:.1%} importance. "
                "This may indicate data leakage. Investigate before deploying."
            )

    # Build report
    report = {
        "metrics": {
            "accuracy": round(acc, 4),
            "precision_weighted": round(precision, 4),
            "recall_weighted": round(recall, 4),
            "f1_weighted": round(f1, 4),
            "auc_roc": round(auc, 4),
        },
        "confusion_matrix": {
            "true_negatives": int(tn),
            "false_positives": int(fp),
            "false_negatives": int(fn),
            "true_positives": int(tp),
            "matrix": cm.tolist(),
        },
        "roc_curve": {
            "fpr": [round(x, 4) for x in fpr_sampled],
            "tpr": [round(x, 4) for x in tpr_sampled],
            "thresholds": [round(x, 4) for x in thresholds_sampled],
        },
        "feature_importances": feature_importances,
        "dataset_info": {
            "num_records": len(df),
            "approval_rate": round(float(y.mean()), 4),
            "class_distribution": {
                "approved": int(y.sum()),
                "denied": int((1 - y).sum()),
            },
        },
    }

    return report


def print_report(report: dict) -> None:
    """Print a human-readable evaluation report.

    Args:
        report: Evaluation report dict.
    """
    print("\n" + "=" * 60)
    print("MODEL EVALUATION REPORT")
    print("=" * 60)

    metrics = report["metrics"]
    print(f"\n  Accuracy:          {metrics['accuracy']:.4f}")
    print(f"  Precision (wt):    {metrics['precision_weighted']:.4f}")
    print(f"  Recall (wt):       {metrics['recall_weighted']:.4f}")
    print(f"  F1 Score (wt):     {metrics['f1_weighted']:.4f}")
    print(f"  AUC-ROC:           {metrics['auc_roc']:.4f}")

    cm = report["confusion_matrix"]
    print(f"\n  Confusion Matrix:")
    print(f"    TN={cm['true_negatives']}  FP={cm['false_positives']}")
    print(f"    FN={cm['false_negatives']}  TP={cm['true_positives']}")

    fi = report["feature_importances"]
    if fi:
        print(f"\n  Top Feature Importances:")
        for i, (name, importance) in enumerate(fi.items()):
            if i >= 10:
                break
            bar = "#" * int(importance * 50)
            print(f"    {name:30s} {importance:.4f}  {bar}")

    ds = report["dataset_info"]
    print(f"\n  Dataset: {ds['num_records']} records, {ds['approval_rate']:.1%} approval rate")
    print("=" * 60)


def main():
    """Parse arguments and run evaluation."""
    parser = argparse.ArgumentParser(
        description="Evaluate a trained loan approval model against test data."
    )
    parser.add_argument(
        "--model-path",
        type=str,
        required=True,
        help="Path to the saved .joblib model file",
    )
    parser.add_argument(
        "--test-data-path",
        type=str,
        default=".tmp/synthetic_loans.csv",
        help="Path to test data CSV (default: .tmp/synthetic_loans.csv)",
    )
    parser.add_argument(
        "--output-path",
        type=str,
        default=".tmp/model_report.json",
        help="Path to save the JSON report (default: .tmp/model_report.json)",
    )
    args = parser.parse_args()

    # Load model and data
    model = load_model(args.model_path)
    df = load_test_data(args.test_data_path)

    # Evaluate
    report = evaluate(model, df)

    # Print human-readable report
    print_report(report)

    # Save JSON report
    output_dir = os.path.dirname(args.output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(args.output_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nFull report saved to: {args.output_path}")


if __name__ == "__main__":
    main()
