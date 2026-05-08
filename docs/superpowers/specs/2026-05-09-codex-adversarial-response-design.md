# Codex Adversarial Review Response — Design

**Date**: 2026-05-09
**Status**: Approved (trust-delegated, scope chosen by implementer)
**Scope**: backend `ml_engine` (dossier + trainer + settings + tests) + `frontend/next-env.d.ts` revert + RUNBOOK addendum

## Problem

Codex's adversarial review of the working tree returned `verdict=needs-attention` with three findings:

1. **[high]** Active model `1c21d19b-f1a9-43ce-a115-fdef602d410d` (xgb v20260508_174941) is marked `Active: True` and `Compliance status: NON-COMPLIANT` (fairness 80%-rule fails on `state` and `employment_type`), while the deployment runs the policy overlay in `shadow` mode where out-of-scope predictions are *not blocked*. The gate machinery exists but defaults to advisory rather than enforcement.
2. **[high]** The dossier for the same active model says decile calibration was not recorded and no PSI-by-feature data exists. For an active credit model that leaves no concrete evidence of probability calibration or train/test drift before rollout.
3. **[medium]** `frontend/next-env.d.ts` was hand-edited to import from `./.next/dev/types/routes.d.ts`, a dev-build-tree-specific path that may not exist in CI / production builds.

Investigation confirmed the findings are real but more nuanced than Codex framed them:

- **Finding #2 calibration sub-finding is a dossier bug, not a data bug.** `mrm_dossier.py:233` reads `mv.calibration_data["deciles"]`, but deciles actually live at the separate `mv.decile_analysis["deciles"]` JSONField. The DB confirms `mv.decile_analysis.deciles` has 10 entries for the active model. The trainer is correct; the dossier path is wrong.
- **Finding #2 PSI sub-finding is a mirror bug.** `trainer.py:952` writes `metrics["psi_by_feature"]` at the top level of the metrics dict, but the dossier reads `mv.training_metadata["psi_by_feature"]`. `tasks.py:149` populates `training_metadata=metrics.get("training_metadata", {})` — the top-level `psi_by_feature` is dropped on the floor before it reaches the DB. Same shape of bug we fixed for `reference_probabilities` in Task 4 of `2026-05-08-drift-tiles-design.md`.
- **Finding #1 is real**: `backend/config/settings/base.py:241,252,263` defaults all three gate modes to advisory (`shadow` for `CREDIT_POLICY_OVERLAY_MODE`, `warn` for `ML_FAIRNESS_GATE_MODE` and `ML_PROMOTION_GATE_MODE`). The non-compliant model passed activation because nothing was set to refuse it.
- **Finding #3 is real and trivial**: pre-existing local WIP, unrelated to any feature work, easy to revert.

## Goal

Close all three Codex findings without breaking existing flows. After this work:

- Newly trained models that fail fairness or promotion gates **block** activation by default rather than silently activating with a warning.
- Out-of-scope predictions are **enforced** by the policy overlay rather than observed in shadow.
- The dossier accurately reports calibration deciles + per-feature PSI when the underlying data exists.
- The active model `1c21d19b...` has its `training_metadata.psi_by_feature` backfilled so its dossier renders correctly without forcing a retrain.
- `frontend/next-env.d.ts` matches what Next.js regenerates from a clean checkout.

The currently-active non-compliant model is **not auto-demoted**. Surfacing the issue clearly via the now-correct dossier + new strict defaults gives the operator a deliberate decision: re-train (next training run will be blocked from activation if still non-compliant) or manually deactivate via Django admin. Auto-demotion is destructive and exceeds the scope of "fix Codex findings".

## Approach

Seven deliverables organised by component. Each is a small atomic commit. Frontend touches are limited to one file revert.

