# Experiments - Methodology

## Data source

All experiments use the synthetic loan-application generator at `backend/apps/ml_engine/services/data_generator.py`. The generator is calibrated against AU macro anchors (see `reports/au-lender-benchmark.md`): HEM tables (Melbourne Institute 2025/26), APRA 3% serviceability buffer, state-level income distributions (ABS FY2022-23), Equifax-shaped credit scores (2025 average 864/1200), APRA QPEX Dec-2025 LVR and DTI mix.

## Reproducibility

- **Seed:** every command accepts `--seed` (default 42). `np.random.seed` is set before generator call. sklearn/xgboost/lightgbm all receive the seed via `random_state`.
- **Splits:** `train_test_split(test_size=0.2, stratify=y, random_state=<seed>)`. Benchmark uses a single 80/20 split for speed; ablation uses the same. The production training pipeline uses temporal split when `application_quarter` is present.
- **Feature engineering:** all derived features computed through `compute_derived_features` - the single source of truth used by trainer and predictor alike (see ADR-0002).
- **Imputation:** numeric columns only, fill with 0 at benchmark/ablation time (simple to audit; production uses train-data medians bundled with the model).
- **Label-leakage guard:** post-approval / post-origination columns emitted by the generator (`approval_type`, `default_probability`, `actual_outcome`, `ever_30dpd`, `ever_90dpd`, ...) are excluded from `X` via a shared `LABEL_LEAKING_COLUMNS` tuple in both commands. Changes to the generator schema must be reflected in that tuple or AUCs will trivially reach 1.0.

## What each command measures

- **`run_benchmark`** - same data, same split, same features; four models with default (not Optuna-tuned) hyperparameters. Compares AUC-ROC, PR-AUC, Brier, and training wall-clock. Purpose: establish XGBoost's lead over simpler baselines on identical footing.
- **`run_ablation`** - baseline XGBoost vs k retrains each with one top-importance feature removed. delta-AUC and delta-PR-AUC per feature. Purpose: identify load-bearing features and detect whether removing any single feature collapses the model (signal for over-reliance).

## How to extend

- Add a new model to `run_benchmark._build_models`.
- Add a new metric to the benchmark table by importing from `apps.ml_engine.services.metrics` and extending `_render_table`.
- Preserve human takeaways: every generated doc has `<!-- ... TABLE END -->` markers - the command only rewrites content above the end marker; everything below is preserved across runs.

## Known limitations

- Benchmark trains without hyperparameter tuning, so "XGBoost wins by X" reflects default settings. Optuna-tuned XGBoost is the production configuration.
- Ablation uses importance ranking from the baseline model only; interactions between removed-feature pairs are not explored.
- Synthetic data means results may not match real-world calibration on launch.
- The committed `benchmark.md` and `ablations.md` were generated with `--num-records=2000` for fast, reproducible CI-friendly artefacts. Production-scale runs (10k-50k records) are executed post-merge via `make benchmark` / `make ablate`; the human takeaway section is preserved across runs via end-of-table markers.
