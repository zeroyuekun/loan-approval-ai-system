# Age-at-Maturity Policy Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hard-deny loan applications where the applicant's age at loan maturity exceeds 67, short-circuiting the pipeline before ML scoring and surfacing reason code `R50`.

**Architecture:** Pure `EligibilityChecker` service produces a pass/fail result. `PipelineOrchestrator` adds an `eligibility_check` step as the first step; on fail it writes a denied `LoanDecision`, transitions the application to `denied`, finalises the run, and returns early.

**Tech Stack:** Django, DRF, existing orchestrator step-tracker pattern.

**Spec:** `docs/superpowers/specs/2026-04-15-age-maturity-policy-gate-design.md`

---

## Context for implementers (read this first)

- Orchestrator file: `backend/apps/agents/services/orchestrator.py`. Existing first step is `fraud_check` at line ~123.
- Step tracker pattern: `self._start_step("name")`, `self._complete_step(step, result_summary=...)`, `self._waterfall_entry(step, result, reason_code, detail)`.
- Applicant DOB: `application.applicant.profile.date_of_birth_date` returns a `datetime.date | None` (helper at `backend/apps/accounts/models.py:252`). Profile may be `None` if not yet created — handle with `getattr(application.applicant, "profile", None)`.
- Loan term lives on `application.loan_term_months` (integer).
- Status transitions: `application.transition_to("denied", user=None, details={...})` — see existing orchestrator denial paths.
- Reason codes: `backend/apps/ml_engine/services/reason_codes.py` has a `REASON_CODE_MAP` dict keyed by feature name.
- Tests live under `backend/apps/agents/tests/`. If that directory doesn't exist yet, create it with an empty `__init__.py`.

---

## Task 1: Add reason code R50

**Files:**
- Modify: `backend/apps/ml_engine/services/reason_codes.py`

- [ ] **Step 1: Locate the end of `REASON_CODE_MAP`**

Run:
```bash
grep -n "^}" backend/apps/ml_engine/services/reason_codes.py | head -3
```
Identify the closing `}` of `REASON_CODE_MAP` (the dict literal). The last existing entry is around line 60 (`months_since_last_default`).

- [ ] **Step 2: Add the new entry before the closing `}`**

Find the final existing entry (whichever it is today) and append, preserving the grouping comment style. Example insertion:

```python
    # Policy gates (deterministic, not ML features)
    "age_at_loan_maturity": (
        "R50",
        "Applicant age at loan maturity exceeds 67-year policy limit",
    ),
```

Place this as the last entry inside `REASON_CODE_MAP`. Keep the trailing comma so future additions are clean.

- [ ] **Step 3: Verify the file still parses**

Run:
```bash
python -c "import ast; ast.parse(open('backend/apps/ml_engine/services/reason_codes.py').read()); print('ok')"
```
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add backend/apps/ml_engine/services/reason_codes.py
git commit -m "feat(reason-codes): add R50 age-at-maturity policy gate"
```

---

## Task 2: Write failing tests for `EligibilityChecker`

**Files:**
- Create: `backend/apps/agents/tests/__init__.py` (if missing)
- Create: `backend/apps/agents/tests/test_eligibility_checker.py`

- [ ] **Step 1: Ensure the tests package exists**

Run:
```bash
ls backend/apps/agents/tests/__init__.py 2>/dev/null || ( mkdir -p backend/apps/agents/tests && touch backend/apps/agents/tests/__init__.py )
```

- [ ] **Step 2: Write the failing test file**

Create `backend/apps/agents/tests/test_eligibility_checker.py`:

```python
"""Tests for EligibilityChecker — age-at-loan-maturity policy gate."""
import datetime
from types import SimpleNamespace

import pytest

from apps.agents.services.eligibility_checker import EligibilityChecker


def _make_application(age_years: int | None, loan_term_months: int):
    """Build a minimal duck-typed application for the pure checker.

    EligibilityChecker is deliberately pure: it reads only date_of_birth_date
    and loan_term_months, so we don't need a Django model instance.
    """
    dob = None
    if age_years is not None:
        today = datetime.date.today()
        dob = today.replace(year=today.year - age_years)
    profile = SimpleNamespace(date_of_birth_date=dob)
    applicant = SimpleNamespace(profile=profile)
    return SimpleNamespace(applicant=applicant, loan_term_months=loan_term_months)


def test_passes_when_maturity_age_under_67():
    app = _make_application(age_years=30, loan_term_months=60)
    result = EligibilityChecker().check(app)
    assert result.passed is True
    assert result.reason_code is None


def test_denies_when_maturity_age_over_67():
    app = _make_application(age_years=65, loan_term_months=60)
    result = EligibilityChecker().check(app)
    assert result.passed is False
    assert result.reason_code == "R50"
    assert "67" in (result.detail or "")


def test_boundary_exactly_67_passes():
    app = _make_application(age_years=62, loan_term_months=60)
    result = EligibilityChecker().check(app)
    assert result.passed is True


