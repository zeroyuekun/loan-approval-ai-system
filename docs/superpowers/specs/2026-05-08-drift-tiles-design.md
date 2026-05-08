# Drift Tiles — Design

**Date**: 2026-05-08
**Status**: Approved (trust-delegated)
**Scope**: backend/apps/ml_engine — trainer hook + two management commands + tests + runbook

## Problem

The KPI strip on `/dashboard/model-metrics` displays four tiles: AUC-ROC, KS statistic, **PSI (latest)**, and **Approval rate**. The PSI and Approval rate tiles are blank ("—") on the active model `xgb v20260508_111850`. Investigation surfaced three independent gaps in the training → drift pipeline:

1. **No `PredictionLog` rows for the active model.** The active model has had zero predictions scored through it, so the recent-window query in `compute_weekly_drift_report` returns empty and the task short-circuits with `skipped: no_predictions`.
2. **`training_metadata.reference_probabilities` missing.** The simpler weekly drift task computes PSI by comparing recent prediction probabilities to a stored reference list. That list is not written by the current trainer, so even if predictions existed, PSI would be `None`.
3. **Bundle `reference_distribution` has the wrong shape.** The richer on-demand path (`compute_batch_drift_report` in `drift_monitor.py`) expects `reference_distribution.probability_distribution` (list of holdout probabilities) and optionally `reference_distribution.feature_distributions`. The current bundle stores per-feature value samples keyed by feature name (`annual_income`, `credit_score`, …) instead — a different shape that satisfies neither drift code path.

The two `DriftReport` paths are otherwise functional. The fix is to make models drift-ready at training time, backfill the currently-active model in place, and feed it a realistic synthetic prediction stream so the weekly task has something to compute against.

## Goal

PSI and Approval rate tiles populate with honest numbers derived from a real prediction stream, not seeded directly into a `DriftReport` row. The pipeline that produces those numbers stays correct for every future trained model without manual intervention.

## Approach

Three small, atomic deliverables plus one orchestration step. Frontend untouched.

1. **Trainer hook** — every newly trained model writes the data both drift code paths need.
2. **Backfill management command** — one-shot patch for the currently-active model (and any other models lacking the metadata).
3. **AU-realistic seed management command** — generates a synthetic but distributionally-honest prediction stream against the active model and triggers the drift task to produce a real `DriftReport` row.

## Architecture

```
Train New Model        ──► trainer hook captures holdout dists  ──► bundle + metadata always drift-ready
                                                                        │
For currently-active model (one-time):                                  │
   manage.py backfill_reference_distribution --all-active ──────────────┘
                                                                        │
   manage.py seed_predictions --model-id X --count 200 --trigger-drift  │
       │                                                                │
       ├─ DataGenerator (AU-calibrated) → 200 rows                      │
       ├─ ModelPredictor.predict() per row → 200 PredictionLog          │
       ├─ override created_at with weekday+evening-biased timestamps    │
       └─ compute_weekly_drift_report.apply() → DriftReport row ────────┘
                                                                        │
                                                                        ▼
   /dashboard/model-metrics → useDriftReports() → KpiStrip tiles populate
```

## Components

### 1. Trainer hook — `services/trainer.py`

Add a private helper `_capture_reference_distribution(holdout_probs, holdout_features) -> dict` and call it at the end of `_persist_model` (or wherever the bundle dict is assembled — locate the existing `reference_distribution` write site and extend, do not duplicate).

Behavior:

- Sample up to **1,000** holdout-set predicted probabilities. Use the full holdout if smaller.
- Capture per-feature holdout values for the model's input feature columns. Numeric features → list of float values. Categorical features → list of string values. Cap each list at 1,000 samples for bundle-size hygiene.
- Write to:
  - `bundle.reference_distribution.probability_distribution` (list[float])
  - `bundle.reference_distribution.feature_distributions` (dict[str, list])
  - `ModelVersion.training_metadata.reference_probabilities` (mirror of `probability_distribution`)
- Idempotent on retrain: each new training run replaces the values cleanly. Future re-saves overwrite without special handling.
- Failure mode: if holdout probabilities are unavailable for any reason, log a warning and continue. Drift readiness is opportunistic, not a training-blocker.

### 2. Backfill command — `management/commands/backfill_reference_distribution.py`

```
python manage.py backfill_reference_distribution
    [--model-id <uuid> | --all-active]
    [--sample 5000]
    [--force]
```

Behavior:

- Resolve target model(s). Default is `--all-active` (every `ModelVersion.is_active=True`).
- For each target:
  - Validate the bundle path with the existing `_validate_model_path()` security helper.
  - If `bundle.reference_distribution.probability_distribution` is already populated and `--force` is not set, log a refusal message and skip. Exit 0 (cron-friendly).
  - Generate a fresh `DataGenerator` batch of `--sample` rows (default 5,000) using the existing AU-calibrated defaults.
  - Run the loaded model on the batch to produce holdout-equivalent probabilities and feature samples.
  - Update bundle: write `probability_distribution`, `feature_distributions`, preserving any existing keys.
  - Update `ModelVersion.training_metadata['reference_probabilities']`.
  - Re-save bundle atomically (write to `<bundle>.tmp` → `os.replace`) so an interrupted run never leaves a corrupt bundle.
  - Save the `ModelVersion` row.

Logs the count of fields filled vs already-present.

### 3. Seed-predictions command — `management/commands/seed_predictions.py`

```
python manage.py seed_predictions
    --model-id <uuid>
    [--count 200]
    [--spread-days 7]
    [--seed <int>]
    [--trigger-drift / --no-trigger-drift]
```

Behavior:

