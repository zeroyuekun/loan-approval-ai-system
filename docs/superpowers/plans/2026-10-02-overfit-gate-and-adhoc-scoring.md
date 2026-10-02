# Validation Overfit Gate and Ad-hoc Applicant Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Overfitting is measured on the validation split and enforced as a promotion gate, and staff can score a single applicant against the active model without creating an application.

**Architecture:** The trainer records `val_auc` and `overfitting_gap_val` in `training_metadata`. `promote_if_eligible` gains an overfitting gate next to the PSI and ECE gates, so it inherits `ML_PROMOTION_GATE_MODE`, the activation records and the dashboards. Ad-hoc scoring uses `ModelPredictor.predict(application, persist=False)` on an unsaved `LoanApplication`. The service lives in `scoring/adhoc.py`, the view is thin, and a "Try it" tab on Model Metrics calls it.

**Tech Stack:** Django REST Framework, scikit-learn/XGBoost, Next.js + React Query, vitest.

**Spec:** `docs/superpowers/specs/2026-10-02-agent-pipeline-completeness-design.md` (sections C and D). That spec is committed on `feat/bias-agent2-regenerate`. One planned deviation: the overfitting gate is added inside `promote_if_eligible` (model_selector.py) rather than as a new `_evaluate_gates` entry, so it reuses the promotion gate's mode, records and UI.

## Global Constraints

- `ml_engine/services` has a 500-LOC per-file cap (`tools/file_size_allowlist.json`). `training/trainer.py` is capped at 1415 and is at 1385, so keep the additions under 30 lines.
- Ad-hoc scoring persists nothing: no `LoanApplication`, no `PredictionLog`, no referral write. Its `AuditLog` entry holds field names only.
- A model version with no `overfitting_gap_val` passes the gate with `not_assessable: true`.
- Backend tests run in a dev-stage container built from this worktree. See the "Testing a git worktree" note in the project memory. Run one test container at a time. For frontend work in this worktree, junction `node_modules` to the main tree and remove the junction with `cmd /c rmdir`.
- Run ruff on the host before each commit. Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

---

### Task 1: Validation AUC and gap in the trainer

**Files:**
- Modify: `backend/apps/ml_engine/services/training/trainer.py`, around line 1000 (the overfitting block) and the `training_metadata` dict near line 1030.
- Test: `backend/apps/ml_engine/tests/test_overfit_gate.py` (new)

**Interfaces:**
- Produces: `training_metadata["val_auc"]` (float, 4dp) and `training_metadata["overfitting_gap_val"]` (float, 4dp, train minus val).

- [ ] Step 1: Write the failing test. Train on a small generated dataset with the existing test helper used by other trainer tests (find it with `grep -rn "ModelTrainer()" apps/ml_engine/tests | head`). Assert both keys are present, `val_auc` is between 0 and 1, and `overfitting_gap_val == round(train_auc - val_auc, 4)`.
- [ ] Step 2: Run it. Expected: FAIL with KeyError `val_auc`.
- [ ] Step 3: Implement next to the train AUC computation:

```python
        # Overfitting is judged on the validation split, before the test set is
        # read; the train-vs-test gap below stays as the final independent figure.
        val_auc = round(float(roc_auc_score(y_val, model.predict_proba(X_val)[:, 1])), 4)
        overfitting_gap_val = round(train_auc - val_auc, 4)
```

Add `"val_auc": val_auc, "overfitting_gap_val": overfitting_gap_val,` to `training_metadata`.
- [ ] Step 4: Run it. Expected: PASS.
- [ ] Step 5: Commit `feat(ml_engine): record validation AUC and train-vs-validation gap`.

### Task 2: Overfitting promotion gate

