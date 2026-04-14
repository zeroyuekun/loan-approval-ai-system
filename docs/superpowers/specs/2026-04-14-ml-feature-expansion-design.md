# ML Feature Expansion — Design

**Date:** 2026-04-14
**Sub-project:** B (of A→B→C sequence)
**Depends on:** `docs/research/findings.json` from sub-project A
**Feeds:** Sub-project C (stress testing the regenerated pipeline; surfacing new features in UI/email)
**Out of scope:** Policy rules (age-at-maturity cap, visa eligibility gate), real-data GMSC validation (in-flight on a separate branch), frontend/email changes, stress testing.

## Goal

Add four research-backed features to the synthetic loan data generator, train a new `ModelVersion` on the regenerated dataset, and gate promotion of the new model behind an A/B metric check so the current active model remains a one-flag rollback.

## Why these four

From `docs/research/findings.json` consolidated `gaps_in_our_model`, these are the highest leverage and lowest complexity:

- `bnpl_balance` — Wisr explicitly lists BNPL as a first-class debt input; post-2019 AU norm
- `savings_balance_months` — Canstar names savings history as a denial signal
- `rhi_on_time_last_24` and `rhi_late_last_24` — CBA, NAB, Wisr, Plenti all drive pricing off 24-month RHI
- `enquiries_last_6_months` — Canstar flags short-window application clustering; our current `enquiries` is total-only

Deferred (policy-logic-heavy or low base rate): visa sub-class, self-employed trading years, financial-hardship flag, age-at-maturity, soft-pull indicator.

## Feature specifications

### `bnpl_balance` (float, AUD)

- Zero-inflated: `P(bnpl_balance = 0) = 0.50` overall; drops to 0.30 for age < 30, rises to 0.75 for age ≥ 55
- When non-zero: lognormal, median ~$800, p95 ~$4,500, clipped to [50, 15000]
- Inverse correlation with `credit_score`: higher utilisation among mid-tier scores
- Stays as a standalone feature for the model; does not mutate existing `debt_to_income`

### `savings_balance_months` (float)

- Definition: months of current `monthly_expenses` held as liquid savings
- Lognormal, median 1.5, p95 ~12, clipped to [0, 60]
- Positive correlation with `annual_income` (log-log) and with age_proxy
- `first_home_buyer` sub-population skews higher (median 3.5) reflecting deposit accumulation
- `income_constrained` sub-population skews lower (median 0.5)

### `rhi_on_time_last_24` and `rhi_late_last_24` (ints)

- Joint constraint: `rhi_on_time_last_24 + rhi_late_last_24 = 24` (full RHI window coverage; missing-months modelling is out of scope)
- Derived from existing `worst_arrears_months`: applicants with `worst_arrears_months = 0` get `rhi_on_time = 24, rhi_late = 0` with 0.98 probability; otherwise `rhi_late` sampled from a truncated geometric weighted by `worst_arrears_months`
- Strong positive correlation of `rhi_on_time_last_24` with `credit_score`
- Both features are additive, not a pure restatement of `worst_arrears_months` — two applicants with the same worst-month can have different late-month counts

### `enquiries_last_6_months` (int)

- Drawn from the existing aggregated enquiries column (inspect the generator and use the actual column name) by a binomial split with recency-weighted `p`
- `p = 0.55` default, rises to 0.75 for applicants with `credit_score` < 500 (clustering behaviour)
- Result is `<=` the parent enquiry count, enforced as an invariant in a post-generation validation step

## Pipeline changes

### `backend/apps/ml_engine/services/data_generator.py`

- Add four feature generators following existing patterns (reuse the `rng` passed into record generation; plumb through the existing copula/correlation machinery where it fits)
- Append new columns to the returned records
- Add a module-level `DATA_SCHEMA_VERSION` string (e.g. `"2026-04-14-v2"`) and include it in generator metadata
- Update module docstring with an index of features and their provenance (cite `docs/research/findings.json`)

### Training

- `backend/apps/ml_engine/services/trainer.py` should not need behavioural changes — it reads columns from the generated dataset. Verify the feature allow-list (if any) picks up the four new columns; extend if needed.
- Train a new `ModelVersion` with `name="rf-v2-au-features-2026-04-14"` (or equivalent for whichever algorithm is currently `is_active`). Create it with `is_active=False`.
- Artefacts (serialised model, calibration, SHAP summary) written using the existing persistence convention; no change to serialisation format.

### Reason codes

- `backend/apps/ml_engine/services/reason_codes.py`: add mappings so the four new features can appear in adverse-action explanations. Follow the existing phrasing conventions (no apology language; plain English per memory).

## A/B promotion gate

After training the new model, compute on a held-out test set (use the existing test-split convention):

- AUC-ROC
- Precision at 10% approval rate
- Recall at 10% approval rate
- Calibration (Brier score; ECE as secondary)

**Promotion rule:** new version flips `is_active=True` only if:

1. New version wins on ≥2 of {AUC, Precision@10%, Recall@10%} vs current active version, AND
2. Calibration (Brier score) does not regress by more than 5% relative

If either condition fails, new version stays `is_active=False` and is diagnosed in a follow-up. Old version is untouched — instant rollback by design.

The comparison is executed by an explicit management command (`ab_compare_models`), not implicitly at training time. The command prints the metric table and proposes the promotion decision; promotion is executed by a second explicit command (`promote_model`) so a human sign-off remains in the loop.

## Testing

- **Unit tests per feature:** distribution sanity (mean/median in expected range, null rate 0, min/max bounds respected, invariants like `rhi_on_time + rhi_late = 24` and `enquiries_last_6m <= total_enquiries`)
- **Schema regression test:** existing columns present and distributions unchanged within a tolerance — guards against accidentally mutating existing features
- **Smoke train test:** run trainer on 1,000 generated rows end-to-end before full generation, to catch schema/name mismatches cheaply
- **A/B metric test:** unit-test the promotion-gate logic against synthetic metric inputs (win/lose/tie combinations)

## Success criteria

- Data generator outputs the four new features with documented distributions
- `DATA_SCHEMA_VERSION` bumped
- New `ModelVersion` trained and persisted with `is_active=False`
- `ab_compare_models` command produces a metric table and promotion decision
- All new unit tests pass
- No existing tests regress
- Rollback path verified: manually flipping `is_active` back to the previous version works end-to-end

## Deliverables

- Modified: `backend/apps/ml_engine/services/data_generator.py`
- Modified: `backend/apps/ml_engine/services/trainer.py` (only if feature allow-list needs extending)
- Modified: `backend/apps/ml_engine/services/reason_codes.py`
- Created: `backend/apps/ml_engine/management/commands/ab_compare_models.py`
- Created: `backend/apps/ml_engine/management/commands/promote_model.py`
- Created: tests under `backend/apps/ml_engine/tests/` covering the four features, invariants, schema regression, and promotion-gate logic