def test_passes_when_date_of_birth_missing():
    app = _make_application(age_years=None, loan_term_months=60)
    result = EligibilityChecker().check(app)
    assert result.passed is True
```

- [ ] **Step 3: Confirm the test file fails to collect (module missing)**

Run:
```bash
cd backend && python -m pytest apps/agents/tests/test_eligibility_checker.py -v 2>&1 | tail -10
```
Expected: ModuleNotFoundError or ImportError for `apps.agents.services.eligibility_checker`.

---

## Task 3: Implement `EligibilityChecker` to make tests pass

**Files:**
- Create: `backend/apps/agents/services/eligibility_checker.py`

- [ ] **Step 1: Write the service**

Create `backend/apps/agents/services/eligibility_checker.py`:

```python
"""Age-at-loan-maturity eligibility gate.

Policy: deny if the applicant would be older than 67 at the end of the loan.
Source: Alex Bank published rule (see docs/research/2026-04-14-au-lending-research.md).
"""
import datetime
from dataclasses import dataclass


AGE_AT_MATURITY_LIMIT_YEARS = 67


@dataclass(frozen=True)
class EligibilityResult:
    passed: bool
    reason_code: str | None = None
    detail: str | None = None


class EligibilityChecker:
    """Pure, stateless policy gate. No DB writes, no side effects."""

    def check(self, application) -> EligibilityResult:
        dob = self._dob(application)
        if dob is None:
            return EligibilityResult(passed=True)

        today = datetime.date.today()
        current_age_years = self._years_between(dob, today)
        term_years = (application.loan_term_months or 0) / 12.0
        age_at_maturity = current_age_years + term_years

        if age_at_maturity > AGE_AT_MATURITY_LIMIT_YEARS:
            return EligibilityResult(
                passed=False,
                reason_code="R50",
                detail=(
                    f"Applicant would be {age_at_maturity:.1f} years old at loan "
                    f"maturity; policy limit is {AGE_AT_MATURITY_LIMIT_YEARS}."
                ),
            )
        return EligibilityResult(passed=True)

    @staticmethod
    def _dob(application) -> datetime.date | None:
        applicant = getattr(application, "applicant", None)
        profile = getattr(applicant, "profile", None) if applicant is not None else None
        if profile is None:
            return None
        return getattr(profile, "date_of_birth_date", None)

    @staticmethod
    def _years_between(start: datetime.date, end: datetime.date) -> float:
        delta_days = (end - start).days
        return delta_days / 365.25
```

- [ ] **Step 2: Run the tests**

Run:
```bash
cd backend && python -m pytest apps/agents/tests/test_eligibility_checker.py -v 2>&1 | tail -15
```
Expected: 4 passed.

- [ ] **Step 3: Commit**

```bash
git add backend/apps/agents/services/eligibility_checker.py backend/apps/agents/tests/test_eligibility_checker.py backend/apps/agents/tests/__init__.py
git commit -m "feat(eligibility): add EligibilityChecker service + unit tests"
```

---

## Task 4: Write failing integration test

**Files:**
- Create: `backend/apps/agents/tests/test_orchestrator_eligibility.py`

- [ ] **Step 1: Write the integration test**

Create `backend/apps/agents/tests/test_orchestrator_eligibility.py`:

```python
"""Integration test: orchestrator short-circuits on age-at-maturity denial.

Confirms that when EligibilityChecker denies an application, the orchestrator
writes a denied LoanDecision, transitions the application to 'denied', and
does NOT invoke the ML predictor.
"""
import datetime
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from apps.accounts.models import CustomerProfile
from apps.agents.services.orchestrator import PipelineOrchestrator
from apps.loans.models import LoanApplication, LoanDecision


@pytest.mark.django_db
def test_orchestrator_denies_on_age_maturity_and_skips_ml():
    User = get_user_model()
    user = User.objects.create_user(
        username="too-old", password="test-pass", role="customer"
    )
    # Applicant is 65 today; with a 60-month term, maturity age is 70 → >67.
    dob = datetime.date.today().replace(year=datetime.date.today().year - 65)
    profile = CustomerProfile.objects.create(user=user, date_of_birth=dob.isoformat())

    app = LoanApplication.objects.create(
        applicant=user,
        loan_amount=25000,
        loan_term_months=60,
        purpose="personal",
        annual_income=80000,
        credit_score=720,
        debt_to_income=0.25,
        monthly_expenses=3000,
        employment_type="payg_permanent",
        employment_length=5,
        home_ownership="rent",
        state="NSW",
        applicant_type="single",
    )

    # If ML scoring is called, fail the test — the gate should short-circuit.
    with patch(
        "apps.ml_engine.services.predictor.Predictor.predict",
        side_effect=AssertionError("ML predictor should not be called when policy gate fails"),
    ):
        orch = PipelineOrchestrator()
        orch.orchestrate(str(app.id))

    app.refresh_from_db()
    assert app.status == "denied"
    decision = LoanDecision.objects.get(application=app)
    assert decision.decision == "denied"
    assert "R50" in (decision.reasoning or "")
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:
```bash
cd backend && python -m pytest apps/agents/tests/test_orchestrator_eligibility.py -v 2>&1 | tail -15
```
Expected: FAIL. Failure mode will be either "ML predictor called" (gate not wired up) or "application not denied". Record which — either confirms the feature isn't integrated yet.