1. **Dossier path fix** — `mrm_dossier.py` reads deciles from `mv.decile_analysis["deciles"]` (the correct JSONField) instead of `mv.calibration_data["deciles"]`.
2. **Trainer PSI mirror** — `trainer.py` writes `psi_by_feature` into `metrics["training_metadata"]` so it propagates to `ModelVersion.training_metadata` via the existing `tasks.py:149` path.
3. **Active-model backfill** — small management command `backfill_psi_by_feature` that recomputes `psi_by_feature` for any `is_active=True` ModelVersion missing the field, by loading the bundle, generating a fresh DataGenerator batch, and computing PSI between training reference and the new batch. Idempotent.
4. **Strict gate defaults** — `config/settings/base.py` defaults `ML_FAIRNESS_GATE_MODE`, `ML_PROMOTION_GATE_MODE` to `block` and `CREDIT_POLICY_OVERLAY_MODE` to `enforce`. Existing env-var override behaviour is preserved.
5. **`next-env.d.ts` revert** — revert to the standard Next-generated content (`/// <reference types="next" />`, `/// <reference types="next/image-types/global" />`, `import "./.next/types/routes.d.ts";`, no edits).
6. **RUNBOOK addendum** — document the new strict defaults, when/how to set the env vars to relax to `warn`/`shadow` for emergency rollback, and the operator playbook for what to do when a fairness gate refuses activation (re-train with adjusted features, or skip activation, or override per-incident).
7. **Tests** — covers (a) dossier rendering against a ModelVersion with deciles + psi_by_feature populated, (b) trainer writes `training_metadata.psi_by_feature` on training, (c) backfill command populates the field idempotently, (d) settings default to strict gate modes, (e) regression: existing fairness-gate `block` rejection path still raises and surfaces the failure reason cleanly.

## Components

### 1. Dossier path fix

**File**: `backend/apps/ml_engine/services/mrm_dossier.py:231-238`

Current:

```python
def _calibration_section(mv) -> str:
    """§6 — Calibration report (decile table)."""
    calibration = mv.calibration_data or {}
    deciles = calibration.get("deciles") or calibration.get("decile_analysis") or []
    if not deciles:
        return (
            "## 6. Calibration report\n\n"
            "Decile calibration not recorded. Re-train with v1.9.0+ trainer which "
            "emits `calibration_data.deciles` on every run."
        )
```

Replacement: read deciles from `mv.decile_analysis` (the separate JSONField), keeping the existing fallback for legacy bundles that stored deciles inside `calibration_data`. The existing fallback ordering matters — preserve it.

```python
def _calibration_section(mv) -> str:
    """§6 — Calibration report (decile table)."""
    decile_analysis = mv.decile_analysis or {}
    calibration = mv.calibration_data or {}
    deciles = (
        decile_analysis.get("deciles")
        or calibration.get("deciles")
        or calibration.get("decile_analysis")
        or []
    )
    if not deciles:
        return (
            "## 6. Calibration report\n\n"
            "Decile calibration not recorded. Re-train with v1.9.0+ trainer which "
            "emits `decile_analysis.deciles` on every run."
        )
```

The change is one line plus updating the empty-state message to reflect the canonical path.

### 2. Trainer PSI mirror

**File**: `backend/apps/ml_engine/services/trainer.py:945-953`

Current trainer block (around the `psi_by_feature` write):

```python
try:
    metrics["psi_by_feature"] = psi_by_feature(
        X_train if isinstance(X_train, pd.DataFrame) else pd.DataFrame(X_train, columns=feature_cols),
        X_test if isinstance(X_test, pd.DataFrame) else pd.DataFrame(X_test, columns=feature_cols),
        feature_cols,
    )
except Exception as _psi_exc:
    logger.warning("psi_by_feature computation failed: %s", _psi_exc)
    metrics["psi_by_feature"] = {}
```

Augment the `metrics["training_metadata"] = { ... }` block (around line 986-1014) to mirror the value into `training_metadata`:

Find the line `"reference_probabilities": list(...),` and insert immediately before it:

```python
"psi_by_feature": dict(metrics.get("psi_by_feature") or {}),
```

This keeps the top-level metrics["psi_by_feature"] write site untouched (other consumers may rely on it) and adds a mirror under `training_metadata` for the dossier.

### 3. `backfill_psi_by_feature` management command

**File (new)**: `backend/apps/ml_engine/management/commands/backfill_psi_by_feature.py`

Args:

```
python manage.py backfill_psi_by_feature
    [--model-id <uuid> | --all-active]
    [--sample 5000]
    [--force]
```

Behavior:

