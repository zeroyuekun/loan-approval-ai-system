# Age-at-Loan-Maturity Policy Gate — Design

**Date:** 2026-04-15
**Source:** Sub-project A research (`docs/research/2026-04-14-au-lending-research.md` — Alex Bank section)
**Out of scope:** Visa-subclass eligibility gate (separate deferred item); "satisfactory repayment proposal" escape hatch; auto-suggesting a shorter term that fits; informational warnings for applicants close to the cap.

## Goal

Hard-deny loan applications where the applicant would be older than 67 at loan maturity. Short-circuit the pipeline before ML scoring. Emit a transparent reason code (`R50`) so the denial email explains the cause.

## Why a hard decline, not a human-review flag

Project memory (`feedback_human_review_bias_only.md`): human review queue is reserved for bias flags. Blanket policies such as an age-at-maturity cap must be enforced deterministically, not queued for review. A transparent, reason-coded denial is therefore the correct path.

## Rule

```
age_at_maturity_years = (today - date_of_birth).years + (loan_term_months / 12)
```

- If `> 67`: deny.
- If `<= 67`: pass (continue to `fraud_check` and the rest of the pipeline).
- If `date_of_birth` is missing on the applicant's `CustomerProfile`: pass (defensive only — submission is already gated on a completed profile).

Integer months are used for `loan_term_months / 12` (e.g. 60 months = 5.0 years).

## Architecture

### New unit: `EligibilityChecker`

- Location: `backend/apps/agents/services/eligibility_checker.py`
- Responsibility: pure, stateless, synchronous function `check(application) -> EligibilityResult` where:
  - `EligibilityResult.passed: bool`
  - `EligibilityResult.reason_code: str | None`
  - `EligibilityResult.detail: str | None`
- No DB writes. No side effects. Easy to unit-test in isolation.

### Integration: `PipelineOrchestrator.orchestrate()`

Add a new step named `eligibility_check` as the **first** step, before `fraud_check`:

1. `_start_step("eligibility_check")`
2. Call `EligibilityChecker().check(application)`.
3. If passed: `_complete_step(...)` and continue to `fraud_check`.
4. If failed:
   - Write a `LoanDecision` with `decision="denied"`, reason code + detail captured in the reasoning field.
   - Transition the application status to `denied` via `LoanApplication.transition_to("denied", ...)` so existing status-change hooks fire.
   - `_complete_step(...)` with a summary indicating the denial reason.
   - `_finalize_run(agent_run, steps, start_time)` and return early — do NOT run fraud_check, ML scoring, bias, NBO, or email generation in this path.
   - The outer pipeline's existing denial email path handles email generation based on the denied status (same path that handles any other denial).

### Reason code

Add to `backend/apps/ml_engine/services/reason_codes.py`:

```python
"age_at_loan_maturity": (
    "R50",
    "Applicant age at loan maturity exceeds 67-year policy limit",
),
```

Feature name `age_at_loan_maturity` is chosen to align with the research gap name for future ML-feature use, even though this rule is not a model feature.

## Testing

### Unit tests for `EligibilityChecker` (`backend/apps/agents/tests/test_eligibility_checker.py`)

Exactly four test cases:

1. `test_passes_when_maturity_age_under_67` — age 30, term 60 months → maturity age 35 → passes.
2. `test_denies_when_maturity_age_over_67` — age 65, term 60 months → maturity age 70 → denies with `R50`.
3. `test_boundary_exactly_67_passes` — age 62, term 60 months → maturity age exactly 67 → passes (rule is `> 67`, not `>= 67`).
4. `test_passes_when_date_of_birth_missing` — applicant with no `date_of_birth` → passes (defensive).

### Integration test (`backend/apps/agents/tests/test_orchestrator_eligibility.py`)

One test:

1. `test_orchestrator_denies_on_age_maturity_and_skips_ml` — build an application whose applicant is 70 at maturity, mock the ML predictor to fail if called, run the orchestrator, assert: application status is `denied`, `LoanDecision.decision == "denied"`, reason contains `R50`, ML predictor was NOT called.

### Regression safeguard

Existing orchestrator tests must continue to pass. If any existing test builds an applicant whose maturity age exceeds 67, update the test's date_of_birth / loan_term_months so it passes the gate — don't change the gate to accommodate tests.

## Success criteria

- `EligibilityChecker` exists with a pure `check(application)` function
- `R50` reason code registered
- Orchestrator wires `eligibility_check` as the first step and short-circuits on fail
- 4 unit tests + 1 integration test all pass
- No existing tests regress
- Denial email generated for denied applications contains `R50`
- The change is reversible as a single git revert

## Deliverables

- Create: `backend/apps/agents/services/eligibility_checker.py`
- Create: `backend/apps/agents/tests/test_eligibility_checker.py`
- Create: `backend/apps/agents/tests/test_orchestrator_eligibility.py`
- Modify: `backend/apps/agents/services/orchestrator.py` (add first step)
- Modify: `backend/apps/ml_engine/services/reason_codes.py` (add R50)
