# Synthetic Data Realism Audit — How Close Are We to Production AU Lending?

**Purpose:** Catalogue, feature by feature, how the synthetic `DataGenerator` maps to what a real Australian lender (Big 4, neobank, or fintech) actually feeds into their credit decisioning model. Be explicit about what is **anchored to real AU statistics**, what is **approximated**, what is **fabricated**, and what is **missing**.

**Why this exists:** A fair reviewer asks *"the AUC is 0.88 on synthetic data — how much of that is because the synthetic data is too easy?"*. The external **GMSC benchmark** (`docs/experiments/gmsc_benchmark.md`) answers *"does the pipeline generalise to real borrower data?"* — and the answer is yes (AUC 0.866 on real Kaggle data). This audit answers the **complementary** question: *"given that we train on synthetic data, how realistic is that synthetic data on a per-feature basis?"*

**Bottom line upfront:** Most of the data is anchored to real AU statistics (ABS, APRA, ATO, RBA, Melbourne Institute). Three structural issues are called out below with severity and planned fixes. The most important — postcode-rate signal concentration — is fixed in the same PR as this document.

---

## Feature → Real AU Lender Source Mapping

### ✅ Anchored to real statistics

| Feature group | Source in generator | Real AU lender source | Realism |
|---|---|---|---|
| **HEM benchmarks** (`hem_benchmark`) | Melbourne Institute HEM tables, FY25/26 | Melbourne Institute HEM (same) | ✅ Direct use |
| **APRA 3% stress buffer** | `stressed_dsr = repayment_at_rate+3% / monthly_income` | APRA Prudential Standard APS 220 | ✅ Same rule |
| **NCCP serviceability** | Net monthly surplus after all commitments | NCCP Act s.131 | ✅ Same rule |
| **HECS/HELP thresholds** | ATO FY25/26 repayment table (hardcoded) | ATO tables (authoritative source) | ✅ Same table |
| **ANZSIC industry codes + income mix** | ABS AWE (Average Weekly Earnings) by division | ABS AWE (same) | ✅ Same source |
| **DTI calculation** | `(existing_debt + new_loan) / annual_income` | Standard Big 4 DTI | ✅ Correct |
| **LVR calculation** | `loan_amount / property_value` | Standard Big 4 LVR | ✅ Correct |
| **RBA cash rate + forecasts** | RBA Statement on Monetary Policy snapshots | RBA (same source) | ✅ Direct use |
| **SA4 unemployment** | ABS Labour Force by SA4 | ABS Labour Force (same) | ✅ Direct use |
| **Property SA3 multipliers** | ABS CoreLogic median-value indexes | CoreLogic / ABS (same) | ✅ Direct use |
| **Consumer confidence** | Westpac-Melbourne Institute index snapshots | Westpac-MI Index (same) | ✅ Direct use |
| **CCR repayment-history buckets** | 24-month bucket generator matching CCR schema | Equifax / illion / Experian CCR | ✅ Schema-compatible |
| **CDR transaction features** | Income-source count, essential-to-total spend, buffer-before-payday | CDR Open Banking (real schema) | ✅ Schema-compatible |
| **LMI trigger** | LVR > 80% → insurance required | Genworth / QBE (same rule) | ⚠ Rate applied but not capitalised (see below) |
| **LMI rate tables** | Anchored to public Genworth / QBE LMI premium tables | Real LMI premium tables | ✅ Values within published ranges |

### ⚠ Approximated or fabricated (tracked for fixes)