- Resolve target model(s). Default `--all-active`.
- Skip targets whose `training_metadata.psi_by_feature` is already populated unless `--force`.
- For each target:
  - Load bundle via `_validate_model_path` + `joblib.load`.
  - Generate a fresh `DataGenerator` batch of `--sample` rows.
  - Apply `predictor._transform` to get the engineered DataFrame in the same shape the trainer used (mirrors the pattern from `backfill_reference_distribution`).
  - Use the bundle's stored `reference_distribution.feature_distributions` (populated by Task 3 of `2026-05-08-drift-tiles-design.md`) as the "train" side. Use the engineered DataGenerator output as the "test" side.
  - Call `psi_by_feature(train_df, test_df, feature_cols)` (the existing helper in `apps.ml_engine.services.metrics`).
  - Write the resulting dict into `mv.training_metadata["psi_by_feature"]` with `mv.save(update_fields=["training_metadata"])`.
- Refuses to overwrite without `--force`.

### 4. Strict gate defaults

**File**: `backend/config/settings/base.py:241,252,263`

Three single-line edits:

```python
CREDIT_POLICY_OVERLAY_MODE = os.environ.get("CREDIT_POLICY_OVERLAY_MODE", "enforce")
...
ML_FAIRNESS_GATE_MODE = os.environ.get("ML_FAIRNESS_GATE_MODE", "block")
...
ML_PROMOTION_GATE_MODE = os.environ.get("ML_PROMOTION_GATE_MODE", "block")
```

Existing env-var override semantics are preserved — operators can set `ML_FAIRNESS_GATE_MODE=warn` in `.env` to relax for emergency rollback. The change is the safe default, not the locked-down behaviour.

### 5. `next-env.d.ts` revert

**File**: `frontend/next-env.d.ts`

Restore to the master content:

```typescript
/// <reference types="next" />
/// <reference types="next/image-types/global" />
import "./.next/types/routes.d.ts";

// NOTE: This file should not be edited
// see https://nextjs.org/docs/basic-features/typescript for more information.
```

The dev-only `./.next/dev/types/routes.d.ts` import path is dropped. Next.js regenerates this file on every dev / build run; the committed copy is the standard auto-generated content.

### 6. RUNBOOK addendum

**File**: `backend/docs/RUNBOOK.md` (append a new section)

New section: `## Strict gate defaults — when and how to relax`. Documents:

- The three env-var defaults flipped from advisory → enforcement.
- What "fairness gate refuses activation" looks like operationally (training task raises `FairnessGateBlocked`; old segment model stays active).
- Emergency rollback: `ML_FAIRNESS_GATE_MODE=warn` in `.env` + service restart.
- Decision tree when a real fairness violation surfaces: re-train with adjusted feature engineering / re-bin / etc, or accept the violation with explicit operator sign-off and flip to `warn` for one training run.
- Pointer to existing `2026-05-07-ml-fairness-gate-mode-design.md` for the underlying gate machinery.

### 7. Tests

- `backend/tests/test_mrm_dossier_calibration.py` — unit test that builds a stub ModelVersion with `decile_analysis.deciles` populated and asserts the dossier renders the calibration table (not the "not recorded" empty-state).
- `backend/tests/test_trainer_psi_mirror.py` — unit test that builds a synthetic training run and asserts `metrics["training_metadata"]["psi_by_feature"]` is populated with the same keys as `metrics["psi_by_feature"]`.
- `backend/tests/test_backfill_psi_by_feature.py` — three tests: populates_missing, refuses_without_force_when_present, force_overwrites (mirrors the structure of `test_backfill_reference_distribution.py`).
- `backend/tests/test_settings_strict_gate_defaults.py` — asserts `settings.ML_FAIRNESS_GATE_MODE == "block"`, `settings.ML_PROMOTION_GATE_MODE == "block"`, `settings.CREDIT_POLICY_OVERLAY_MODE == "enforce"` when no env vars set.
- Regression: confirm the existing `test_fairness_gate_block_mode` style test still passes (the gate logic itself is unchanged; only the default mode changes).

## Data flow

The trainer pipeline is unchanged at the metric-computation level; only the metadata mirror is added:

```
trainer.train() ──► metrics dict
                       ├─ "psi_by_feature": <dict>            (top-level, unchanged)
                       └─ "training_metadata": {
                            ...,
                            "psi_by_feature": <dict>          (NEW mirror, this PR)
                            ...
                          }
                       │
                       ▼
                 tasks.py:149 → ModelVersion.training_metadata = metrics["training_metadata"]
                       │
                       ▼
                 mrm_dossier.py:_psi_section() reads training_metadata.psi_by_feature → renders table
```