---

## Task 5: Wire `eligibility_check` as the orchestrator's first step

**Files:**
- Modify: `backend/apps/agents/services/orchestrator.py`

- [ ] **Step 1: Add the import**

At the top of `orchestrator.py`, with the other `from .xxx import yyy` lines, add:

```python
from .eligibility_checker import EligibilityChecker
```

- [ ] **Step 2: Insert the step BEFORE the existing `fraud_check` step**

Find the block that begins `# Step 0: Fraud Detection / Velocity Checks` (around line 123) and insert the following immediately before it:

```python
        # Policy gate: age at loan maturity must be <= 67 (Alex Bank policy).
        # Deterministic, runs before any ML scoring to short-circuit on fail.
        step = self._start_step("eligibility_check")
        try:
            eligibility_result = EligibilityChecker().check(application)
        except Exception as e:
            step = self._fail_step(step, e)
            steps.append(step)
            self._finalize_run(agent_run, steps, start_time, error=str(e))
            raise

        if not eligibility_result.passed:
            waterfall.append(
                self._waterfall_entry(
                    "eligibility_check",
                    "fail",
                    eligibility_result.reason_code or "POLICY_GATE",
                    eligibility_result.detail or "",
                )
            )
            step = self._complete_step(
                step,
                result_summary={
                    "passed": False,
                    "reason_code": eligibility_result.reason_code,
                    "detail": eligibility_result.detail,
                },
            )
            steps.append(step)

            # Record a denied LoanDecision with the reason in the reasoning field.
            LoanDecision.objects.update_or_create(
                application=application,
                defaults={
                    "decision": "denied",
                    "reasoning": (
                        f"[{eligibility_result.reason_code}] "
                        f"{eligibility_result.detail}"
                    ),
                },
            )
            application.transition_to(
                "denied",
                details={
                    "source": "eligibility_check",
                    "reason_code": eligibility_result.reason_code,
                },
            )
            self._finalize_run(agent_run, steps, start_time)
            return agent_run

        waterfall.append(
            self._waterfall_entry(
                "eligibility_check",
                "pass",
                "POLICY_CLEAR",
                "Age-at-maturity within policy",
            )
        )
        step = self._complete_step(
            step,
            result_summary={"passed": True},
        )
        steps.append(step)

```

- [ ] **Step 3: Add the `LoanDecision` import if not already present**

Check the top of `orchestrator.py`. If `LoanDecision` is not imported, add:

```python
from apps.loans.models import LoanDecision
```

(Inspect existing imports with `grep "^from apps.loans" backend/apps/agents/services/orchestrator.py` — the file likely imports `LoanApplication` and `FraudCheck` already; add `LoanDecision` to that import line if present, else add a new line.)

- [ ] **Step 4: Run the integration test and confirm it passes**

Run:
```bash
cd backend && python -m pytest apps/agents/tests/test_orchestrator_eligibility.py -v 2>&1 | tail -15
```
Expected: 1 passed.

- [ ] **Step 5: Run the existing test suite to confirm no regressions**

Run:
```bash
cd backend && python -m pytest apps/agents/ apps/loans/ apps/ml_engine/ -x -q 2>&1 | tail -20
```
Expected: all green. If any existing test fails because its fixture creates a >67-at-maturity applicant, fix the test fixture (adjust DOB or term) — do NOT weaken the policy gate.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/agents/services/orchestrator.py backend/apps/agents/tests/test_orchestrator_eligibility.py
git commit -m "feat(orchestrator): wire age-at-maturity policy gate as first step

Short-circuits the pipeline when the applicant would be >67 at loan
maturity. Writes a denied LoanDecision with reason code R50, transitions
application status to 'denied', and returns before fraud check or ML
scoring. Integration test confirms the ML predictor is not invoked."
```

---

## Task 6: Final verification

**Files:** none.

- [ ] **Step 1: Run everything one more time**

```bash
cd backend && python -m pytest apps/agents/ apps/loans/ apps/ml_engine/ -q 2>&1 | tail -10
```
Expected: all pass.

- [ ] **Step 2: Manual smoke (optional but recommended)**

With the stack up, create a test applicant who would be >67 at maturity, POST a loan application, trigger `/api/v1/agents/orchestrate/<loan_id>/`, and confirm the application is denied with reason code R50 in the `LoanDecision.reasoning` field.

---

## Done criteria

- 4 unit tests pass; 1 integration test passes
- No existing tests regress
- `R50` appears in `reason_codes.py`
- `EligibilityChecker` is a pure, stateless service with no DB writes
- Orchestrator denies >67-at-maturity applicants without invoking the ML predictor
- Single-revert rollback path preserved
