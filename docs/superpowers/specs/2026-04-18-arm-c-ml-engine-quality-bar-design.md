# Arm C — `ml_engine/services/` Quality Bar + Hot-Path Refactor

**Date:** 2026-04-18
**Target version:** v1.11.0
**Base branch:** `master` (post v1.10.0, at `4f8b13f`)
**Scope:** Bring the `ml_engine/services/` package under an enforced quality bar and
refactor the 6 hot-path god-modules. Each phase is an atomic, independently-shippable PR.

---

## 1. Goal

After v1.10.0 shipped (Arm A — XGBoost AU lender parity), `backend/apps/ml_engine/services/`
grew to **16,470 LOC across 23 files**, with 10 files above 500 LOC and 6 above 1,000 LOC.
These "god-modules" are hard to reason about, risky to change, and signal technical debt
to anyone reviewing the repo.

Arm C does two things:

1. Installs a **lasting quality bar** (enforced via CI) so this class of drift cannot
   silently return.
2. Refactors the **6 worst offenders** into focused sub-modules that each have a single
   responsibility, a clear public API, and their own test file.

The bar is the asset; the refactor is the initial compliance work.

---

## 2. Non-goals

- **Feature work.** No new ML behaviour, no new decisioning rules, no new integrations.
  If a refactor surfaces a bug, it gets a separate PR; we don't fix it in-place and call
  the refactor "done".
- **Unrelated packages.** `accounts/`, `loans/`, `email_engine/`, `agents/` stay untouched.
  A separate Arm (or Workstream C follow-up) can extend the quality bar there.
- **Rewriting Arm A code.** `credit_policy.py`, `model_selector.py`, `mrm_dossier.py`,
  `pricing_engine.py`, `monotone_constraints.py`, `metrics.py`, `regression_gate.py`,
  `segmentation.py` shipped under MRM review three commits ago. We do not refactor them
  in this arm unless they exceed the bar (only `metrics.py` at 1,010 LOC does — covered
  in Phase 4).
- **Test coverage improvements** beyond what the bar requires per new module file
  (≥70%). A broader coverage push is a separate Arm.
- **Performance optimisation.** Refactors must not regress latency, but we don't chase
  speedups.

---

## 3. The Quality Bar

Four rules, all enforced via CI checks that run on every PR:

### 3.1 File size: ≤500 LOC
- Hard fail at 500 LOC in any file under `backend/apps/ml_engine/services/`
- Warning at 400 LOC (flagged in PR comment, non-blocking)
- Excluded: `__init__.py`, `migrations/`, generated files
- **Initial allowlist** lists the 10 files already above the bar with their current
  LOC as the ceiling; each phase's PR removes its target file(s) from the allowlist.
  CI fails if any allowlisted file grows beyond its recorded ceiling.

### 3.2 Single responsibility
- Every module file must start with a module docstring that states the responsibility
  in one sentence. Enforced via a simple AST check in the CI script (presence of
  `Module.body[0]` being an `Expr(Constant(str))` that is also non-empty).
- Not enforced: the *quality* of the docstring. That's a review concern.

### 3.3 Test coverage ≥70% per new module file
- New files created in refactor phases must ship with a corresponding `test_<name>.py`
- `pytest --cov=apps.ml_engine.services.<new_module>` must report ≥70% line coverage
- Existing files are measured against a baseline and must not regress
- Coverage check runs in CI via `pytest-cov`

### 3.4 No wildcard imports; explicit public API
- `from X import *` banned (ruff F403/F405 already flags this project-wide; we simply
  keep enforcement on for this package)
- Every module exports an explicit `__all__ = [...]` listing public symbols
- Private helpers use `_` prefix

### 3.5 CI enforcement tooling
- `tools/check_file_sizes.py` — new script; reads allowlist, walks package, fails CI
  with a clear diff message if any file exceeds its cap
- Hooked into `.github/workflows/ci.yml` as a non-conditional job (runs before tests)
- Pre-commit hook in `.pre-commit-config.yaml` runs the same check locally

---

## 4. Priority & Phase Map

| Phase | File | LOC | Natural split | Rationale |
|-------|------|-----|---------------|-----------|
| **P0** | `predictor.py` | 1,209 | `predictor.py` (core orchestration) + `feature_prep.py` + `policy_recompute.py` + `prediction_cache.py` | Hot path — every approval call touches it. Highest visibility. |
| **P0** | `trainer.py` | 1,316 | `trainer.py` (orchestrator) + `preprocessing.py` + `hyperopt.py` + `evaluation.py` | Hot path — every retrain runs through it. Current file mixes four concerns. |
| **P1** | `data_generator.py` | 1,551 | `data_generator.py` (entry-point) + `realism/` subpackage with per-variable generators (`realism/income.py`, `realism/credit.py`, `realism/employment.py`, `realism/property.py`, ...) | Largest file. Per-variable logic is genuinely separable. |
| **P1** | `metrics.py` | 1,010 | `metrics.py` (facade re-exports) + `_psi.py` + `_ks.py` + `_brier.py` + `_calibration.py` | Each metric family is ~150-250 LOC; clean separation. |
| **P2** | `real_world_benchmarks.py` | 1,378 | `benchmarks/__init__.py` (runner) + `benchmarks/gmsc.py` + `benchmarks/lending_club.py` + `benchmarks/home_credit.py` + per-benchmark fixtures | Each benchmark is independent; current file is a hand-maintained registry. |
| **P2** | `underwriting_engine.py` | 1,001 | `underwriting_engine.py` (orchestrator) + `rules/` per-rule modules (`rules/serviceability.py`, `rules/lvr.py`, `rules/affordability.py`, ...) | Rules fire independently; orchestrator composes them. |

