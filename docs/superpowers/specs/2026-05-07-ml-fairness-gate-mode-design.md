# ML Fairness Gate Mode — runtime activation gating

**Date:** 2026-05-07
**Status:** Approved design, pending implementation plan
**Scope:** Phase 1 of the runtime gating work deferred from PR #162. Adds an opt-in `ML_FAIRNESS_GATE_MODE` setting that lets operators choose whether failed fairness gates are merely logged (current default) or actively block model activation. Phases 2 (champion-challenger gate wiring) and 3 (`CREDIT_POLICY_OVERLAY_MODE` default change) are out of scope and tracked separately.

## Context

PR #162 made the MRM dossier honest about fairness-gate failures (the §1 Header now banners NON-COMPLIANT). It deliberately did not touch the runtime activation path, where `tasks.py:121-138` runs the fairness gate **after** the new model is already active and only logs a warning on failure ("Model remains active but flagged for human review.").

This spec adds the lever to make that warning a hard block — without changing default behaviour. The `warn` mode default ships byte-identical behaviour to today's deployment; operators flip to `block` only when they have validated their training pipeline produces compliant fairness metrics for the segments they care about.

## Constraints (carried over from the parent brainstorm)

- **No retroactive deactivation.** Currently-`is_active=True` models with failed fairness must not be touched. The gate runs only on **new training runs** invoked through `train_model_task`.
- **No zero-model gap.** When `block` mode rejects activation, the previously-active model in the same segment must continue serving predictions. The current code's atomic-block comment ("if create() fails, the old active model remains active") is the property we must preserve.
- **Opt-in default.** `warn` is the default — the PR ships zero behaviour change for any deployment that doesn't explicitly set the env var.
- **Reversible.** Operators who flip to `block` and hit unexpected blocks can revert by setting `ML_FAIRNESS_GATE_MODE=warn` — no code change, no data migration, no DB state to clean up.

## The setting

`backend/config/settings/base.py` near `CREDIT_POLICY_OVERLAY_MODE` (line 241):

```python
ML_FAIRNESS_GATE_MODE = os.environ.get("ML_FAIRNESS_GATE_MODE", "warn")
```

Three valid values:

| Mode | Behaviour | Use case |
|---|---|---|
| `warn` (default) | Activate first, run gate, log warning + flag `requires_fairness_review=True` if failed; **leave model active**. Byte-identical to current code. | All existing deployments. No change required. |
| `block` | Run gate **before** activation. If failed (or `metrics["fairness"]` is empty), raise `RuntimeError` and return early — old active model in segment continues serving. | Production environments that have validated their training pipeline produces compliant fairness metrics. |
| `off` | Skip the gate entirely (no check, no warning, no flag). | Emergency escape hatch. Documented but not the recommended path. |

Unknown values fall through to `warn` (mirrors the `credit_policy.py:405` pattern where unknown overlay modes default to `shadow`).

## The reorder

`backend/apps/ml_engine/tasks.py:75-138` flow change. Current:

```
1. atomic { deactivate old segment models, create new mv with is_active=True }
2. compute fairness gate result on metrics["fairness"]
3. record result on mv.training_metadata
4. if failed: log warning + set requires_fairness_review=True (model remains active)
5. clear cache + release lock
```

Proposed:

```
1. read mode = ML_FAIRNESS_GATE_MODE (defaults to "warn")
2. compute fairness gate result on metrics["fairness"]:
   - if metrics["fairness"] is empty → gate_data_present = False
   - else → run check_fairness_gate(metrics["fairness"])
3. if mode == "block":
   - if not gate_data_present:
     raise RuntimeError("Activation blocked (mode=block): no fairness data
     recorded. Re-run training with the fairness evaluator enabled, or set
     ML_FAIRNESS_GATE_MODE=warn after manual review.")
   - if gate failed:
     raise RuntimeError("Activation blocked (mode=block): failing protected
     attributes <list>. Set ML_FAIRNESS_GATE_MODE=warn after manual review,
     or fix training distribution and retrain.")
   The raise must happen BEFORE the atomic-activation block — old segment
   models stay active because we never enter the transaction.
4. atomic { deactivate old segment models, create new mv with is_active=True }
   (unchanged from current code)
5. record gate result + mode on mv.training_metadata
6. if mode == "warn" and gate failed:
   log warning + set requires_fairness_review=True
   (preserves current `warn` behaviour byte-identically)
7. clear cache + release lock (unchanged)
```

The reorder is the heart of the safety property: in `block` mode we raise **before** the `transaction.atomic()` block, so the deactivation of old models never happens. Old segment models keep `is_active=True`, no zero-model gap, no rollback machinery needed.

## Edge cases and explicit decisions

