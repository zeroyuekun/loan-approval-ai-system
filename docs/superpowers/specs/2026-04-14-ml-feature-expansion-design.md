# ML Feature Expansion — Design (revised)

**Date:** 2026-04-14
**Sub-project:** B (of A→B→C sequence)
**Depends on:** `docs/research/findings.json` from sub-project A
**Feeds:** Sub-project C (stress testing the regenerated pipeline; surfacing new features in UI/email)
**Out of scope:** Policy rules (age-at-maturity cap, visa eligibility gate), real-data GMSC validation (in-flight on a separate branch), frontend/email changes, stress testing.

## Revision note (2026-04-14)

The initial design named four features (`bnpl_balance`, `savings_balance_months`, `rhi_on_time_last_24`/`rhi_late_last_24`, `enquiries_last_6_months`). Inspection of `backend/apps/ml_engine/services/data_generator.py` shows three of those already exist in richer form:

- BNPL already covered by `num_bnpl_accounts`, `bnpl_total_limit`, `bnpl_utilization_pct`, `bnpl_late_payments_12m`, `bnpl_monthly_commitment`, `bnpl_to_income_ratio`.
- Savings already covered by `savings_balance`, `avg_monthly_savings_rate`, `savings_trend_3m`, `savings_to_loan_ratio`.
- Windowed enquiries already covered by `num_credit_enquiries_6m`.

The genuinely missing feature is the 24-month Repayment History Information (RHI) split. The current generator produces `worst_arrears_months` and `worst_late_payment_days` but no month-by-month RHI counts. Sub-project B is reduced to adding that plus a coverage audit so the research gap list stays honest.

## Goal

Add one research-backed feature (`rhi_on_time_last_24` / `rhi_late_last_24`) to the synthetic loan data generator, train a new `ModelVersion` on the regenerated dataset, and gate promotion of the new model behind an A/B metric check so the current active model remains a one-flag rollback. Additionally, publish an audit document that maps every research-identified gap to either an existing generator field or an explicit "deferred" note.

## Feature specification

### `rhi_on_time_last_24` and `rhi_late_last_24` (ints)

- Joint constraint: `rhi_on_time_last_24 + rhi_late_last_24 = 24`
- Derived from existing `worst_arrears_months`:
  - If `worst_arrears_months == 0`: `rhi_on_time = 24, rhi_late = 0` with probability 0.98; otherwise sample `rhi_late` from `{1, 2}` with probability 0.015 and 0.005 respectively (captures the small fraction of customers whose worst month is 0 but who had isolated late months beyond the worst-window logic — matches AU bank observed behaviour)
  - If `worst_arrears_months >= 1`: sample `rhi_late` from a truncated geometric distribution with mean scaled linearly by `worst_arrears_months` (mean ≈ 1.5 × `worst_arrears_months`, capped at 24)
- Strong positive correlation of `rhi_on_time_last_24` with `credit_score` (already present indirectly via `worst_arrears_months`, preserved)
- Both features are additive signal beyond `worst_arrears_months`: two applicants with the same worst-arrears value can have different late-month counts

## Coverage audit

Create `docs/research/ml-gap-coverage.md` that maps each item in `findings.json#/consolidated/gaps_in_our_model` to one of:

- **Covered:** existing field name(s) in the generator; cite line number
- **Adding now:** the two RHI features above
- **Deferred:** named with reason (e.g. `age_at_loan_maturity` → "policy rule, not ML feature; deferred per sub-project B spec")

This document is the honest record that sub-project A's gap analysis was name-based rather than semantic, and that most perceived gaps are already covered.

## Pipeline changes

### `backend/apps/ml_engine/services/data_generator.py`

- Add generator logic for `rhi_on_time_last_24` and `rhi_late_last_24` following existing patterns (reuse the `rng` already threaded through record generation; place the block near the existing `worst_arrears_months` generation to keep semantically related fields colocated)
- Append both new columns to the returned records dict
- Add a module-level `DATA_SCHEMA_VERSION = "2026-04-14-v2"` constant; update any metadata return path that surfaces the schema
- Update module docstring with the two new features and cite `docs/research/findings.json`

### Training

- `backend/apps/ml_engine/services/trainer.py` needs the new columns in its feature allow-list (if any exists). Inspect for `FEATURE_COLUMNS`, `feature_columns`, or equivalent; if present, extend it. If absent, the generator output flows through automatically.
- Train a new `ModelVersion` with `name` tagged `"rf-v2-au-rhi-2026-04-14"` (or `"xgb-v2-au-rhi-2026-04-14"` if XGBoost is currently `is_active`). Create it with `is_active=False`.
- Use the existing persistence and artefact conventions with no changes.

### Reason codes

- `backend/apps/ml_engine/services/reason_codes.py`: add mappings for `rhi_on_time_last_24` and `rhi_late_last_24` so they can appear in adverse-action explanations. Follow existing phrasing conventions (no apology language; plain English per memory). Example phrasing: "Fewer on-time repayments in your 24-month credit history than peers approved at similar rates."

## A/B promotion gate

After training the new model, compute on the held-out test set:

- AUC-ROC
- Precision at 10% approval rate
- Recall at 10% approval rate
- Calibration (Brier score; ECE as secondary)

**Promotion rule:** new version flips `is_active=True` only if:

1. New version wins on ≥2 of {AUC, Precision@10%, Recall@10%} vs current active version, AND
2. Calibration (Brier score) does not regress by more than 5% relative

If either condition fails, new version stays `is_active=False` and is diagnosed in a follow-up. Old version is untouched — instant rollback by design.

Comparison and promotion are two explicit management commands (`ab_compare_models` and `promote_model`) so a human sign-off stays in the loop.

## Testing

- **Unit tests for the new features:**
  - Distribution sanity: for `worst_arrears_months == 0` inputs, `rhi_on_time == 24` at ≥97% rate
  - Invariant: `rhi_on_time_last_24 + rhi_late_last_24 == 24` for every row
  - Bounds: both values in `[0, 24]`
  - Correlation sign: `rhi_on_time_last_24` positively correlated with `credit_score` at Pearson ρ > 0.1
- **Schema regression test:** all pre-existing columns present; a spot-check (mean/median) of a couple of existing features unchanged within tolerance
- **Smoke train test:** run trainer on 1,000 generated rows end-to-end before full generation
- **A/B promotion-gate unit test:** exercise the gate logic against synthetic metric inputs covering win/lose/tie combinations

## Success criteria

- Generator outputs both new features with documented distributions and invariants
- `DATA_SCHEMA_VERSION` bumped to `"2026-04-14-v2"`
- Coverage audit `docs/research/ml-gap-coverage.md` committed
- New `ModelVersion` trained and persisted with `is_active=False`
- `ab_compare_models` command produces a metric table and proposes a decision
- `promote_model` command flips `is_active` only when called explicitly by a human
- All new unit tests pass; no existing tests regress
- Rollback path verified manually

## Deliverables

- Modified: `backend/apps/ml_engine/services/data_generator.py`
- Modified: `backend/apps/ml_engine/services/trainer.py` (only if feature allow-list needs extending)
- Modified: `backend/apps/ml_engine/services/reason_codes.py`
- Created: `backend/apps/ml_engine/management/commands/ab_compare_models.py`
- Created: `backend/apps/ml_engine/management/commands/promote_model.py`
- Created: tests covering the two new features, invariants, schema regression, and promotion-gate logic
- Created: `docs/research/ml-gap-coverage.md`
