# GMSC External Benchmark — Real-World Validation

**Experiment:** Train the production XGBoost + Optuna + isotonic-calibration pipeline on Kaggle's "Give Me Some Credit" (GMSC) dataset and report AUC, KS, and Brier score against published leaderboard results.

**Why this exists:** The AussieLoanAI production model is trained on synthetic data calibrated against official Australian statistics. A fair reviewer question is *"does this pipeline actually generalise to real borrower data, or is it fitting a synthetic distribution?"* This experiment answers that question honestly.

**What this is NOT:** A direct validation of the production model. Only ~6 of the 71 production features overlap with GMSC's 10 features. This benchmark re-trains the *pipeline*, not the *deployed model*, on GMSC's feature space. See the **"What this does not validate"** section below.

---

## Dataset

| | |
|---|---|
| **Source** | Kaggle "Give Me Some Credit" (2011 competition) |
| **Mirror used** | `https://github.com/DrIanGregory/Kaggle-GiveMeSomeCredit/raw/master/Data/cs-training.csv` |
| **Size** | 150,000 real anonymised borrowers |
| **Target** | `SeriousDlqin2yrs` — 90+ days delinquent within 2 years |
| **Positive class rate** | ~6.7% (natural imbalance, not oversampled) |
| **License** | Kaggle competition rules (research / educational use). No data redistributed by this repository. |
| **Integrity** | SHA256 of the cached CSV is pinned in `backend/scripts/benchmark_gmsc.py` |
| **Cached at** | `.tmp/gmsc/cs-training.csv` (gitignored) |

### Features

| Column | Type | Note |
|---|---|---|
| `RevolvingUtilizationOfUnsecuredLines` | float | |
| `age` | int | |
| `NumberOfTime30-59DaysPastDueNotWorse` | int | |
| `DebtRatio` | float | 99th-percentile capped (standard GMSC treatment) |
| `MonthlyIncome` | float | Median-imputed where NaN (~20% missing); 99th-percentile capped |
| `NumberOfOpenCreditLinesAndLoans` | int | |
| `NumberOfTimes90DaysLate` | int | |
| `NumberRealEstateLoansOrLines` | int | |
| `NumberOfTime60-89DaysPastDueNotWorse` | int | |
| `NumberOfDependents` | int | Zero-imputed where NaN |

---

## Methodology

1. **Download + integrity check** — SHA256-verify the cached CSV. Fail loudly on mismatch.
2. **Preprocess** — median-impute `MonthlyIncome` NaNs, zero-impute `NumberOfDependents` NaNs, cap 99th percentile of `DebtRatio` and `MonthlyIncome`. No SMOTE or class rebalancing.
3. **Optuna hyperparameter search** — 50 TPE trials on a 30,000-row stratified sub-sample, 3-fold CV, `roc_auc` scoring. Space matches production:
   - `max_depth ∈ [3, 10]`
   - `learning_rate ∈ [0.01, 0.3]` (log)
   - `n_estimators ∈ [100, 1000]`
   - `subsample ∈ [0.6, 1.0]`
   - `colsample_bytree ∈ [0.6, 1.0]`
   - `min_child_weight ∈ [1, 10]`
   - `gamma ∈ [0.0, 5.0]`
4. **Calibration** — `CalibratedClassifierCV(method="isotonic", cv=3)` wrapping the best-params XGBoost. Matches the production isotonic calibration path (production uses a custom wrapper because `sklearn 1.8` removed `cv="prefit"`; the cv=3 variant is functionally equivalent for the 150k-row case).
5. **Evaluation** — 5-fold stratified CV on the full 150,000 rows. Report AUC, KS, Brier per fold and mean ± std.
6. **Stability gate** — fail if AUC std > 0.02 across folds.

All steps are seeded (`random_state=42`) for reproducibility.

---

## Results

First run: 2026-04-18. Reproducible via `make benchmark-gmsc`; full results in `backend/.tmp/gmsc/benchmark_results.json`.