- **`check_fairness_gate({})` returns `{"passed": True}`** (verified by reading `fairness_gate.py`). That's because `gate_passed = len(failing_attributes) == 0` and an empty input produces no failing attributes. We do **not** want to treat that as a pass in `block` mode — operators forgetting to enable the fairness evaluator should not be a free-pass to activate. So `block` mode independently checks `if not metrics["fairness"]: raise` before delegating to `check_fairness_gate`.
- **Lock release on the failure path.** The existing `try/except` lock release at the end of `train_model_task` is structured as best-effort. The new `raise` paths must run after the lock is released, OR the lock release must be wrapped in a `try/finally`. Implementation will use `try/finally` to keep the lock-release contract explicit and avoid a ratchet-style training deadlock.
- **Cache invalidation on the failure path.** `clear_model_cache()` should NOT run on the block-and-raise path because no new model was activated — the cache is correctly pointing at the still-active old model. Implementation skips this on the failure branch.
- **Multiple segments.** The atomic block deactivates models in the **same segment** as the new training run (`tasks.py:82` filters by `segment=segment`). Block-and-raise on a `personal` retrain has zero effect on `home_owner_occupier` active models. Test will assert this.
- **The `mv.training_metadata.fairness_gate_mode` field** — record the mode used at activation time, so the dossier can later say "this model was activated under `warn` mode (gate failed)" vs "activated under `block` mode (gate passed)". Audit trail.
- **Unknown mode value.** Falls through to `warn` (with one log line `logger.warning("Unknown ML_FAIRNESS_GATE_MODE=%r — defaulting to 'warn'", mode)` matching the `credit_policy.py:405` pattern).

## Test surface

New file `backend/apps/ml_engine/tests/test_fairness_gate_mode.py` (services-level pure-function tests of the mode dispatcher) plus integration tests in the existing test suite for the activation flow.

| Test | Focus |
|---|---|
| `test_warn_mode_passing_fairness_activates_silently` | Default mode + clean fairness → activates, no warning. |
| `test_warn_mode_failing_fairness_still_activates_with_flag` | Default mode + failed fairness → activates, warning logged, `requires_fairness_review=True`. **Regression guard for current behaviour.** |
| `test_block_mode_passing_fairness_activates_normally` | `block` mode + clean fairness → activates, gate result and `mode=block` recorded on `training_metadata`. |
| `test_block_mode_failing_fairness_blocks_activation` | `block` mode + `passes_80_percent_rule=False` on any attribute → `RuntimeError` raised; `ModelVersion.objects.count()` unchanged from pre-call; old active model still `is_active=True`. |
| `test_block_mode_missing_fairness_data_blocks_activation` | `block` mode + `metrics["fairness"]` empty → `RuntimeError` with "no fairness data" wording. |
| `test_off_mode_skips_check_entirely` | `off` mode + failed fairness → activates, no warning, no flag, no gate result on `training_metadata`. |
| `test_block_mode_releases_training_lock_on_failure` | `block` raises, then assert `cache.get(training_lock_key)` is `None` (or that a second invocation can acquire). |
| `test_block_mode_does_not_disturb_other_segments` | `block` blocking a `personal` retrain → an active `home_owner_occupier` model still `is_active=True`. |
| `test_unknown_mode_falls_through_to_warn` | `ML_FAIRNESS_GATE_MODE=bogus` → behaves identically to `warn`, with one warning log line. |

Settings overrides via `@override_settings(ML_FAIRNESS_GATE_MODE=...)` (existing project pattern). Total: ~120 LOC test code.

## Implementation footprint

- `backend/apps/ml_engine/tasks.py`: ~30 LOC (mode read + reorder + early-raise branch + `try/finally` for lock release).
- `backend/config/settings/base.py`: 1 line.
- `backend/apps/ml_engine/tests/test_fairness_gate_mode.py`: ~120 LOC (new file).
- Zero touches to: `model_selector.py`, `credit_policy.py`, `mrm_dossier.py`, `mrm_compliance.py`, frontend, ENV files, migrations.

`tasks.py` is currently 380 LOC; +30 lands at ~410, comfortably under the 500-LOC quality-bar cap.

## Branch + PR shape

- Branch: `feat/ml-fairness-gate-block-mode`
- Single squash-merge PR. Title: `feat(ml): add ML_FAIRNESS_GATE_MODE setting (warn/block/off) for activation gating`.
- Body cites #162 as upstream and the Codex 2026-05-06 finding 2 that motivated the runtime follow-up.
- Mirrors the project's atomic-PR pattern.

## Out of scope (Phases 2 and 3 — separate brainstorms)

- **Phase 2.** Wire `model_selector.promote_if_eligible` (KS, PSI, ECE, AUC regression gates) into the activation path. Currently dead code outside tests. Multiple new gates with edge cases (first model in segment, regression vs champion). Separate spec when picked up.
- **Phase 3.** Switch `CREDIT_POLICY_OVERLAY_MODE` default `shadow` → `enforce`. Affects every prediction that hits `apply_overlay_to_decision()`. Deployment-policy decision; the right artifact is a runbook entry + env-var rollout plan, not a code PR.

Both are explicitly **deferred**, not abandoned.