**Files:**
- Modify: `backend/apps/ml_engine/services/model_selector.py`. Add the constant `MAX_OVERFIT_GAP = 0.05`, the parameter `max_overfit_gap`, and gate 5, evaluated before the no-champion short-circuit.
- Modify: `backend/config/settings/base.py`. `ML_OVERFIT_MAX_GAP = float(os.environ.get("ML_OVERFIT_MAX_GAP", "0.05"))`.
- Test: `backend/apps/ml_engine/tests/test_overfit_gate.py`

- [ ] Step 1: Write the failing tests against `promote_if_eligible` with ModelVersion rows that pass PSI and ECE (copy how `test_regression_gate.py` builds them):
  - gap 0.08 → `promoted=False`, with "Overfitting gate failed" in the reasons.
  - gap 0.03 → passes.
  - Missing key → `gates["overfitting"]["not_assessable"] is True`, and it passes.
  - The setting override `ML_OVERFIT_MAX_GAP=0.10` makes 0.08 pass.
- [ ] Step 2: Run them. Expected: FAIL. `gates` has no "overfitting" key.
- [ ] Step 3: Implement:

```python
    # --- Gate 5: Overfitting (train vs validation AUC) ---------------------
    limit = max_overfit_gap if max_overfit_gap is not None else getattr(settings, "ML_OVERFIT_MAX_GAP", MAX_OVERFIT_GAP)
    gap = (getattr(candidate_version, "training_metadata", None) or {}).get("overfitting_gap_val")
    if gap is None:
        gates["overfitting"] = {"value": None, "threshold": limit, "passed": True, "not_assessable": True}
    else:
        gap = float(gap)
        gates["overfitting"] = {"value": gap, "threshold": limit, "passed": gap <= limit}
        if gap > limit:
            reasons.append(f"Overfitting gate failed: train-vs-validation AUC gap {gap:.4f} exceeds {limit:.2f}")
```

Mention "overfitting gap ≤ limit" in the all-gates-passed reason string.
- [ ] Step 4: Run the tests together with `test_regression_gate.py`, `test_promotion_gate_mode.py` and `test_activation_service.py`. Expected: PASS.
- [ ] Step 5: Frontend: in `frontend/src/components/metrics/diagnostics.ts`, add `train_auc` "Train AUC", `val_auc` "Validation AUC" and `overfitting_gap_val` "Overfitting Gap (train − validation)", and relabel `overfitting_gap` as "Overfitting Gap (train − test)". Update the matching vitest, if one exists, with `npx vitest run src/components/metrics`.
- [ ] Step 6: Commit `feat(ml_engine): overfitting gate on the train-vs-validation gap`.

### Task 3: Predictor dry run (PR D starts here)

Create the branch `feat/adhoc-applicant-scoring` from the Task 2 commit.

**Files:**
- Modify: `backend/apps/ml_engine/services/scoring/predictor.py`. `predict(self, application, *, persist=True)`. When `persist` is false, skip shadow scoring and pass `persist_referral=False` to the overlay.
- Modify: `backend/apps/ml_engine/services/scoring/policy_overlay.py`. Add the `persist_referral: bool = True` keyword, which guards the `application.save(...)` block.
- Test: `backend/apps/ml_engine/tests/test_adhoc_scoring.py` (new)

- [ ] Step 1: Write the failing test. Train or load the fixture model that other predictor tests use (`grep -rn "ModelPredictor(" apps/ml_engine/tests | head`). Build an unsaved `LoanApplication(**fields)` with `has_bankruptcy=True` (or another value that triggers a policy refer, chosen by reading `credit_policy.py`). Call `predict(app, persist=False)`. Assert there are no new `PredictionLog` rows and no `LoanApplication` rows, and the result has `probability`.
- [ ] Step 2: Run it. Expected: FAIL. `persist` is an unexpected keyword.
- [ ] Step 3: Implement both guards.
- [ ] Step 4: Run it plus `apps/ml_engine/tests -k "predict or overlay or shadow"`. Expected: PASS.
- [ ] Step 5: Commit `feat(ml_engine): predictor dry-run mode that writes nothing`.

