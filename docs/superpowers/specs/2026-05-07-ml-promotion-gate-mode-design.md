# ML Promotion Gate Mode — runtime activation gating, Phase 2

**Date:** 2026-05-07
**Status:** Approved design, pending implementation plan
**Scope:** Phase 2 of the runtime gating work deferred from PR #162. Wires `model_selector.promote_if_eligible` (KS, PSI, ECE, AUC regression gates — currently dead code outside tests) into `train_model_task` activation, gated by an opt-in `ML_PROMOTION_GATE_MODE` setting that mirrors `ML_FAIRNESS_GATE_MODE` from PR #163. Phase 3 (`CREDIT_POLICY_OVERLAY_MODE` default flip) is out of scope and is now documented as a runbook artifact rather than a code change.

## Context

PR #163 added a fairness gate dispatcher (`evaluate_fairness_gate_for_activation`) with three modes: `warn` (default — current behaviour byte-identical), `block`, `off`. This spec adds the parallel dispatcher for the four-gate champion-challenger promotion check (KS regression, PSI stability, ECE calibration, AUC regression). The promotion gates already exist as `model_selector.promote_if_eligible`; they're well-tested but never invoked from production code paths.

Mirroring Phase 1's mode shape lets operators learn one pattern that applies to both gates. The default `warn` mode preserves current behaviour byte-identically — gates run nowhere, model activates regardless of metric regressions vs the incumbent champion.

## The wiring trick

`promote_if_eligible(candidate)` reads metric attributes via `getattr` + `training_metadata` JSON (duck-typed), queries the DB **once** for the champion, returns a `PromotionDecision`, and does **not** mutate the candidate. So we can call it pre-activation by passing a transient `SimpleNamespace` stub built from the in-memory `metrics` dict — no DB write needed, no refactor of `promote_if_eligible`. The `pk=None` on the stub makes the `.exclude(pk=...)` clause inside `promote_if_eligible` a no-op which is correct (we want the existing active model excluded only if it shares pk with us, which a None pk never does).

## The setting

`backend/config/settings/base.py` near `ML_FAIRNESS_GATE_MODE`:

```python
ML_PROMOTION_GATE_MODE = os.environ.get("ML_PROMOTION_GATE_MODE", "warn")
```

Three valid values, identical semantics to the fairness gate:

| Mode | Behaviour |
|---|---|
| `warn` (default) | Run gates, log + record decision on `training_metadata`, leave model active. Byte-identical to pre-PR behaviour where gates simply weren't invoked at all (we now invoke them but don't act on a failure). |
| `block` | Run gates pre-activation. If `decision.promoted == False`, raise `PromotionGateBlocked` BEFORE the atomic activation transaction. Old segment models keep `is_active=True`; no zero-model gap. |
| `off` | Skip gate evaluation entirely. Emergency escape hatch. |

Unknown values fall through to `warn` with one log line (mirrors `credit_policy.py:405`, `fairness_gate_mode.py:normalize_mode`).

## The dispatcher

New module `backend/apps/ml_engine/services/promotion_gate_mode.py`:

```python
class PromotionGateBlocked(RuntimeError): ...

VALID_MODES = ("warn", "block", "off")
DEFAULT_MODE = "warn"

def normalize_mode(mode): ...

def evaluate_promotion_gates_for_activation(decision: PromotionDecision, mode: str) -> dict:
    """Decide whether activation should proceed given a promotion decision.

    Returns:
        {"action": "activate" | "skip_check",
         "decision": PromotionDecision | None,
         "mode": str}

    Raises PromotionGateBlocked in `block` mode when decision.promoted is False.
    """
```

Pure-functional, no DB, no Django settings dependency — takes mode as an argument so it's testable without app boot.

## Wiring in `tasks.py`

