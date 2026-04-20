# Synthetic Data Realism Audit

> **Scope:** feature-by-feature audit of `backend/apps/ml_engine/services/data_generator.py`
> against real Australian lender inputs and official statistics. Companion to
> [`backend/docs/MODEL_CARD.md`](../../backend/docs/MODEL_CARD.md) — the model card
> lists calibration sources; this document grades every emitted feature against
> them. The goal is honest, auditable engineering: no feature is claimed to be
> "calibrated" unless its generation code directly uses an official source.
>
> **Last reviewed:** 2026-04-20, against `data_generator.py` on master
> [`7756761`](https://github.com/zeroyuekun/loan-approval-ai-system/commit/7756761).

## Purpose

AussieLoanAI is trained on synthetic data (no real borrower records are ever
used). That choice is necessary — real bureau data cannot be distributed — but it
creates a documentation obligation: every distribution, threshold, and lookup
table in the generator must be traceable to a public Australian benchmark or
flagged as an approximation. This audit exists so reviewers (interviewers,
auditors, future maintainers) can see at a glance:

1. **Which features are anchored** to an official statistic (ABS / APRA / RBA /
   Equifax / Melbourne Institute / ATO / CoreLogic).
2. **Which features are approximated** using reasonable industry conventions
   (e.g., the 3% monthly-limit rule banks use for credit-card assessment) — not
   wrong, but not a number you can cite from a specific government table.
3. **Which features are missing a cited source** and should be improved or
   deprecated.
4. **Which parts of real AU lending are not captured at all**, so model
   performance on real data remains bounded.

## Methodology

Each feature emitted by `DataGenerator.generate()` is graded into one of three
buckets:

- **ANCHORED** — the value, distribution, or threshold is derived directly from
  a named, public Australian source. The generating code references the source
  constant (or a derived constant in a table such as `HEM_TABLE`,
  `STATE_HEM_MULTIPLIER`, `INCOME_SHADING`).
- **APPROXIMATED** — the value is a reasonable industry convention or an
  internally consistent derivation from anchored inputs, but not a figure you
  can look up in an official publication.
- **UNCITED** — the value is a placeholder, an arbitrary distribution, or a
  heuristic that has not yet been mapped to a specific source. These are the
  highest-priority items to revisit.

Features marked ANCHORED still carry the normal caveats of synthetic data (no
real post-origination behaviour, no real temporal default patterns). The grade
describes **calibration**, not validation.

## Summary

| Grade | Count | Notes |
|-------|-------|-------|
| ANCHORED | ~28 | base demographics, loan structure, macro context, bureau aggregates, HEM/LMI policy variables |
| APPROXIMATED | ~18 | behavioural/CDR aggregates, derived ratios, application-integrity scores |
| UNCITED | ~6 | gambling-spend ratio, optimism-bias flag, financial-literacy score, application channel mix, loan-trigger event, postcode default noise (noise std anchored, per-postcode map is illustrative) |

Counts are approximate because several "features" are composite (interactions,
one-hot encodings). The feature-by-feature table below is the authoritative
catalogue.

## Calibration sources

The sources below are the ones actually consumed by `DataGenerator` (not every
source cited in the model card — this list is narrower and ordered by how many
features it anchors). Links point to the specific publication that backs each
constant.

| Source | What it anchors | Where it lives in code |
|---|---|---|
| ATO Taxation Statistics 2022-23 (Table 16) | Individual income percentile distributions, median taxable income | `data_generator.py` income section (see `annual_income` copula marginals) |
| ABS Employee Earnings Aug 2025 | National median earnings ($74,100), state-level earnings medians | `data_generator.py` income + state modifiers |
| ABS Characteristics of Employment Aug 2025 | Employment-type mix (permanent ~77%, casual 19%, self-employed 7.6%, contract ~4%) | `EMPLOYMENT_TYPES` + `EMPLOYMENT_TYPE_WEIGHTS` |
| ABS Lending Indicators Dec Q 2025 | Avg owner-occupier loan $693,801; FHB $560,249; investor $685,634 | loan-amount sampling by sub-population |
| APRA Quarterly ADI Property Exposures Sep Q 2025 | 30.8% new loans LVR ≥ 80%, 6.1% DTI ≥ 6, NPL rate 1.04% | outcome calibration (target default rate, LVR band shape) |
| APRA macroprudential Feb 2026 | DTI ≥ 6 limits activated — influences denial thresholds | `UnderwritingEngine.compute_approval` |
| Equifax 2025 Credit Scorecard | National mean 864/1200, state-level means (ACT 915 down to NT 844) | credit-score generation with state offsets |
| RBA Financial Stability Review Oct 2025 | <1% owner-occupier 90+ arrears, 0.47% 30-89 arrears | post-origination performance simulator |
| RBA Cash Rate history 2023Q3–2026Q2 | Quarterly cash rate (4.10% declining to 3.60%), product rate = cash + 2.15 spread | `rba_cash_rate`, `product_rate`, `stress_test_rate` |
| Melbourne Institute HEM benchmarks 2025/2026 | 50-cell HEM lookup by applicant type × dependants × income bracket | `UnderwritingEngine.HEM_TABLE`; re-exported as `DataGenerator.HEM_TABLE` |
| CoreLogic / Cotality 2025 | Median house prices by capital (Sydney $1.65M → Darwin $520K) | `PropertyDataService` median/dispersion by state |
| ABS Total Value of Dwellings Dec Q 2025 | National mean dwelling $1.0747M (used as sanity cap) | property-value sampler |
| Westpac-Melbourne Institute Consumer Confidence | Quarterly index 79.7 → 99.0 (2023Q3–2026Q2) | `consumer_confidence` macro feature |

## Feature-by-feature audit

The categories below match the groupings in `MODEL_CARD.md` → "Feature
Categories". Each row is one emitted column of `DataGenerator.generate()`.

### Base demographics & loan structure (14)

| Feature | Grade | Source / rationale |
|---|---|---|
| `annual_income` | ANCHORED | ATO Taxation Statistics 2022-23 marginals; ABS earnings for state-level shift; copula preserves correlation with credit score and employment length |
| `credit_score` | ANCHORED | Equifax 2025 national mean 864 with state offsets (ACT 915 → NT 844) and age-group adjustments (18–30: 715; 31–40: 839) |
| `loan_amount` | ANCHORED | ABS Lending Indicators Dec Q 2025 averages per sub-population (FHB, upgrader, investor, personal, business) |
| `loan_term_months` | APPROXIMATED | Product-conventional term distributions (home: 25–30y, auto: 3–7y, personal: 1–5y). Not from a named source. |
| `debt_to_income` | APPROXIMATED | Derived from sampled existing debt and income; APRA's DTI≥6 macroprudential threshold used in approval logic |
| `employment_length` | ANCHORED | ABS Characteristics of Employment tenure distributions |
| `has_cosigner` | APPROXIMATED | Industry convention (~12% of personal loans); not from a cited figure |
| `property_value` | ANCHORED | CoreLogic 2025 medians per state, log-normal dispersion, sanity-capped by ABS Total Value of Dwellings |
| `deposit_amount` | APPROXIMATED | Derived from sampled LVR distribution so APRA's 30.8% LVR≥80% headline is recovered |
| `monthly_expenses` | APPROXIMATED | Declared-vs-HEM distribution: most applicants declare HEM+10–30%, a minority declare below HEM (flagged in the floor-vs-declared gap) |
| `existing_credit_card_limit` | APPROXIMATED | RBA credit card data (avg limit ~$10K); distribution shape is illustrative |
| `number_of_dependants` | ANCHORED | ABS Census household-composition distribution |
| `has_hecs` | ANCHORED | ATO HECS-HELP FY25/26 participation rate (~12% of taxpayers) |
| `has_bankruptcy` | APPROXIMATED | AFSA personal insolvency base rate (~0.2%) used as sampling rate; bankruptcy depth not modelled |

### Bureau / credit report aggregates (6)

| Feature | Grade | Source / rationale |
|---|---|---|
| `num_credit_enquiries_6m` | ANCHORED | Equifax Hard Enquiry Australia 2024 distribution; correlated with credit-seeking behaviour sub-population |
| `worst_arrears_months` | ANCHORED | RBA FSR 2025 arrears mix (≤30d, 30–89d, 90+d) |
| `num_defaults_5yr` | APPROXIMATED | Illion / Equifax base rates; sampling distribution is illustrative |
| `credit_history_months` | APPROXIMATED | Linear growth from age, capped by "earliest possible account" age |
| `total_open_accounts` | APPROXIMATED | Equifax CCR summary stats; distribution shape illustrative |
| `num_bnpl_accounts` | APPROXIMATED | ASIC BNPL Report 2023 prevalence; per-provider counts illustrative |

### Macroeconomic context (4)

| Feature | Grade | Source / rationale |
|---|---|---|
| `rba_cash_rate` | ANCHORED | Verbatim quarterly series 2023Q3–2026Q2 |
| `unemployment_rate` | ANCHORED | ABS Labour Force quarterly series over the same window |
| `property_growth_12m` | ANCHORED | CoreLogic / Cotality state-level year-on-year HPI |
| `consumer_confidence` | ANCHORED | Westpac-Melbourne Institute index (79.7 → 99.0) |

### Behavioural / Open Banking (6)

| Feature | Grade | Source / rationale |
|---|---|---|
| `is_existing_customer` | APPROXIMATED | Typical ADI portfolio mix (~35–40% existing); not from a cited figure |
| `savings_balance` | APPROXIMATED | ABS Household Saving Ratio implied stocks; individual-level distribution illustrative |
| `salary_credit_regularity` | APPROXIMATED | Correlated with employment-type in a plausible direction — no cited benchmark |
| `num_dishonours_12m` | APPROXIMATED | APCA direct-entry dishonour base rates used as base probability; individual tail illustrative |
| `avg_monthly_savings_rate` | APPROXIMATED | ABS Household Saving Ratio used as population mean; individual variance illustrative |
| `days_in_overdraft_12m` | APPROXIMATED | Typical retail-bank overdraft incidence; individual distribution illustrative |

### CDR / CCR enrichment (~14 — sampled, see `feature_generator.py`)

| Feature | Grade | Source / rationale |
|---|---|---|
| `gambling_transaction_flag`, `gambling_spend_ratio` | UNCITED | No anchored AU source for individual-level gambling spend. Distribution is illustrative and should not be used for real decisioning. |
| `optimism_bias_flag`, `financial_literacy_score` | UNCITED | Illustrative behavioural signals. Useful as model-capability demos; not calibrated. |
| `num_late_payments_24m`, `worst_late_payment_days`, `num_hardship_flags` | APPROXIMATED | CCR distributions consistent with Equifax aggregate stats but individual-level shapes are illustrative |
| `bnpl_utilization_pct`, `bnpl_late_payments_12m`, `bnpl_monthly_commitment` | APPROXIMATED | Derived from sampled BNPL balances + provider count; not from a cited dataset |
| `rent_payment_regularity`, `utility_payment_regularity` | APPROXIMATED | Typical CDR distribution shape from publicly-reported Open Banking aggregates |
| `essential_to_total_spend`, `subscription_burden` | APPROXIMATED | Plausible CDR aggregates — ABS HES 2015-16 spend shares cited as a sanity reference |

### Application integrity (2)

| Feature | Grade | Source / rationale |
|---|---|---|
| `income_verification_gap` | APPROXIMATED | Synthetic noise around the true income to simulate payslip-vs-declared mismatch |
| `document_consistency_score` | APPROXIMATED | Internally-consistent rule-based score from the integrity model |

### Underwriter policy variables (4)

These are the features that were the long-standing gap documented in
`project_v1_9_8_realism_audit` memory. They are now exposed to the model (see
`data_generator.py:1239-1242` and re-derivation at `1377-1387`), so the model
learns the same HEM-floor and LMI-capitalisation rules the underwriting engine
uses to derive the label.

| Feature | Grade | Source / rationale |
|---|---|---|
| `hem_benchmark` | ANCHORED | Melbourne Institute HEM 2025/2026, 50-cell lookup in `UnderwritingEngine.HEM_TABLE`, applicant-type × dependants(0–4) × income-bracket(5) with state multiplier |
| `hem_gap` | ANCHORED | `monthly_expenses − hem_benchmark`; surface of anchored HEM + declared expenses |
| `lmi_premium` | ANCHORED | 1% / 2% / 3% of loan amount at LVR bands 80 / 85 / 90 (`LMI_RATES` constant; in line with Genworth/QBE LMI rate cards) |
| `effective_loan_amount` | ANCHORED | `loan_amount + lmi_premium` (capitalised) — standard Big 4 practice |

### Geographic (3)

| Feature | Grade | Source / rationale |
|---|---|---|
| `state` | ANCHORED | ABS ERP shares by state |
| `sa3_region`, `sa3_name` | ANCHORED | Official ABS SA3 codes/names (ASGS 2021) |
| `postcode_default_rate` | APPROXIMATED | Noise std anchored (`rng.normal(0, 0.008)`, `data_generator.py:1097`, regression-guarded by `test_postcode_default_rate_correlation_realistic`); underlying per-postcode map is illustrative, not an actual Equifax postcode risk table |

## Known gaps

The model **does not** and should not be claimed to capture:

1. **Real post-origination behaviour.** The Markov-chain performance simulator
   is calibrated to RBA FSR headline arrears rates, but individual-level
   default trajectories are not from real borrower data.
2. **Survival / time-to-default.** The model makes a point-in-time prediction.
   No temporal default pattern is modelled; no hazard function is fit.
3. **Real credit bureau integration.** Bureau features (enquiries, arrears,
   defaults, BNPL accounts) are simulated, not sourced from Equifax or Illion.
4. **Postcode-level risk.** State-level granularity is honest; the
   `postcode_default_rate` column is illustrative and not a replacement for an
   actual postcode risk table.
5. **Co-borrower asymmetry.** Couple applicants are treated as a household
   income sum; the real-world divergence between co-borrower incomes /
   liabilities is flattened.
6. **Non-bank product mix.** Calibrated to ADI ("Big 4 + mid-tier") shapes.
   Non-bank lender distributions (FIIG, Liberty, Pepper) are not modelled.
7. **Discretionary expense shocks.** Household shocks (divorce, medical,
   child-support orders) are not surfaced as features beyond HEM-gap.
8. **Gambling spend.** No anchored AU source for individual-level gambling
   spend exists publicly; the flag is illustrative only.
9. **Financial literacy.** The `financial_literacy_score` signal is an
   illustrative demo feature and should not be used in real decisioning.
10. **Macroprudential response.** APRA DTI/LVR caps are applied as static
    thresholds. Dynamic macroprudential response (rate-cut-driven refi waves)
    is out of scope.

These gaps are not hidden — they are the main reason performance on real
borrower data is reported as **unvalidated** in the model card's Limitations
section.

## Recalibration triggers

The audit above is point-in-time. The following events should trigger a
re-grade of the affected rows:

- **New ABS Lending Indicators release** (quarterly) → re-check loan-amount
  means per sub-population.
- **New APRA Quarterly ADI Property Exposures** (quarterly) → re-check LVR and
  DTI band shares.
- **New RBA Financial Stability Review** (semi-annual) → re-check arrears mix.
- **New Equifax scorecard** (annual) → re-check `credit_score` state/age
  offsets.
- **New Melbourne Institute HEM release** (annual, CPI-indexed) → regenerate
  `HEM_TABLE` and re-run regression tests.
- **APRA macroprudential change** → update DTI/LVR thresholds in
  `UnderwritingEngine.compute_approval`.
- **New CoreLogic / Cotality median-price release** (monthly) → re-check
  `PropertyDataService` per-state medians.

Each trigger above is a one-line constant change plus a regression-test
refresh. Keeping this audit current is intentionally cheap so it can be done
during routine dependency bumps.

## Change history

| Date | Change |
|------|--------|
| 2026-04-20 | Initial audit. Grades captured against `data_generator.py` on master `7756761`, with HEM/LMI/effective-loan-amount now exposed as model features. Replaces the audit originally scoped in closed PR #93. |