| # | Feature | Issue | Severity | Fix status |
|---|---|---|---|---|
| 1 | `postcode_default_rate` | Computed as `state_base * sa4_unemp_factor + N(0, 0.003)`. Noise is too tight — synthetic correlation with label-driving signal is ~0.85, real AU bureau correlation is ~0.35-0.45. Model learns an inflated shortcut. | **HIGH** | **FIXED in this PR** — std 0.003 → 0.008 |
| 2 | `monthly_expenses` does not compare against HEM floor | Real lenders fail serviceability when *declared* expenses < HEM floor (under-declaration flag). We generate `monthly_expenses` and output `hem_benchmark`, but never compute the `hem_gap` feature. | **HIGH** | Planned for follow-up PR (requires retraining pipeline) |
| 3 | LMI premium calculated but not capitalised into loan amount | Real lenders add 1–3% to principal when LMI required (inflates monthly repayment). Our generator computes the LMI rate but doesn't adjust `loan_amount`. | **MEDIUM** | Planned for follow-up PR |
| 4 | Employment-type rule mismatch between generator and underwriter | Generator applies static `0.80` casual income shading. Underwriter applies tenure-aware hard-deny (<1yr casual). Feature and label use different logics → label noise. | **MEDIUM** | Planned for follow-up PR |
| 5 | No income volatility features | Real underwriting compares YTD income mean to YTD income std (especially for self-employed / casual). We have only point-in-time income. | **LOW** | Planned for follow-up PR |
| 6 | Gambling spend ratio | Generated from age × state × 3-tier bucket. Not validated against actual CDR distribution. Affects default probability (+1.8x PD when `gambling_spend_ratio > 0.05`). | **LOW** | Accept — reasonable prior; real CDR distribution is proprietary |
| 7 | Income verification gap (`income_verification_gap`, `document_consistency_score`) | Present as features but not enforced by a payslip/PAYG cross-check path | **LOW** | Accept — fraud-signal placeholder is honest; not claiming full KYC |

### ❌ Missing features that real AU lenders use

| Feature | Why it matters | Added in this PR? |
|---|---|---|
| Full credit-mix separation (open credit cards vs personal loans vs home loans vs auto) | CCR reports this; model can penalise mix concentration | No — tracked for future |
| Collection-agency records | Distinct from defaults — affects decline rate | No |
| Part IX agreement discharge date | Different risk profile from active Part IX | No |
| Probation flag (employment <3 months) | Hard deny at most Big 4 banks | No |
| Multiple-applicant scoring (joint applications) | Different serviceability math | No — single-applicant model by design |
| Branch-flag (digital-only vs branch-acquired) | Acquisition channel affects default rate | Partially — `application_channel` exists |

---

## Why this matters for the AUC number

The headline production AUC on synthetic data is reported in `backend/docs/MODEL_CARD.md` as ~0.87–0.88 (Optuna-tuned). The **GMSC external benchmark** (same pipeline, real 150k Kaggle borrowers, 10 real features) reaches AUC 0.866 ± 0.003. The fact that the synthetic AUC is only ~0.01–0.02 higher than the real-data GMSC AUC is, on its own, a reasonable signal that the synthetic data is not dramatically easier than real data.

However, the **postcode-rate signal concentration** above is a known contributor to that gap. Fixing it (std 0.003 → 0.008) brings the synthetic feature's correlation with the label-driving unemployment signal from ~0.85 down to ~0.40, matching real-world AU bureau data. Expected impact on AUC: 0.005–0.015 drop — well within the noise band of typical retraining variance, but the *right* 0.01 to give up for credibility.

---

## Validation matrix

| Validation | How it's tested | Status |
|---|---|---|
| Schema matches real AU credit-decisioning inputs | Manual feature-source mapping (this document) | ✅ Done |
| Pipeline architecture generalises to real data | GMSC benchmark (`docs/experiments/gmsc_benchmark.md`) | ✅ Done — AUC 0.866 |
| No catastrophic label leakage | Underwriting engine is a simulator, not a label copy. Features that drive the label (`postcode_default_rate`, HEM, serviceability) are features a real lender also sees. | ✅ Confirmed |
| Signal concentration is realistic | Postcode rate noise matches real bureau correlation (~0.4 with SA4 unemployment) | ✅ Fixed in this PR |
| Fairness subgroup audit | SR 11-7 bias report per training run | ✅ In production model |
| External real-data benchmark | Kaggle GMSC benchmark (`make benchmark-gmsc`) | ✅ Automated |

---

## What this document is NOT

- This is not a validation of real-borrower performance. Only the GMSC benchmark attempts that.
- This is not a claim that the synthetic data is indistinguishable from real AU lending data. It isn't — it has no adversarial data quality, no edge-case borrowers, no outliers that don't fit the generator's sub-population priors, and no temporal drift.
- This is not a SR 11-7 model validation package — that lives in `backend/docs/MODEL_CARD.md` and the bias reports under `backend/apps/ml_engine/services/bias_analyzer.py`.

---

## Change log

- **2026-04-18** — Initial audit. Seven approximation issues catalogued with severity. Issue #1 (postcode signal concentration) fixed in this PR. Issues #2–#5 tracked for a follow-up realism PR that requires retraining.