- Validate args: `count ∈ [1, 10000]`, `spread-days ∈ [1, 90]`. argparse rejects out-of-range values before any DB write.
- Generate `--count` rows from `DataGenerator` with the project's existing AU-calibrated defaults. Distribution itself is unchanged — DataGenerator is already calibrated against ABS/APRA/RBA/HILDA.
- For each row, call `ModelPredictor.predict()` to produce a `PredictionLog`. Wrap the loop in `transaction.atomic` so a mid-loop failure rolls back cleanly.
- After all `PredictionLog` rows are inserted, set `instance.created_at` to a sampled timestamp on each row and issue a single `PredictionLog.objects.bulk_update(rows, ['created_at'])`. `bulk_update` overrides the `auto_now_add=True` default on the field. Sampling rules:
  - **Day-of-week weights** (sums to 100): Mon 13, Tue 22, Wed 22, Thu 18, Fri 12, Sat 8, Sun 5. Weekday-business heavy with a weekend tail — picked to look like an online consumer-lending traffic shape, not sourced from a specific lender's published data.
  - **Hour-of-day weights** (24-element vector, indices 0-23, normalised by sampler): `[1, 1, 1, 1, 1, 1, 2, 3, 5, 6, 5, 4, 4, 4, 4, 4, 5, 6, 8, 9, 9, 7, 4, 2]`. Bimodal — small commute-time peak around 8-10am, larger post-work peak around 6-9pm, quiet overnight.
  - All sampling uses `random.Random(seed)` so `--seed` makes the run reproducible (tests use a fixed seed to assert exact distributions, no chi-square flake).
- If `--trigger-drift` (default true): call `compute_weekly_drift_report.apply()` synchronously and log the resulting `DriftReport.id`, `psi_score`, `approval_rate`.

### 4. Drift trigger

No standalone component — wired into `seed_predictions --trigger-drift`. The trigger uses `apply()` (not `delay()`) so the command's output reports the actual outcome.

## Data flow

The flow is described in the architecture diagram above. Key invariants:

- `PredictionLog.created_at` always lies inside `[now - spread_days, now]` so the weekly task's recent-window filter accepts every seeded row.
- `DriftReport.psi_score` is non-null when:
  - `training_metadata.reference_probabilities` exists (provided by trainer hook or backfill), AND
  - At least one `PredictionLog` row exists in the recent window (provided by seed command).
- `DriftReport.approval_rate` is non-null when at least one `PredictionLog` row exists in the recent window. It does not depend on reference data.

## Error handling

| Component | Failure mode | Behavior |
|---|---|---|
| Trainer hook | Holdout probs unavailable / smaller than 1,000 | Log + use whatever is available. Never raise. |
| Trainer hook | Bundle write fails | Existing `_persist_model` already raises — additive code does not change that path. |
| Backfill cmd | Bundle path invalid | `_validate_model_path` raises; command exits non-zero with clear message. |
| Backfill cmd | Fields already present, no `--force` | Refuse with stderr message; exit 0 (cron-friendly). |
| Backfill cmd | Re-save fails mid-write | Atomic rename pattern protects the original bundle. |
| Seed cmd | `count`/`spread-days` out of range | argparse rejects before any DB write. |
| Seed cmd | `ModelPredictor.predict()` raises mid-loop | `transaction.atomic` rolls back; no partial `PredictionLog` state. |
| Drift trigger | `no_predictions` skip path | Existing task already handles; command surfaces the skip reason. |

## Testing

- `backend/tests/test_trainer_reference_distribution.py` — fits a tiny model on 50 rows, asserts both bundle keys + `training_metadata.reference_probabilities` populated, asserts list length ≤ 1,000.
- `backend/tests/test_backfill_reference_distribution.py` — stub `ModelVersion` + bundle, run command, assert fields filled, assert second invocation refuses without `--force`, assert `--force` overwrites.
- `backend/tests/test_seed_predictions.py` — assert N rows created, all with matching `model_version`, timestamps inside `[now - spread_days, now]`. With `--seed 42` and `--count 200`, assert the exact day-of-week count distribution (deterministic, no chi-square flake).
- `backend/tests/test_drift_pipeline_integration.py` — end-to-end: tiny model → backfill → seed 30 → drift task → assert `DriftReport` row exists with non-null `psi_score` and `approval_rate`.
- Manual verification: reload `localhost:3000/dashboard/model-metrics`. PSI and Approval rate tiles render numbers; AUC and KS unchanged.

## File touch list

- MODIFY `backend/apps/ml_engine/services/trainer.py` — add `_capture_reference_distribution()`, call from `_persist_model`.
- NEW `backend/apps/ml_engine/management/commands/backfill_reference_distribution.py`.
- NEW `backend/apps/ml_engine/management/commands/seed_predictions.py`.
- NEW `backend/tests/test_trainer_reference_distribution.py`.
- NEW `backend/tests/test_backfill_reference_distribution.py`.
- NEW `backend/tests/test_seed_predictions.py`.
- NEW `backend/tests/test_drift_pipeline_integration.py`.
- MODIFY `backend/docs/RUNBOOK.md` — append "Initial drift seed for new model deployments" section (~15 lines).

## Out of scope (deliberately deferred)

- Refactoring duplicate PSI logic between `tasks.py::compute_weekly_drift_report` and `drift_monitor.py::compute_batch_drift_report`. Both code paths exist and the trainer hook makes both work; consolidating them is a separate follow-up issue.
- Frontend changes to `KpiStrip`. No edits required — tiles already read `latestDrift.psi_score` and `latestDrift.approval_rate`.
- Admin-facing "Re-seed predictions" button on the dashboard. Management commands are the right primitive for one-shot operational tasks; UI surface can come later if the demo needs frequent re-seeding.
- Refining temporal weights against a specific named AU lender's quarterly traffic data. The weights chosen match generic online-consumer-lending shape; revisable if a citation surfaces.