Backfill command operates on existing rows that lack the mirror — it computes PSI from the bundle's stored reference distribution + a fresh DataGenerator batch, writes into the same `training_metadata.psi_by_feature` slot.

## Error handling

| Component | Failure mode | Behavior |
|---|---|---|
| Dossier path fix | `mv.decile_analysis` is None or empty dict | Existing fallback chain still applies; empty-state line renders. No new exception path. |
| Trainer PSI mirror | `metrics["psi_by_feature"]` missing | `dict(metrics.get("psi_by_feature") or {})` → empty dict mirrored. Non-blocking. |
| Backfill cmd | Bundle path invalid | Existing `_validate_model_path` raises; command exits non-zero with clear message. |
| Backfill cmd | Field already populated, no `--force` | Refuse with stderr message; exit 0 (cron-friendly). |
| Backfill cmd | `psi_by_feature` computation fails (e.g., feature shape drift) | `try/except`, log warning, write empty dict, exit 0. Drift-readiness is opportunistic. |
| Strict defaults | New training fails fairness gate after deploy | Existing `FairnessGateBlocked` exception raises; outer training task wrapper releases the lock; old segment model stays active. Operator sees the failure in Celery logs + flower. |
| `next-env.d.ts` revert | None — pure file revert | n/a |

## Testing

- `pytest backend/tests/test_mrm_dossier_calibration.py -v` → asserts dossier reads from `decile_analysis`.
- `pytest backend/tests/test_trainer_psi_mirror.py -v` → asserts mirror is written.
- `pytest backend/tests/test_backfill_psi_by_feature.py -v` → 3/3 idempotency tests pass.
- `pytest backend/tests/test_settings_strict_gate_defaults.py -v` → settings default assertions.
- Manual: `python manage.py backfill_psi_by_feature --all-active` against the live `1c21d19b` model populates `training_metadata.psi_by_feature` with non-empty keys; re-running without `--force` skips; with `--force` overwrites.
- Manual: regenerate the dossier for the active model (`python manage.py generate_mrm_dossier --model-id 1c21d19b...`) — verify §6 Calibration and §7 PSI sections render real tables, not "not recorded" stubs.
- Manual: `npm run build` in `frontend/` from a clean checkout (after the revert) succeeds; typecheck passes.

## File touch list

- MODIFY `backend/apps/ml_engine/services/mrm_dossier.py` (calibration section path fix).
- MODIFY `backend/apps/ml_engine/services/trainer.py` (psi_by_feature mirror in training_metadata block).
- NEW `backend/apps/ml_engine/management/commands/backfill_psi_by_feature.py`.
- MODIFY `backend/config/settings/base.py` (3 default flips: shadow→enforce, warn→block, warn→block).
- MODIFY `frontend/next-env.d.ts` (revert).
- MODIFY `backend/docs/RUNBOOK.md` (append "Strict gate defaults" section).
- NEW `backend/tests/test_mrm_dossier_calibration.py`.
- NEW `backend/tests/test_trainer_psi_mirror.py`.
- NEW `backend/tests/test_backfill_psi_by_feature.py`.
- NEW `backend/tests/test_settings_strict_gate_defaults.py`.

## Out of scope

- **Auto-demotion of the current non-compliant `1c21d19b` active model.** Destructive; user decides via re-train or admin. Surfacing-only is the contract here.
- **Runtime check that prevents inference on a non-compliant active model.** Affects the prediction path; bigger blast radius. File as follow-up if desired.
- **Refactoring duplicate gate-mode env-var reads** (multiple files use `getattr(settings, "ML_FAIRNESS_GATE_MODE", "warn")` patterns). Mechanical change; orthogonal.
- **Re-running the GMSC benchmark** to confirm no regression after the gate-mode flip. The flip is pure config; no model behaviour changes.
- **Codex-flagged "Block activation of models that do not emit calibration deciles and PSI metrics"**: the trainer already always emits these (Task 4 of drift-tiles + this PR's mirror). Adding a *block-on-missing-evidence* enforcement check is YAGNI given the data is now reliably present. File as follow-up if desired.