### 4.1 Phase 3 (P3) — triage-only
After phases 0-2, these four files remain in the 500-800 LOC band:

- `property_data_service.py` (765 LOC)
- `macro_data_service.py` (579 LOC)
- `calibration_validator.py` (536 LOC)
- `credit_bureau_service.py` (506 LOC)

A **single triage PR** (Phase 7) reviews each: if it can be split into a coherent
pair of modules (service + client, or validator + fixtures), split it; otherwise
add an exception to the allowlist with a documented rationale ("contains a large
static mapping that is not separable").

---

## 5. Rollout Phases

Each phase is one PR. Phases are independent and can land in any order after Phase 0;
the table below lists the recommended order (hot path first).

### Phase 0 — Quality Bar + CI Check
- Ship `tools/check_file_sizes.py`, `.github/workflows/quality-bar.yml` (or extend
  existing CI), `.pre-commit-config.yaml` update
- Initial allowlist records current LOC of all 10 over-bar files as the ceiling
- **Zero refactoring** in this PR — the allowlist makes CI pass today
- Smoke tests: create a test file that briefly exceeds 500 LOC, confirm CI fails;
  revert, confirm CI passes
- **Merge target:** master. Subsequent phases target master and shrink the allowlist.

### Phase 1 — `predictor.py` split (P0)
- Extract `feature_prep.py` (the per-application feature assembly that predictor does)
- Extract `policy_recompute.py` (the `_recompute_lvr_driven_policy_vars` helper and
  anything downstream of it)
- Extract `prediction_cache.py` (the SHAP cache and prediction memoisation)
- Keep `predictor.py` as the orchestrator — `predict()`, `for_application()`,
  segment routing, and the glue calling into the three extracted modules
- Re-export extracted public symbols from `predictor.py` so external imports keep
  working (`from apps.ml_engine.services.predictor import ModelPredictor` unchanged)
- **Regression safety:** shadow-verification test that predicts on a fixture loan
  application pre- and post-refactor and asserts identical output dict

### Phase 2 — `trainer.py` split (P0)
- Extract `preprocessing.py` (`add_derived_features`, `_imputation_values` management,
  `fit_preprocess` / `transform`)
- Extract `hyperopt.py` (Optuna tuning loop + hyperparameter bookkeeping)
- Extract `evaluation.py` (metric computation, confusion matrix, feature importance,
  calibration curve, split-strategy metadata)
- Keep `trainer.py` as the `ModelTrainer` class with `train()`, `save_model()`,
  and the `NUMERIC_COLS` / `CATEGORICAL_COLS` constants
- **Regression safety:** existing `test_trainer_pipeline.py` golden-run test must
  produce identical model metrics (AUC, KS, confusion matrix) pre- and post-refactor

### Phase 3 — `data_generator.py` split (P1)
- Create `realism/` subpackage with one module per variable family:
  `income.py`, `credit.py`, `employment.py`, `property.py`, `macro.py`,
  `hem.py`, `reject_inference.py`
- `data_generator.py` becomes the entry-point that composes these (≤ 400 LOC)
- **Regression safety:** `DataGenerator(random_seed=42).generate(num_records=1000)`
  must produce a byte-identical CSV pre- and post-refactor (pandas.util.hash_pandas_object)

### Phase 4 — `metrics.py` split (P1)
- Extract `_psi.py`, `_ks.py`, `_brier.py`, `_calibration.py`
- `metrics.py` becomes a facade that re-exports the public functions
  (`psi`, `psi_by_feature`, `ks_statistic`, `brier_decomposition`, `expected_calibration_error`)
- No re-export needed for private symbols (underscore prefix)
- **Regression safety:** existing `test_metrics_production_grade.py` must pass unchanged

### Phase 5 — `real_world_benchmarks.py` split (P2)
- Create `benchmarks/` subpackage: `__init__.py` with runner + one file per benchmark
- Move fixture data into `benchmarks/fixtures/` as CSVs or JSONs (where practical —
  sometimes the benchmark logic owns its fixtures inline; that's fine)
- Runner entry-point: `run_benchmark(name: str) -> dict`
- **Regression safety:** full benchmark run produces identical AUC/KS values per
  benchmark compared to baseline

### Phase 6 — `underwriting_engine.py` split (P2)
- Create `rules/` subpackage, one module per rule family
- Each rule module exports a single `evaluate(application, context) -> RuleResult`
  function
- `underwriting_engine.py` becomes the composer: collects rule results and aggregates
  into a final underwriting verdict
- **Regression safety:** fixture-based end-to-end test of the underwriting flow
  produces identical verdicts

### Phase 7 — P3 triage
- For each of the 4 remaining over-bar files, one of:
  - Split into a clean pair (service + client, validator + fixtures, etc.)
  - Add an exception to the allowlist with a one-line rationale referencing the
    natural boundary (or lack of one)

---

## 6. Regression Safety Strategy

Every refactor phase follows the same four-step pattern:

1. **Green baseline:** before changing any code, run the full test suite on master
   and confirm green. Capture baseline metric values (e.g., model AUC on the golden
   dataset for Phase 2) as reference.
2. **Refactor with test coverage:** move code file-by-file, update imports, run tests
   after each move. Re-exports from the original module file preserve the public API.
3. **Shadow verification:** for phases touching the prediction or training path
   (Phases 1, 2, 3), add a one-off shadow test that compares pre- and post-refactor
   outputs on a fixed fixture. The test lives in the PR and is deleted on merge
   (it has no long-term value — it's a gate, not a regression test).
4. **CI gate:** test suite must pass, coverage must not drop below baseline,
   quality-bar check must pass with the allowlist updated to reflect the new state.

Coverage baseline is captured in Phase 0 and enforced per-PR via the existing
`pytest --cov` runner.

---

## 7. Success Criteria

Arm C ships successfully when all of the following are true:

- `tools/check_file_sizes.py` runs in CI and blocks PRs that exceed the bar
- The 6 P0/P1/P2 files are all below 500 LOC (or, in the P3 triage phase, explicitly
  allowlisted with rationale)
- Every new module file has ≥70% line coverage
- Test suite is green; ML metrics (AUC, KS, Brier, ECE) on the golden dataset are
  within noise of the v1.10.0 baseline (any drift is investigated, not accepted)
- `APP_VERSION` bumped to 1.11.0 in the final phase
- `CHANGELOG.md` entry documents the arm's scope, outcome, and any allowlist
  exceptions kept

---

## 8. Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Re-export drift — external code imports a symbol from `predictor.py` that moved to `feature_prep.py` and re-export is missed | Medium | Shadow-verification tests on the prediction/training golden fixture catch import breakages; additionally, grep for `from apps.ml_engine.services.<file> import` before each phase to inventory external consumers |
| Test-suite flakes masking a real regression | Low | Run each phase's test suite 3× locally before pushing; CI re-runs on failure are treated as "investigate", not "retry until green" |
| Refactor surfaces a pre-existing bug | Medium | File a separate issue/PR; do **not** fix in-place. Arm C PRs are refactor-only. |
| Allowlist becomes permanent for P3 files | Low | Phase 7 PR description must justify every allowlist entry. Reviewer (user) can reject and force the split. |
| Pre-commit hook slows commits noticeably | Low | `check_file_sizes.py` walks ~25 files; should complete in <100 ms. Benchmark during Phase 0. |

---

## 9. What This Unlocks

After Arm C lands:

- **Arm B (stress testing)** can extend `underwriting_engine/rules/` with new APRA
  CPS 220 scenarios without reopening a 1,000 LOC file
- **Any future ML retrain work** operates in `trainer/preprocessing.py`,
  `trainer/hyperopt.py`, or `trainer/evaluation.py` — narrow scope per PR
- **New reviewers / maintainers** can navigate the package without needing to hold
  1,500 LOC in their head
- **Quality-bar CI check** is reusable for `accounts/`, `loans/`, `email_engine/`,
  `agents/` — extending it is one-line config in the workflow

---

## 10. Out-of-scope (explicit)

- **Type hints coverage sweep** — tempting to mix in, but doubles the review burden
- **Docstring rewrites** beyond the one-sentence responsibility line required by bar 3.2
- **`__init__.py` cleanups** in `ml_engine/services/` — its current empty state is fine
- **Splitting P3 files that trigger with <600 LOC** — diminishing returns; the bar
  is 500 and the triage PR can justify exceptions
- **Parallel refactoring of files outside `ml_engine/services/`** — future arm

---

## 11. Handoff to writing-plans

This spec is the source of truth for the implementation plan. The plan should:

- Structure phases 0-7 as atomic tasks with full code for each step (no placeholders)
- Include the exact LOC of each file at plan-write time (Phase 0 needs an allowlist
  seeded with real numbers, not rounded ones)
- Reference `docs/superpowers/specs/2026-04-18-arm-c-ml-engine-quality-bar-design.md`
  at the top so the executing agent can verify compliance per phase