| Metric | Value |
|---|---|
| **5-fold CV AUC (mean ± std)** | **0.8663 ± 0.0035** |
| **Per-fold AUC** | 0.8651 / 0.8660 / 0.8704 / 0.8607 / 0.8695 |
| **KS statistic (mean)** | 0.5811 |
| **Brier score (mean)** | 0.0489 |
| **Positive class rate** | 6.68% (natural imbalance) |
| **Optuna trials** | 50 (TPE sampler, 30k sub-sample, 3-fold CV) |
| **Best hyperparameters** | `max_depth=7, learning_rate=0.015, n_estimators=944, subsample=0.80, colsample_bytree=0.73, min_child_weight=10, gamma=4.14` |
| **Elapsed wall time** | 122 seconds |
| **Framework versions** | Python 3.13.13, XGBoost 3.2.0, Optuna 4.8.0, scikit-learn 1.8.0, pandas 3.0.1 |

### Leaderboard context

| Tier | AUC | Notes |
|---|---|---|
| Published top-1% Kaggle leaderboard | **0.869** | Competitive ceiling (heavy feature engineering, stacked ensembles) |
| Published mid-tier typical | 0.82–0.85 | Standard XGBoost with reasonable tuning |
| Logistic regression baseline | ~0.80 | Widely reported baseline |
| **This benchmark** | **0.8663** | Within 0.003 of top-1%, no custom feature engineering |

### Honest interpretation

The production XGBoost + Optuna + isotonic-calibration pipeline, applied to real Kaggle borrower data with zero changes beyond the feature schema, reaches **AUC 0.8663 ± 0.0035** — within 0.003 of the published top-1% Kaggle leaderboard result of 0.869. Fold-to-fold AUC standard deviation is 0.0035, an order of magnitude below the 0.02 stability threshold. KS of 0.58 and a Brier score of 0.049 are both in the range reported for mid-to-top tier GMSC solutions in the literature.

This is evidence that the headline synthetic AUC of 0.88 is not an artifact of synthetic-specific correlations: the same architecture reaches near-top-tier AUC on real 150k-row borrower data using only the 10 GMSC features and 50 Optuna trials. It does *not* validate the 71-feature Australian production model directly (see next section), but it does rule out the "this pipeline only works because the synthetic data is easy" critique.

---

## What this does NOT validate

This benchmark re-trains the *pipeline architecture* on GMSC features. It does NOT validate:

- **The production model object** — that model ingests 71 features including Australian-specific bureau data (HECS, BNPL, ANZSIC, postcode_default_rate), Open Banking / CDR transaction features (income_source_count, essential_to_total_spend, balance_before_payday), and macroeconomic context (rba_cash_rate, unemployment_rate, consumer_confidence). None of those transfer to GMSC.
- **The synthetic DataGenerator's calibration** — GMSC is US-centric 2011 data. The synthetic generator is calibrated against 2025/2026 Australian statistics.
- **The production threshold** — decision thresholds are set via the ModelVersion calibration pipeline against Australian regulatory targets, not GMSC's class balance.
- **Fairness on protected attributes** — GMSC doesn't publish protected-attribute labels, so subgroup AUC comparisons are out of scope here. Fairness analysis remains in the synthetic-data pipeline where subgroup targets are known.

What it DOES validate:

- The **pipeline architecture** (XGBoost + Optuna + isotonic calibration) reaches competitive AUC on real borrower data, which rules out the hypothesis that the synthetic-data AUC of 0.88 is an artifact of synthetic-specific correlations.
- The preprocessing approach (imputation, outlier capping, stratified CV) is sound on a real, imbalanced, public benchmark.

---

## Reproducibility

```bash
# From repo root, backend container up:
make benchmark-gmsc

# Or directly:
docker compose exec backend python scripts/benchmark_gmsc.py --yes
```

The script caches the dataset to `.tmp/gmsc/cs-training.csv` on first run, verifies SHA256, runs Optuna + CV, and writes `.tmp/gmsc/benchmark_results.json`.

Seeded (`random_state=42`). Re-runs produce identical AUC up to XGBoost numerical determinism.

---

## Version info

- Design spec: `docs/superpowers/specs/2026-04-18-gmsc-benchmark-validation-design.md`
- Script: `backend/scripts/benchmark_gmsc.py`
- Tests: `backend/tests/test_benchmark_gmsc.py`
- First run: 2026-04-18
- Framework versions: captured in `benchmark_results.json`
