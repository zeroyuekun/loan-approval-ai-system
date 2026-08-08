# ml_engine service decomposition — foundation spec

**Date:** 2026-05-25
**Author:** Architecture review (Claude Opus 4.7) with Neville Zeng
**Status:** Draft — separate plan + multi-PR cycle when scheduled
**Source audit:** [2026-05-25 senior architect audit](2026-05-25-dashboard-persona-refit-design.md#audit-findings-that-motivated-this-spec-verified-2026-05-25)

---

## Problem statement

`backend/apps/ml_engine/services/` has grown into a ~50-file flat directory with five files exceeding 1000 lines each. The system's own CLAUDE.md says *"smaller, well-bounded units are easier to work with"* — the current layout violates that. Concrete bloat (verified 2026-05-25):

| File | LOC |
|------|-----|
| `data_generator.py` | **1,565** |
| `real_world_benchmarks.py` | 1,378 |
| `trainer.py` | 1,334 |
| `metrics.py` | 1,018 |
| `underwriting_engine.py` | 1,009 |
| `property_data_service.py` | 765 |
| `macro_data_service.py` | 579 |
| `calibration_validator.py` | 536 |
| `credit_bureau_service.py` | 506 |

There are also adjacent files with narrow purposes that should live together: `prediction_cache.py`, `prediction_diagnostics.py`, `prediction_explanations.py`, `prediction_features.py`, `policy_overlay.py`, `policy_recompute.py`. Right now they're scattered as siblings in a flat directory; a developer touching prediction logic has to scan six unrelated-looking filenames to find the right one.

## Goals

1. Reorganise `ml_engine/services/` into five sub-packages with clear boundaries: `datagen/`, `training/`, `scoring/`, `governance/`, `external/`.
2. Split the five files over 1000 LOC into focused modules under those sub-packages.
3. **Zero behaviour change.** All existing tests pass without modification beyond import-path updates.
4. Each new module has a single responsibility a developer can name in one sentence.

## Non-goals

- Adding new functionality. This is pure refactor.
- Renaming classes or methods (changes ripple through tests). Only file paths change.
- Touching `apps/agents/`, `apps/loans/`, `apps/email_engine/`, or the frontend.
- Performance tuning. If something's slow, that's a separate spec.

## Target structure

```
backend/apps/ml_engine/services/
├── datagen/
│   ├── __init__.py
│   ├── generator.py           # split from data_generator.py (1565 → ~500)
│   ├── distributions.py       # extracted: ATO/ABS/APRA copula calibration helpers
│   ├── outcome_simulator.py   # extracted: loan_performance_simulator.py (moved)
│   └── label_engine.py        # extracted: 1000-line rules-based underwriting that labels data
├── training/
│   ├── __init__.py
│   ├── trainer.py             # split from trainer.py (1334 → ~400)
│   ├── hyperparameter.py      # extracted: Optuna tuning loops
│   ├── feature_selection.py   # moved as-is
│   ├── feature_engineering.py # moved
│   ├── feature_prep.py        # moved
│   ├── monotone_constraints.py# moved
│   └── tstr_validator.py      # moved
├── scoring/
│   ├── __init__.py
│   ├── predictor.py           # moved (already 436 LOC after Arm C Phase 1)
│   ├── decision_assembly.py   # moved
│   ├── credit_policy.py       # moved
│   ├── policy_overlay.py      # moved
│   ├── policy_recompute.py    # moved
│   ├── prediction_cache.py    # moved
│   ├── prediction_diagnostics.py
│   ├── prediction_explanations.py
│   ├── prediction_features.py
│   ├── adverse_action.py      # moved
│   ├── reason_codes.py        # moved
│   ├── shap_attribution.py    # moved
│   ├── stress_testing.py      # moved
│   ├── counterfactual_engine.py
│   ├── pricing_engine.py
│   ├── segmentation.py
│   └── consistency.py
├── governance/
│   ├── __init__.py
│   ├── model_card.py          # moved
│   ├── mrm_dossier.py         # moved
│   ├── mrm_compliance.py      # moved
│   ├── fairness_gate.py       # moved
│   ├── fairness_gate_mode.py  # moved
│   ├── intersectional_fairness.py
│   ├── promotion_gate_mode.py # moved
│   ├── regression_gate.py     # moved
│   ├── shadow_scoring.py      # moved
│   ├── drift_monitor.py       # moved
│   ├── outcome_tracker.py     # moved
│   └── calibration_validator.py # split from 536-line file into validator + report writer
├── external/
│   ├── __init__.py
│   ├── credit_bureau.py       # was credit_bureau_service.py
│   ├── open_banking.py        # was open_banking_service.py
│   ├── property_data.py       # was property_data_service.py
│   ├── macro_data.py          # was macro_data_service.py
│   ├── plaid_patterns.py      # was plaid_patterns_service.py
│   ├── geocoding.py           # was geocoding_service.py
│   └── benchmark_resolver.py  # moved
└── metrics/
    ├── __init__.py
    ├── compute.py             # split from metrics.py (1018 → ~500)
    ├── fairness.py            # extracted: fairness metric computations
    ├── calibration.py         # extracted: calibration scoring helpers
    ├── ranking.py             # extracted: Gini/KS/decile/threshold compute
    └── real_world_benchmarks.py  # split from 1378-line file into a smaller benchmark loader
```

A re-exporting `__init__.py` in each subpackage preserves backward-compat for any caller importing `from apps.ml_engine.services.predictor import ModelPredictor` — the re-export keeps the old import working alongside the new `from apps.ml_engine.services.scoring import ModelPredictor`. A follow-up cleanup PR (out of scope here) tightens callers to the new paths.

## PR sequencing (5 PRs)

| PR | Subpackage | Risk | Why first/last |
|---|---|---|---|
| 1 | `external/` | Lowest — isolated I/O adapters with few internal callers | First; proves the re-export pattern works |
| 2 | `metrics/` | Medium — split one big file into 5 focused ones | Second; bounded blast radius |
| 3 | `governance/` | Medium — many files, few internal cross-refs | Third |
| 4 | `scoring/` | High — predictor.py is the hot path everyone imports | Fourth; build on stable re-exports |
| 5 | `datagen/` + `training/` | Highest — biggest splits, most call sites | Last; do the dangerous part with confidence the rest is stable |

Each PR includes:
- The directory + file moves (use `git mv` so history is preserved per file).
- The split of any file > 1000 LOC into focused modules under the new path.
- A re-export `__init__.py` so existing import paths keep working.
- All existing tests still pass — `pytest apps/ml_engine/` must be green at every commit.
- No new tests, no new functionality.

## Risks

- **Test churn from import paths.** Mitigation: re-export shims preserve old paths during the PR. A follow-up cleanup PR migrates callers, then deletes the re-exports.
- **Circular imports.** Some splits may surface latent circular dependencies between modules. Mitigation: when one is found, surface it in the PR description — fixing it is in scope (it indicates a real architectural smell), introducing it isn't.
- **Reviewer fatigue.** Each PR is large by file-count but small by line-count change (mostly moves). Mitigation: PR descriptions explicitly say "git mv-only except where noted, focus review on the noted exception".

## Acceptance per PR

1. `git diff` for any moved file fits on one screen (proves it really was a move).
2. `pytest apps/ml_engine/` is green at every commit.
3. `grep -rn "from apps.ml_engine.services\." backend/apps/` finds zero broken paths.
4. The PR's new sub-package has an `__init__.py` re-exporting the public names that previously lived at the parent module.

## What this lays foundation for

- Easier onboarding — a new developer can scan five subdir names and know roughly where things live.
- Future feature work in scoring/governance/external no longer has to add another grab-bag file to the flat directory.
- Pre-requisite for any future "make ml_engine deployable as a separate service" conversation — without clean boundaries, that's a non-starter.

## Out of scope for this spec

- CDR / Open Banking adapter (separate foundation spec — depends on `external/` landing first).
- Security gap-closure (separate foundation spec — independent).
- Backend API surface changes. None of this touches DRF views, serializers, or URLs.