Drops in directly after the fairness gate dispatcher call (added in PR #163), still pre-`transaction.atomic()`:

```python
# Existing (PR #163): fairness gate dispatcher
fairness_decision = evaluate_fairness_gate_for_activation(...)

# New: promotion gates pre-activation. Build a transient candidate stub
# from in-memory metrics — no DB write needed.
from types import SimpleNamespace
candidate_stub = SimpleNamespace(
    id="(pre-activation)", pk=None, segment=segment,
    auc_roc=metrics["auc_roc"],
    ks_statistic=metrics["ks_statistic"],
    ece=metrics.get("calibration_data", {}).get("ece"),
    training_metadata=metrics.get("training_metadata", {}),
)
promotion_decision = promote_if_eligible(candidate_stub)
promotion_gate_decision = evaluate_promotion_gates_for_activation(
    promotion_decision,
    getattr(settings, "ML_PROMOTION_GATE_MODE", "warn"),
)
# raise propagates to outer task wrapper, releases lock, no atomic block entered

# (existing atomic activation block — unchanged)
with transaction.atomic():
    ...
```

Post-activation, the dispatcher result joins `mv.training_metadata` so the dossier audit trail captures the promotion decision (gates + champion id + reasons + mode).

## Edge cases

- **First model in segment** — `promote_if_eligible` short-circuits Gates 1+4 (KS regression, AUC regression) when no champion exists; only PSI + ECE are evaluated. The dispatcher delegates wholesale, so this just works — first models in a segment auto-promote after PSI+ECE pass.
- **Pre-D5 model with no `psi_by_feature` recorded** — `_max_psi` returns `float("inf")`, which fails Gate 2. In `block` mode, this means an old-format model can't be activated until it's retrained with the v1.9.9+ trainer. Acceptable — the model registry uses post-D5 trainers in practice.
- **`metrics["calibration_data"]` missing `ece`** — `_metric` falls back to `1.0`, which is well above the 0.03 ECE ceiling. `block` mode would refuse activation. Operators see "ECE 1.0000 exceeds 0.03 ceiling" in the error and either fix the trainer or set mode to `warn`.
- **DB query inside `promote_if_eligible`** — the function performs one ORM query for the champion. In CI without DB, the query layer raises and the dispatcher would propagate. Tests for the dispatcher patch `promote_if_eligible` to avoid the DB; the integration of `promote_if_eligible` itself is covered by existing `test_metrics_production_grade.py` tests.

## Test surface

New file `backend/apps/ml_engine/tests/test_promotion_gate_mode.py` — service-level pure-function tests of the dispatcher. Constructs `PromotionDecision` instances directly (no DB). ~10 tests, ~120 LOC.

| Test | Focus |
|---|---|
| `test_normalize_mode_accepts_valid_values` | Sanity floor |
| `test_normalize_mode_collapses_unknown_to_warn` | Misconfigured deployment doesn't silently bypass |
| `test_warn_mode_promoted_returns_activate` | Default mode + decision.promoted=True → activate, decision recorded |
| `test_warn_mode_rejected_still_returns_activate` | Default mode + decision.promoted=False → activate (regression guard for the current zero-call-site behaviour) |
| `test_block_mode_promoted_returns_activate` | block + promoted → activate |
| `test_block_mode_rejected_raises_with_reasons` | block + rejected → `PromotionGateBlocked` whose message includes the failed gate reasons |
| `test_block_mode_includes_remediation_hint_in_error` | Error message names `ML_PROMOTION_GATE_MODE=warn` as the override path |
| `test_off_mode_skips_check_entirely` | off mode → skip_check, no raise |
| `test_off_mode_does_not_inspect_decision` | Patches `decision.promoted` access; off mode must not read the decision |
| `test_promotion_gate_blocked_is_runtime_error` | Subclass contract |

The `_do_train` integration is mechanical (build stub → call function → call dispatcher → raise/proceed). Existing `test_metrics_production_grade.py::promote_if_eligible — gate matrix` tests already exercise the gate logic with DB.

## Implementation footprint

- `backend/config/settings/base.py`: 1 line (`ML_PROMOTION_GATE_MODE = os.environ.get("ML_PROMOTION_GATE_MODE", "warn")`)
- `backend/apps/ml_engine/services/promotion_gate_mode.py`: ~70 LOC (new)
- `backend/apps/ml_engine/tests/test_promotion_gate_mode.py`: ~150 LOC (new)
- `backend/apps/ml_engine/tasks.py`: ~20 LOC (stub construction + dispatcher call + metadata write)

`tasks.py` is at 422 LOC after PR #163; +20 lands at ~442, comfortably under the 500-LOC quality-bar cap.

## Constraints honored

Same as PR #163, restated for completeness:

- **No retroactive deactivation.** The gate runs only on new `train_model_task` runs; existing `is_active=True` models are never touched.
- **No zero-model gap.** `block`-mode raise happens before the atomic transaction.
- **Opt-in default.** `warn` is the default — the PR ships zero behaviour change for any deployment that doesn't set the env var.
- **Reversible.** Operators flip `ML_PROMOTION_GATE_MODE=warn` to revert.

## Branch + PR shape

- Branch: `feat/ml-promotion-gate-block-mode`
- Single squash-merge PR. Title: `feat(ml): add ML_PROMOTION_GATE_MODE setting (warn/block/off) wiring promote_if_eligible into activation`.
- Body cites PR #163 as the upstream pattern and the parent #162 review.

## Out of scope (Phase 3 — handled separately)

`CREDIT_POLICY_OVERLAY_MODE` default `shadow` → `enforce`. After thinking it through: this is a runbook artifact, not a code change. Flipping the global default would change runtime behaviour for every deployment without an explicit env var, which violates the "opt-in default" safety constraint that Phases 1 and 2 honor. The right Phase 3 deliverable is a documented enablement procedure (prerequisite checks, rollout monitoring, rollback steps) so an operator can flip `CREDIT_POLICY_OVERLAY_MODE=enforce` in their own deployment when ready. Tracked as a follow-up doc PR.