### Task 4: Ad-hoc scoring endpoint

**Files:**
- Create: `backend/apps/ml_engine/services/scoring/adhoc.py`, with `AdhocApplicantSerializer` (a ModelSerializer over `LoanApplication.DECISION_INPUT_FIELDS`) and `score_applicant(validated_data) -> dict`.
- Modify: `backend/apps/ml_engine/views.py`. Add `AdhocScoreView` (`IsAdminOrOfficer`, `AdhocScoreThrottle` rate `30/hour`).
- Modify: `backend/apps/ml_engine/urls.py`. `path("models/active/score/", views.AdhocScoreView.as_view(), name="model-score")`.
- Test: `backend/apps/ml_engine/tests/test_adhoc_scoring.py`

**Interfaces:**
- Produces: `POST /api/v1/ml/models/active/score/`. The response is `{"probability": float, "decision": "approved"|"denied", "threshold": float, "risk_grade": str, "top_factors": [{"feature": str, "impact": float}], "model_version": str}`. `top_factors` holds the 5 largest absolute SHAP values.

- [ ] Step 1: Write the failing tests:
  - A customer gets 403.
  - Missing `credit_score` gets 400.
  - An officer with valid fields gets 200 with the response keys.
  - No `LoanApplication` or `PredictionLog` rows are written.
  - One `AuditLog` row with `action="adhoc_score"`, whose `details["fields"]` is a sorted list of names and contains no submitted values.

  Patch `apps.ml_engine.services.scoring.adhoc.ModelPredictor` to return a concrete dict (no MagicMock leaves) for the view tests. Use the real predictor only in Task 3's test.
- [ ] Step 2: Run them. Expected: FAIL with 404 on the URL.
- [ ] Step 3: Implement. `score_applicant` builds `LoanApplication(**validated_data)`, calls `ModelPredictor(segment=derive_segment(app)).predict(app, persist=False)` and shapes the response. The view validates the input, calls the service, writes the AuditLog row and returns 200. If no active model is found, it returns 503 with `{"detail": "No active model"}`.
- [ ] Step 4: Run them. Expected: PASS.
- [ ] Step 5: Commit `feat(ml_engine): score one applicant against the active model`.

### Task 5: "Try it" tab

**Files:**
- Create: `frontend/src/components/metrics/tabs/TryItTab.tsx`
- Modify: `frontend/src/app/dashboard/model-metrics/page.tsx`. Add the tab trigger and content.
- Modify: the API client module that other ml calls use (find it with `grep -rn "models/active/metrics" frontend/src/lib`). Add `scoreApplicant(fields)`.
- Test: `frontend/src/components/metrics/tabs/__tests__/TryItTab.test.tsx` (or the repo's existing test location for tabs)

- [ ] Step 1: Write the failing vitest. Render `TryItTab` with the mocked `scoreApplicant` resolving to a fixed response, submit the prefilled form, and expect the probability percentage and the decision label in the document.
- [ ] Step 2: Run `npx vitest run <test path>`. Expected: FAIL, because the module is missing.
- [ ] Step 3: Implement the form. Fields: annual income, credit score, loan amount, loan term, debt to income, employment length, purpose, home ownership, employment type, applicant type, state and dependants. Selects use the same choice lists as the apply form (import them, don't copy). Prefill a sample applicant. Submit with a React Query `useMutation`. Show the probability, the decision against the threshold, the model version, and `top_factors` as a list with feature labels from the existing label map.
- [ ] Step 4: Run vitest, `npx tsc --noEmit` and `npm run lint`. Expected: PASS.
- [ ] Step 5: Commit `feat(frontend): Try it tab scores one applicant on Model Metrics`.

### Task 6: Verify and hand off

- [ ] Run the full backend suite once in the worktree container, plus `python tools/check_file_sizes.py`.
- [ ] Run ruff check and format on the host.
- [ ] Do not push. Record the results for the PR bodies.
