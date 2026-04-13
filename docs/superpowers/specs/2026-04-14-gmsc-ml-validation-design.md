# GMSC Real-Data ML Validation — Design

**Date:** 2026-04-14
**Status:** Draft — awaiting user review
**Scope:** Sub-project B of the 9.2 → 9.5+ rating push. Sub-projects A (frontend crash loop — verified resolved) and C (E2E tests — deferred) are out of scope.

## Problem

The loan-approval ML model (Random Forest + XGBoost, active `ModelVersion`) reports AUC 0.87–0.88 on synthetic data. The estimated real-world AUC is 0.80–0.83, but this has never been measured against a real, labeled dataset. Without an external benchmark, the quoted real-world number is not defensible to a reviewer, auditor, or hiring manager.

## Goal

Validate the active production model against the Kaggle "Give Me Some Credit" (GMSC) dataset — 250K labeled records — and produce a reproducible report that:

- Gives an honest AUC-ROC / AUC-PR number on real, externally-sourced data.
- Documents feature-overlap and distribution-shift caveats transparently.
- Is accessible to GitHub visitors without cloning (rendered HTML) and reproducible by engineers (Docker-launched notebook).
- Re-runs automatically when `backend/ml_engine/` changes (CI gate).

## Non-Goals

- Retraining the model on GMSC (this is validation only).
- Building a data-acquisition pipeline for Australian-specific real data.
- Replacing synthetic training data (GMSC is a measurement tool, not a training source).
- Pixel-accurate plot regression testing.

## Architecture

Three additions. No existing code is refactored.

### 1. Docker service: `jupyter`

- New service in `docker-compose.yml`, gated behind `profiles: ["ml"]` so it does not start with default `docker compose up`.
- Built from new `jupyter/Dockerfile` extending `python:3.13-slim`, installing `jupyter`, `nbconvert`, `papermill`, and the same requirements as the backend service.
- Mounts: `backend/`, `docs/`, `.tmp/`.
- Port: `127.0.0.1:8888:8888`, token-authenticated.
- Launched with `docker compose --profile ml up jupyter`.

### 2. Python package: `backend/ml_engine/validation/`

Three modules, each purely functional, unit-testable independent of the notebook:

- **`gmsc_loader.py`** — downloads GMSC from a pinned source URL into `backend/ml_engine/data/gmsc/` (gitignored); verifies SHA256 checksum against a value committed in the module; returns a DataFrame.
- **`feature_align.py`** — maps GMSC feature columns to the active Aussie model's feature schema. Produces (a) an aligned DataFrame and (b) an overlap report detailing which features matched directly, which were approximated, and which are missing (filled with training-set median, flagged).
- **`metrics.py`** — thin wrappers around sklearn for calibration curve data, AUC-PR, per-decile breakdowns. Exists so the notebook stays declarative and the metrics can be unit-tested.

### 3. Notebook + rendered artifact

- **`backend/ml_engine/notebooks/gmsc_validation.ipynb`** — the executed notebook. Parameters (threshold, random seed) are papermill-style top-of-notebook cells for reproducibility.
- **`docs/ml_validation.html`** — rendered notebook output, committed to the repo. This is the artifact reviewers see.
- **`docs/ml_validation.md`** — short narrative (what this is, how to regenerate, link to HTML, top-level summary table). Keeps the `docs/` index markdown-first.

## Data Flow

```
[Kaggle GMSC CSV]
       |  gmsc_loader.download() — SHA256-verified, cached
       v
[backend/ml_engine/data/gmsc/cs-training.csv]   (gitignored)
       |
       v
[feature_align.align(gmsc_df)] --> aligned DataFrame with Aussie-model schema
       |                           (missing → NaN → median, logged in overlap table)
       v
[ActiveModelVersion.predict_proba(X_aligned)]   (same code path production uses)
       |
       v
[metrics.evaluate(y_true, y_prob)] --> { auc_roc, auc_pr, calibration_df,
                                         confusion_at_threshold, per_decile }
       |
       v
[notebook renders plots + tables]
       |  nbconvert --to html --execute
       v
[docs/ml_validation.html]   (committed)
       |
       v
[CI re-runs on PRs touching ml_engine/** → publishes HTML as artifact]
```

### Key data decisions

- **Dataset not committed to git.** Pinned URL + SHA256 in `gmsc_loader.py` give deterministic re-acquisition.
- **Overlap report is a side-output written to `docs/ml_validation.md`** — the honest-caveats section, auto-regenerated so it cannot rot.
- **Model loaded from the active `ModelVersion` record** — the same code path production uses. Ensures we validate what actually runs.
- **Predicted probabilities, not binary labels** — enables calibration analysis. Threshold-dependent metrics use the production threshold from settings, with a sensitivity table at ±0.05.

