#!/usr/bin/env python3
"""Compare model metrics: hardcoded vs live-calibrated synthetic data.

Generates data both ways, trains XGBoost on each, and prints a
side-by-side comparison of all key metrics.

Usage:
    python tools/compare_calibrations.py
    python tools/compare_calibrations.py --num-records 20000
    python tools/compare_calibrations.py --algorithm rf
"""

import argparse
import os
import sys
import tempfile
import time

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

import numpy as np
import pandas as pd


def generate_and_train(label: str, generator, num_records: int, seed: int,
                       algorithm: str, tmpdir: str) -> dict:
    """Generate data, save to CSV, train model, return metrics."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    t0 = time.time()
    print(f"  Generating {num_records} records...")
    df = generator.generate(num_records=num_records, random_seed=seed)

    csv_path = os.path.join(tmpdir, f'{label.lower().replace(" ", "_")}.csv')
    generator.save_to_csv(df, csv_path)
    gen_time = time.time() - t0
    print(f"  Generated in {gen_time:.1f}s — {len(df)} rows, "
          f"approval rate {df['approved'].mean():.1%}")

    # Distribution summary
    print(f"  Income P50: ${df['annual_income'].median():,.0f}")
    print(f"  Loan amount P50: ${df['loan_amount'].median():,.0f}")
    print(f"  Credit score P50: {df['credit_score'].median():.0f}")
    print(f"  DTI >= 6 share: {(df['debt_to_income'] >= 6).mean():.1%}")

    if 'property_value' in df.columns:
        home = df[df['property_value'] > 0]
        if len(home) > 0:
            lvr = home['loan_amount'] / home['property_value']
            print(f"  LVR >= 80% share: {(lvr >= 0.80).mean():.1%}")

    # Train model
    print(f"  Training {algorithm.upper()} model...")
    from apps.ml_engine.services.trainer import ModelTrainer
    trainer = ModelTrainer()

    t1 = time.time()
    _model, metrics = trainer.train(
        data_path=csv_path,
        algorithm=algorithm,
        use_reject_inference=True,
        reject_inference_labels=generator.reject_inference_labels,
    )
    train_time = time.time() - t1
    print(f"  Trained in {train_time:.1f}s")

    return metrics


def print_comparison(baseline_metrics: dict, live_metrics: dict):
    """Print side-by-side metric comparison."""
    print(f"\n{'='*70}")
    print(f"  METRIC COMPARISON: Hardcoded (baseline) vs Live-calibrated")
    print(f"{'='*70}")

    key_metrics = [
        ('accuracy', 'Accuracy'),
        ('precision', 'Precision'),
        ('recall', 'Recall'),
        ('f1_score', 'F1 Score'),
        ('auc_roc', 'AUC-ROC'),
        ('brier_score', 'Brier Score (lower=better)'),
        ('gini_coefficient', 'Gini Coefficient'),
        ('ks_statistic', 'KS Statistic'),
        ('log_loss', 'Log Loss (lower=better)'),
        ('ece', 'ECE (lower=better)'),
    ]

    lower_is_better = {'brier_score', 'log_loss', 'ece'}
    results = []

    print(f"\n  {'Metric':<30} {'Baseline':>10} {'Live':>10} {'Delta':>10} {'Result':>10}")
    print(f"  {'-'*30} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")

    for key, label in key_metrics:
        b_val = baseline_metrics.get(key)
        l_val = live_metrics.get(key)

        if b_val is None or l_val is None:
            print(f"  {label:<30} {'N/A':>10} {'N/A':>10} {'N/A':>10} {'SKIP':>10}")
            continue

        delta = l_val - b_val
        if key in lower_is_better:
            improved = delta < 0
            pct = -delta / max(abs(b_val), 1e-9) * 100
        else:
            improved = delta > 0
            pct = delta / max(abs(b_val), 1e-9) * 100

        degraded = not improved and abs(pct) > 1.0
        result = 'BETTER' if improved else ('WORSE' if degraded else 'SAME')
        results.append((key, result, pct))

        sign = '+' if delta > 0 else ''
        print(f"  {label:<30} {b_val:>10.4f} {l_val:>10.4f} {sign}{delta:>9.4f} {result:>10}")

    # Cross-validation comparison
    for label_key, label_name in [('cv_mean', 'CV Mean AUC'), ('cv_std', 'CV Std')]:
        b = baseline_metrics.get(label_key)
        l = live_metrics.get(label_key)
        if b is not None and l is not None:
            delta = l - b
            sign = '+' if delta > 0 else ''
            print(f"  {label_name:<30} {b:>10.4f} {l:>10.4f} {sign}{delta:>9.4f}")

    # Overall verdict
    worse_count = sum(1 for _, r, _ in results if r == 'WORSE')
    better_count = sum(1 for _, r, _ in results if r == 'BETTER')

    print(f"\n  {'='*70}")
    if worse_count == 0:
        print(f"  PASS — {better_count} metrics improved, 0 degraded")
        print(f"  Live-calibrated data is safe to deploy.")
    else:
        print(f"  FAIL — {better_count} improved, {worse_count} degraded (>1%)")
        print(f"  Review degraded metrics before deploying.")
    print(f"  {'='*70}")


def main():
    parser = argparse.ArgumentParser(
        description="Compare model metrics: hardcoded vs live-calibrated data"
    )
    parser.add_argument(
        '--num-records', type=int, default=10000,
        help='Number of records per dataset (default: 10000)',
    )
    parser.add_argument(
        '--seed', type=int, default=42,
        help='Random seed (default: 42)',
    )
    parser.add_argument(
        '--algorithm', type=str, default='xgb', choices=['xgb', 'rf'],
        help='Algorithm to train (default: xgb)',
    )
    args = parser.parse_args()

    from apps.ml_engine.services.data_generator import DataGenerator

    with tempfile.TemporaryDirectory() as tmpdir:
        # --- Baseline: hardcoded constants (current behavior) ---
        baseline_gen = DataGenerator()
        baseline_metrics = generate_and_train(
            'Baseline (hardcoded)', baseline_gen,
            args.num_records, args.seed, args.algorithm, tmpdir,
        )

        # --- Treatment: live-calibrated benchmarks ---
        print("\nFetching live Australian benchmarks...")
        from apps.ml_engine.services.real_world_benchmarks import RealWorldBenchmarks
        svc = RealWorldBenchmarks()
        benchmarks = svc.get_calibration_snapshot()
        print(f"Snapshot assembled at {benchmarks['fetched_at']}")

        live_gen = DataGenerator(benchmarks=benchmarks, use_live_macro=True)
        live_metrics = generate_and_train(
            'Live-calibrated', live_gen,
            args.num_records, args.seed, args.algorithm, tmpdir,
        )

        # --- Comparison ---
        print_comparison(baseline_metrics, live_metrics)


if __name__ == '__main__':
    main()
