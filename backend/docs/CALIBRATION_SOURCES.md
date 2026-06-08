# Calibration sources for `DataGenerator`

> **Status:** living document. Update whenever a benchmark cited in
> `backend/apps/ml_engine/services/datagen/data_generator.py:50-67` is changed.

This system trains on **synthetic Australian retail-lending data** anchored to
public-domain calibration sources. We do not have access to a real lender's
loan book; instead, every distribution `DataGenerator` produces is calibrated
against a published Australian benchmark, and the trained model is
independently validated against the **Kaggle GMSC** dataset (150,000 real
borrowers).

## At a glance

- **10 named public AU sources** drive the synthetic distributions.
- **~3,200 LOC** of calibrated synthetic-data plumbing (`datagen/data_generator` +
  `external/benchmark_resolver` + `datagen/feature_generator` +
  `datagen/loan_performance_simulator` + `datagen/underwriting_engine`).
- **Independent real-data validation:** Kaggle GMSC AUC 0.866 (PR #141).
- **Last calibration audit:** 2026-05-07.

## Sources

| # | Source | Latest publication | Value(s) used | Encoded at |
|---|---|---|---|---|
| 1 | ATO Taxation Statistics 2022-23, Table 16 | 2024 | Median taxable income $55,868; male avg $86,199; female avg $62,046 | `data_generator.py:50` |
| 2 | ABS Employee Earnings Aug 2025 | Aug 2025 | Median $74,100/yr (all employees) | `data_generator.py:52` |
| 3 | ABS Characteristics of Employment Aug 2025 | Aug 2025 | Permanent ~77%, casual 19%, self-employed 7.6%, contract ~4% | `data_generator.py:53-54`; split encoded at `:80-85` |
| 4 | ABS Lending Indicators Dec Q 2025 | Dec 2025 | Avg owner-occ loan $693,801; FHB $560,249; investor $685,634 | `data_generator.py:55-56` |
| 5 | APRA Quarterly ADI Property Exposures Sep Q 2025 | Sep 2025 | 30.8% new-loan LVR ≥ 80%; 6.1% DTI ≥ 6; NPL rate 1.04% | `data_generator.py:57-58` |
| 6 | Equifax 2025 Credit Scorecard | 2025 | National avg 864/1200; age + state breakdowns | `data_generator.py:59-62` |
| 7 | RBA Financial Stability Review Oct 2025 | Oct 2025 | <1% owner-occ 90+ day arrears; 30-89d arrears 0.47% | `data_generator.py:63-64` |
| 8 | APRA Feb 2026 macroprudential update | Feb 2026 | DTI ≥ 6 limits activated | `data_generator.py:65` |
| 9 | Melbourne Institute HEM benchmarks 2025/2026 | 2025/2026 | CPI-indexed expenditure measure | `data_generator.py:66`, `underwriting_engine.HEM_TABLE` |
| 10 | ABS Total Value of Dwellings Dec Q 2025 | Dec 2025 | Mean dwelling value $1,074,700 | `data_generator.py:67` |

## Derived calibration constants

- **APRA serviceability buffer:** 3% above product rate (`data_generator.py:90`,
  matches APRA 2025 9.5–10.0% assessment rate).
- **Big-4 spread over RBA cash rate:** 2.15% (`data_generator.py:95`).
- **State-level HEM multiplier:** Sydney/Melbourne ↑, regional ↓
  (`underwriting_engine.STATE_HEM_MULTIPLIER`).
- **HELP repayment thresholds:** ATO 2025-26 schedule (`data_generator.py:217`).
- **RBA cash rate quarterly history:** actual + projected (`data_generator.py:345`).

## Validation methodology

1. **Internal hold-out:** 20% temporal-quarter test split. Trained model
   reports AUC on the held-out quarter (`training_metadata.temporal_cv_auc_*`).
2. **External real-data benchmark:** Kaggle GMSC (150k real borrowers,
   90+ day arrears within 2 years). Latest run: AUC 0.866. The < 1pp gap
   versus the synthetic test set indicates the synthetic distribution is not
   over-fit to its own quirks. See PR #141.
3. **Leakage regression test:**
   `backend/tests/test_data_generator_no_leak.py` enforces
   `POST_OUTCOME_FEATURES` exclusion.
4. **Class-balance regression:**
   `backend/tests/test_data_generator_realism.py` keeps the synthetic
   positive-class rate within a documented band so a future calibration
   tweak can't silently drift the training distribution.

## Acknowledged gaps

- **Synthetic positive-class rate vs real arrears.** The project deliberately
  trains at ~56% positive-class rate (the supervised label) to give the
  model tractable signal without resampling. Real AU mortgage 90+ day
  arrears sit at 1.68% (APRA Q1 2025) — the gap is intentional for ML
  tractability. Measured on n=10000, seed=42: positive-class rate
  0.5595 ± 0.008 (across seeds 1/42/99) — see also
  `test_data_generator_realism.py`. A future iteration could match real
  prevalence with class weighting + focal loss.
- **No real lender data.** Out of reach without partnerships. The Kaggle
  GMSC validation is the closest available substitute.
- **No RBA stress-scenario simulator.** RBA April 2025's severe scenario
  (10% unemployment, −4% GDP, −40% house prices) would be a valuable
  stress-test mode but is deferred.
- **Single-snapshot calibration.** Sources are point-in-time; no longitudinal
  panel. Updating the manifest is manual.

## Maintenance

When a benchmark in `datagen/data_generator.py:50-67` changes:
1. Update the docstring in `datagen/data_generator.py`.
2. Update the row in this manifest's `## Sources` table (value + publication
   date + line reference).
3. Re-run `pytest backend/tests/test_data_generator_no_leak.py
   backend/tests/test_data_generator_realism.py` — both must stay green.
4. If the change affects class balance, re-train baseline + champion in the
   same PR.