## Error Handling

Proportional to an offline validation tool.

### Hard failures (raise, stop)

- Dataset download fails or SHA256 mismatch → `RuntimeError("GMSC download failed: ...")`. No silent fallback to synthetic.
- No active `ModelVersion` in DB → `RuntimeError`. Validation without a model is meaningless.
- Feature alignment drops more than 50% of expected features → raise. Signals either model-feature-list drift or broken GMSC mapping.

### Soft warnings (log + note in overlap table)

- Aussie feature has no GMSC equivalent → marked "missing — filled with training-set median" in the overlap table; execution continues.
- Small-sample calibration decile (<50 samples) → flagged in the calibration plot legend.

### CI failure mode

- `nbconvert` execution timeout (>600s) → CI job fails. Forces investigation rather than silent stall.

### Explicitly not handled

- Kaggle auth/rate limits → one-time manual setup; documented in README, not code.
- Non-deterministic model variance → seeded (numpy, sklearn, xgboost). Run-to-run drift is a real regression, not a bug to paper over.

## Testing

Three layers.

### 1. Unit tests — `backend/tests/test_ml_validation.py`

- `feature_align.align()` — given a GMSC row, returns a DataFrame with the exact Aussie-model feature schema; missing features filled as documented; overlap report accurate.
- `gmsc_loader.download()` — network mocked; asserts checksum validation rejects tampered files.
- `metrics.evaluate()` — deterministic fixtures; outputs match sklearn directly for known inputs.
- Target: 100% line coverage on `validation/`. Feasible because the package is pure-function code.

### 2. Notebook smoke test — `backend/tests/test_gmsc_notebook.py`

- Executes the notebook against a 500-row GMSC fixture (committed to `backend/tests/fixtures/gmsc_tiny.csv`).
- Asserts notebook runs to completion, expected output cells are present (AUC cell holds a float, calibration plot exists), HTML export succeeds.
- Fast (~30s); runs in the default test suite, not only CI.

### 3. CI gate — `.github/workflows/ml-validation.yml`

- Triggers on PRs touching `backend/ml_engine/**`.
- Downloads full GMSC dataset (cached via GitHub Actions cache keyed by SHA256).
- Runs notebook end-to-end with `nbconvert --execute`.
- Uploads `docs/ml_validation.html` as workflow artifact.
- Fails if AUC drops below a committed floor (initial value set after first successful run; tightened over time).
- Fails if the freshly-rendered HTML diverges from the committed `docs/ml_validation.html` (ensures the committed artifact stays in sync with the notebook).

### Explicitly not tested

- Visual plot correctness — HTML export sanity-check only. Pixel-diffing is expensive and brittle.
- Kaggle API — mocked, not exercised live.

## Delivery Checklist

- [ ] `docker-compose.yml` updated with `jupyter` service under `profiles: ["ml"]`.
- [ ] `jupyter/Dockerfile` created.
- [ ] `backend/ml_engine/validation/` package with `gmsc_loader.py`, `feature_align.py`, `metrics.py`, and `__init__.py`.
- [ ] `backend/ml_engine/data/gmsc/` added to `.gitignore`.
- [ ] `backend/ml_engine/notebooks/gmsc_validation.ipynb` committed.
- [ ] `docs/ml_validation.html` and `docs/ml_validation.md` committed.
- [ ] `backend/tests/test_ml_validation.py` and `test_gmsc_notebook.py` with tiny fixture.
- [ ] `nbstripout` pre-commit hook configured.
- [ ] `.github/workflows/ml-validation.yml` added.
- [ ] README updated with `docker compose --profile ml up jupyter` instructions and Kaggle-auth note.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| GMSC feature mismatch gives misleadingly low AUC, damaging credibility | Overlap report is prominent in rendered HTML; caveats section in `docs/ml_validation.md` explains distribution shift and feature alignment. |
| Dataset source URL changes or Kaggle restricts access | Pin to a mirror; document fallback acquisition path in `gmsc_loader.py` docstring. |
| CI job becomes flaky / slow | Cache dataset by checksum; smoke test uses tiny fixture so local tests stay fast. Full dataset run only in CI on targeted paths. |
| Engineers forget to commit regenerated HTML after model changes | CI job blocks the PR if committed HTML diverges from freshly-rendered HTML. |

## Open Questions

*None at this time — all clarifying questions resolved during brainstorming session 2026-04-14.*
