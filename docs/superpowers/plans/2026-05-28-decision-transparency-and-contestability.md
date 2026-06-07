# Decision Transparency & Contestability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give declined applicants a single, explainable decision view plus an in-app right to request human review of an automated decision, satisfying the 10 Dec 2026 Privacy Act ADM transparency reforms.

**Architecture:** A pure `DecisionExplanation` assembler becomes the single source of truth for the *customer-facing* decision payload (reasons + counterfactuals + reapplication guidance + ADM disclosure). A dedicated `DecisionReview` model + endpoints implement contestability, orthogonal to the bias queue and linking to the existing `Complaint`→AFCA path. An ADM disclosure register is surfaced per-decision, in `DenialExplanationPanel`, and on `/rights`. Everything is additive, behind `DECISION_REVIEW_ENABLED` (default on), and never touches the scoring/training path.

**Tech Stack:** Django 5 + DRF, PostgreSQL, pytest; Next.js 15 + React 19 + TanStack Query + vitest/testing-library.

**Spec:** `docs/superpowers/specs/2026-05-28-decision-transparency-and-contestability-design.md`

**Refinements from spec (decided during planning):**
- `search_counterfactuals` is orphaned (no prod caller) and varies non-actionable features → **retired**, not kept as a fallback.
- The email prose path (`email_generator._format_denial_reasons`) is **out of scope for v1** (tone-tuned; high regression risk, low value). The assembler is the UI contract and replaces the `human_review_handler` ad-hoc denial string.

---

## Task 0: Branch setup

**Files:** none (git only)

- [ ] **Step 1: Create the feature branch off master**

The current branch is `feat/perf-prompt-caching` with unrelated work. Verify a clean tree, then branch.

```bash
git status --short
git fetch origin
git switch -c feat/decision-transparency-contestability origin/master
```

Expected: new branch created from `origin/master`. If `git switch` reports local changes would be overwritten, stop and resolve with the user (do not discard their `tsconfig.json` change).

- [ ] **Step 2: Move the already-written spec onto this branch and commit it**

```bash
git add docs/superpowers/specs/2026-05-28-decision-transparency-and-contestability-design.md docs/superpowers/plans/2026-05-28-decision-transparency-and-contestability.md
git commit -m "docs(spec): decision transparency & contestability design + plan"
```

Expected: spec + plan committed on the feature branch.

---

## Phase 1 — ADM disclosure register (standalone, no dependencies)

### Task 1: ADM disclosure register + resolver

**Files:**
- Create: `backend/apps/ml_engine/services/adm_disclosure.py`
- Test: `backend/apps/ml_engine/tests/test_adm_disclosure.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/apps/ml_engine/tests/test_adm_disclosure.py
from apps.ml_engine.services.adm_disclosure import resolve_adm_disclosure, ADM_REGISTER


def test_solely_automated_decline_has_human_review_right():
    d = resolve_adm_disclosure(decision="denied", requires_human_review=False)
    assert d["mode"] == "solely_automated"
    assert d["human_review_right"] is True
    assert "credit" in " ".join(d["info_used"]).lower()
    assert d["review_request_path"] == "/api/v1/loans/decision-reviews/"


def test_escalated_decision_is_assisted():
    d = resolve_adm_disclosure(decision="denied", requires_human_review=True)
    assert d["mode"] == "assisted"
    assert d["human_review_right"] is True


def test_register_modes_are_known():
    assert {e["mode"] for e in ADM_REGISTER.values()} <= {"solely_automated", "assisted", "human"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest apps/ml_engine/tests/test_adm_disclosure.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.ml_engine.services.adm_disclosure`.

- [ ] **Step 3: Write the implementation**

```python
# backend/apps/ml_engine/services/adm_disclosure.py
"""Automated decision-making (ADM) disclosure register.

Implements the transparency obligations of the Privacy Act 1988 ADM reforms
(APP 1.7-1.9, commencing 10 Dec 2026) and the Voluntary AI Safety Standard
"transparency" + "contestability" guardrails: a loan applicant is told whether
their decision was made solely by automated means or with human involvement,
what kinds of information were used, and that they may request a human review.

Kept as code (not DB) — these are product/legal facts about the pipeline, not
per-tenant config. Surfaced three ways: in the customer decision payload (via
DecisionExplanation), in the DenialExplanationPanel, and on the /rights page.
"""

from __future__ import annotations

REVIEW_REQUEST_PATH = "/api/v1/loans/decision-reviews/"

_INFO_USED = [
    "Income and employment details you provided",
    "Credit report and repayment history (Equifax/Illion, CCR)",
    "Existing debts, expenses and serviceability under an interest-rate buffer",
    "Loan amount, term and purpose",
]

ADM_REGISTER: dict[str, dict] = {
    "automated_approve": {
        "mode": "solely_automated",
        "summary": "Approved by our automated credit-decision model.",
        "info_used": _INFO_USED,
        "human_review_right": True,
    },
    "automated_decline": {
        "mode": "solely_automated",
        "summary": "Declined by our automated credit-decision model.",
        "info_used": _INFO_USED,
        "human_review_right": True,
    },
    "escalated_review": {
        "mode": "assisted",
        "summary": "Assessed by our automated model and reviewed by a lending officer.",
        "info_used": _INFO_USED,
        "human_review_right": True,
    },
}


def resolve_adm_disclosure(*, decision: str, requires_human_review: bool) -> dict:
    """Return the ADM disclosure block for a single decision.

    `requires_human_review` reflects whether the decision was escalated to a
    human (borderline / drift / bias) — those are "assisted", everything else
    is "solely_automated".
    """
    if requires_human_review:
        entry = ADM_REGISTER["escalated_review"]
    elif decision == "approved":
        entry = ADM_REGISTER["automated_approve"]
    else:
        entry = ADM_REGISTER["automated_decline"]

    return {
        "mode": entry["mode"],
        "summary": entry["summary"],
        "info_used": list(entry["info_used"]),
        "human_review_right": entry["human_review_right"],
        "review_request_path": REVIEW_REQUEST_PATH,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend pytest apps/ml_engine/tests/test_adm_disclosure.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/ml_engine/services/adm_disclosure.py backend/apps/ml_engine/tests/test_adm_disclosure.py
git commit -m "feat(ml): ADM disclosure register for Privacy Act APP 1.7-1.9"
```

---

## Phase 2 — Unified `DecisionExplanation` assembler

### Task 2: The assembler (pure functions)

**Files:**
- Create: `backend/apps/ml_engine/services/decision_explanation.py`
- Test: `backend/apps/ml_engine/tests/test_decision_explanation.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/apps/ml_engine/tests/test_decision_explanation.py
from apps.ml_engine.services.decision_explanation import (
    ranked_denial_drivers,
    build_explanation_payload,
)


def test_ranked_drivers_prefers_negative_shap_then_caps():
    shap = {"credit_score": -0.4, "annual_income": -0.1, "loan_amount": 0.2, "debt_to_income": -0.3}
    drivers = ranked_denial_drivers(shap_values=shap, feature_importances={}, max_n=2)
    assert [d[0] for d in drivers] == ["credit_score", "debt_to_income"]


def test_ranked_drivers_falls_back_to_importances_when_no_negative_shap():
    drivers = ranked_denial_drivers(
        shap_values={}, feature_importances={"credit_score": 0.5, "loan_amount": 0.2}, max_n=1
    )
    assert drivers[0][0] == "credit_score"


def test_build_payload_denied_has_reasons_counterfactuals_and_adm():
    payload = build_explanation_payload(
        decision="denied",
        shap_values={"credit_score": -0.5},
        feature_importances={"credit_score": 0.5},
        counterfactual_results=[{"changes": {"loan_amount": 10000}, "statement": "Reduce your loan amount"}],
        requires_human_review=False,
    )
    assert payload["decision"] == "denied"
    assert payload["denial_reasons"][0]["code"] == "R06"
    assert payload["counterfactuals"][0]["statement"].startswith("Reduce")
    assert payload["reapplication_guidance"] is not None
    assert payload["adm_disclosure"]["mode"] == "solely_automated"


def test_build_payload_approved_omits_denial_fields():
    payload = build_explanation_payload(
        decision="approved", shap_values={}, feature_importances={}, counterfactual_results=[],
        requires_human_review=False,
    )
    assert payload["denial_reasons"] == []
    assert payload["counterfactuals"] == []
    assert payload["reapplication_guidance"] is None
    assert payload["adm_disclosure"]["mode"] == "solely_automated"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest apps/ml_engine/tests/test_decision_explanation.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

```python
# backend/apps/ml_engine/services/decision_explanation.py
"""Single source of truth for the customer-facing decision explanation.

Consolidates the previously-duplicated denial-reason ranking that lived in
`loans.serializers.CustomerLoanDecisionSerializer`, `agents...human_review_handler`,
and (prose-only) `email_generator._format_denial_reasons`. This module owns the
ranking; renderers (structured reason codes for the UI, ADM disclosure) consume it.

Pure functions — no Django model writes — so they unit-test without a DB and can
run against either a saved `LoanDecision` or a live `prediction_result` dict.
"""

from __future__ import annotations

from apps.ml_engine.services.adm_disclosure import resolve_adm_disclosure
from apps.ml_engine.services.reason_codes import (
    generate_adverse_action_reasons,
    generate_reapplication_guidance,
)


def ranked_denial_drivers(
    *, shap_values: dict, feature_importances: dict, max_n: int = 4
) -> list[tuple[str, float]]:
    """Canonical ordered list of (feature, magnitude) that drove a denial.

    Prefers per-applicant negative SHAP (most-negative first). Falls back to
    global feature importances (descending) when no negative SHAP is present.
    This is the ONE ranking all customer-facing surfaces start from.
    """
    if shap_values:
        negative = [(name, val) for name, val in shap_values.items() if val < 0]
        if negative:
            negative.sort(key=lambda x: x[1])  # most negative first
            return [(name, abs(val)) for name, val in negative[:max_n]]
    ordered = sorted(feature_importances.items(), key=lambda x: x[1], reverse=True)
    return [(name, float(val)) for name, val in ordered[:max_n]]


def build_explanation_payload(
    *,
    decision: str,
    shap_values: dict | None,
    feature_importances: dict | None,
    counterfactual_results: list | None,
    requires_human_review: bool,
) -> dict:
    """Build the customer-facing decision payload (the UI/serializer contract)."""
    shap_values = shap_values or {}
    feature_importances = feature_importances or {}
    counterfactual_results = counterfactual_results or []

    denial_reasons = generate_adverse_action_reasons(shap_values, decision)

    if decision == "denied":
        counterfactuals = counterfactual_results
        reapplication_guidance = generate_reapplication_guidance(counterfactual_results, denial_reasons)
    else:
        counterfactuals = []
        reapplication_guidance = None

    return {
        "decision": decision,
        "denial_reasons": denial_reasons,
        "counterfactuals": counterfactuals,
        "reapplication_guidance": reapplication_guidance,
        "adm_disclosure": resolve_adm_disclosure(
            decision=decision, requires_human_review=requires_human_review
        ),
    }


def build_explanation_from_decision(loan_decision) -> dict:
    """Convenience wrapper for a saved `LoanDecision` instance."""
    requires_human_review = getattr(loan_decision.application, "status", "") == "review"
    return build_explanation_payload(
        decision=loan_decision.decision,
        shap_values=loan_decision.shap_values or {},
        feature_importances=loan_decision.feature_importances or {},
        counterfactual_results=loan_decision.counterfactual_results or [],
        requires_human_review=requires_human_review,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend pytest apps/ml_engine/tests/test_decision_explanation.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/ml_engine/services/decision_explanation.py backend/apps/ml_engine/tests/test_decision_explanation.py
git commit -m "feat(ml): DecisionExplanation assembler — single denial-reason ranking"
```

### Task 3: Wire `CustomerLoanDecisionSerializer` to the assembler (parity-preserving)

**Files:**
- Modify: `backend/apps/loans/serializers.py:46-74`
- Test: `backend/apps/loans/tests/test_serializer_cf_fields.py` (existing — must still pass), add `backend/apps/loans/tests/test_decision_serializer_adm.py`

- [ ] **Step 1: Write the failing test (new ADM field + parity)**

```python
# backend/apps/loans/tests/test_decision_serializer_adm.py
import pytest
from apps.loans.serializers import CustomerLoanDecisionSerializer
from apps.loans.models import LoanApplication, LoanDecision

pytestmark = pytest.mark.django_db


def _denied_decision(django_user_model):
    user = django_user_model.objects.create_user(username="cust1", password="x", role="customer")
    app = LoanApplication.objects.create(
        applicant=user, annual_income=50000, credit_score=500, loan_amount=30000,
        debt_to_income=5, employment_length=1, purpose="personal", home_ownership="rent",
        status="denied",
    )
    return LoanDecision.objects.create(
        application=app, decision="denied", confidence=0.9,
        shap_values={"credit_score": -0.5}, feature_importances={"credit_score": 0.5},
        counterfactual_results=[{"changes": {"loan_amount": 10000}, "statement": "Reduce your loan amount"}],
    )


def test_serializer_exposes_adm_disclosure(django_user_model):
    data = CustomerLoanDecisionSerializer(_denied_decision(django_user_model)).data
    assert data["adm_disclosure"]["mode"] == "solely_automated"
    assert data["adm_disclosure"]["human_review_right"] is True
    # parity: existing keys still present
    assert data["denial_reasons"][0]["code"] == "R06"
    assert data["reapplication_guidance"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest apps/loans/tests/test_decision_serializer_adm.py -v`
Expected: FAIL — `KeyError: 'adm_disclosure'`.

- [ ] **Step 3: Modify the serializer to delegate to the assembler**

Replace lines 46-74 of `backend/apps/loans/serializers.py` with:

```python
class CustomerLoanDecisionSerializer(serializers.ModelSerializer):
    denial_reasons = serializers.SerializerMethodField()
    reapplication_guidance = serializers.SerializerMethodField()
    counterfactuals = serializers.SerializerMethodField()
    adm_disclosure = serializers.SerializerMethodField()

    class Meta:
        model = LoanDecision
        fields = (
            "id",
            "decision",
            "created_at",
            "denial_reasons",
            "reapplication_guidance",
            "counterfactuals",
            "adm_disclosure",
        )

    def _payload(self, obj):
        # Memoize per-instance so the four method fields share one assembly.
        cached = getattr(obj, "_explanation_payload", None)
        if cached is None:
            from apps.ml_engine.services.decision_explanation import build_explanation_from_decision

            cached = build_explanation_from_decision(obj)
            obj._explanation_payload = cached
        return cached

    def get_denial_reasons(self, obj):
        return self._payload(obj)["denial_reasons"]

    def get_counterfactuals(self, obj):
        return self._payload(obj)["counterfactuals"]

    def get_reapplication_guidance(self, obj):
        return self._payload(obj)["reapplication_guidance"]

    def get_adm_disclosure(self, obj):
        return self._payload(obj)["adm_disclosure"]
```

Then remove the now-unused top-level import at lines 5-8 (`generate_adverse_action_reasons`, `generate_reapplication_guidance`) since the assembler owns them.

- [ ] **Step 4: Run the new test AND the existing parity test**

Run: `docker compose exec backend pytest apps/loans/tests/test_decision_serializer_adm.py apps/loans/tests/test_serializer_cf_fields.py apps/ml_engine/tests/test_cf_integration.py -v`
Expected: all pass (existing `denial_reasons`/`reapplication_guidance` behaviour unchanged; new `adm_disclosure` present).

- [ ] **Step 5: Commit**

```bash
git add backend/apps/loans/serializers.py backend/apps/loans/tests/test_decision_serializer_adm.py
git commit -m "feat(loans): serializer delegates to DecisionExplanation + exposes adm_disclosure"
```

### Task 4: Replace the `human_review_handler` ad-hoc denial string

**Files:**
- Modify: `backend/apps/agents/services/human_review_handler.py:188-213`
- Test: `backend/apps/agents/tests/test_human_review_denial_reasons.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/apps/agents/tests/test_human_review_denial_reasons.py
from apps.agents.services.human_review_handler import build_denial_reason_summary


def test_summary_uses_reason_code_text_not_raw_floats():
    summary = build_denial_reason_summary(
        shap_values={"credit_score": -0.5, "debt_to_income": -0.3},
        feature_importances={"credit_score": 0.5},
    )
    assert "Credit score below minimum" in summary
    assert "0.5" not in summary  # no raw float dump
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest apps/agents/tests/test_human_review_denial_reasons.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_denial_reason_summary'`.

- [ ] **Step 3: Add the helper and use it**

Add to `backend/apps/agents/services/human_review_handler.py` (module level, after imports):

```python
def build_denial_reason_summary(shap_values: dict, feature_importances: dict) -> str:
    """Human-readable denial-reason summary for the marketing/NBO step.

    Uses the shared DecisionExplanation ranking + reason codes instead of the
    old ad-hoc `"feature: 0.123"` float dump.
    """
    from apps.ml_engine.services.reason_codes import generate_adverse_action_reasons

    reasons = generate_adverse_action_reasons(shap_values or {}, "denied")
    if reasons:
        return "; ".join(r["reason"] for r in reasons)
    if feature_importances:
        from apps.ml_engine.services.decision_explanation import ranked_denial_drivers

        drivers = ranked_denial_drivers(
            shap_values=shap_values or {}, feature_importances=feature_importances, max_n=3
        )
        return ", ".join(name.replace("_", " ") for name, _ in drivers)
    return ""
```

Then replace the `elif decision == "denied":` block at lines 188-204 (the `denial_reasons = ""` + try/except float-join) with:

```python
        elif decision == "denied":
            denial_reasons = ""
            try:
                denial_reasons = build_denial_reason_summary(
                    application.decision.shap_values,
                    application.decision.feature_importances,
                )
            except (LoanDecision.DoesNotExist, AttributeError) as exc:
                logger.debug(
                    "denial_feature_importances_missing",
                    extra={
                        "agent_run_id": str(agent_run_id),
                        "application_id": str(application.id),
                        "error": type(exc).__name__,
                    },
                )
```

- [ ] **Step 4: Run the test + existing human-review tests**

Run: `docker compose exec backend pytest apps/agents/tests/test_human_review_denial_reasons.py apps/agents/tests/ -k "human_review or resume" -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/agents/services/human_review_handler.py backend/apps/agents/tests/test_human_review_denial_reasons.py
git commit -m "refactor(agents): human_review denial summary uses shared reason codes"
```

### Task 5: Retire the orphaned `search_counterfactuals`

**Files:**
- Modify: `backend/apps/ml_engine/services/prediction_explanations.py` (remove `search_counterfactuals` + its module-level helpers; keep `compute_conformal_interval`)
- Modify: `backend/apps/ml_engine/tests/test_prediction_explanations.py` (remove the `search_counterfactuals` tests; keep conformal tests)

- [ ] **Step 1: Verify there is no production caller**

Run: `docker compose exec backend grep -rn "search_counterfactuals" apps/ --include="*.py" | grep -v "/tests/" | grep -v "prediction_explanations.py"`
Expected: **no output** (only the definition + tests reference it). If any app-code caller appears, STOP and keep the function instead.

- [ ] **Step 2: Remove the function and its now-unused helpers**

In `backend/apps/ml_engine/services/prediction_explanations.py`:
- Delete `_COUNTERFACTUAL_FEATURE_BOUNDS` and `_DECREASE_IS_BETTER` (lines ~35-56).
- Delete the entire `def search_counterfactuals(...)` (lines ~128-226).
- Update `__all__` to `["compute_conformal_interval"]`.
- Update the module docstring to drop the `search_counterfactuals` bullet.

- [ ] **Step 3: Remove the orphaned tests**

In `backend/apps/ml_engine/tests/test_prediction_explanations.py`, delete every test that calls `search_counterfactuals` and the `from ... import search_counterfactuals`. Keep all `compute_conformal_interval` tests.

- [ ] **Step 4: Run the conformal tests to confirm nothing else broke**

Run: `docker compose exec backend pytest apps/ml_engine/tests/test_prediction_explanations.py -v`
Expected: conformal tests pass; no import errors.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/ml_engine/services/prediction_explanations.py backend/apps/ml_engine/tests/test_prediction_explanations.py
git commit -m "refactor(ml): retire orphaned non-actionable search_counterfactuals"
```

---

## Phase 3 — Contestability (`DecisionReview`)

### Task 6: `DecisionReview` model + migration

**Files:**
- Modify: `backend/apps/loans/models.py` (append `DecisionReview`)
- Migration: `backend/apps/loans/migrations/00XX_decisionreview.py` (generated)
- Test: `backend/apps/loans/tests/test_decision_review_model.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/apps/loans/tests/test_decision_review_model.py
import pytest
from apps.loans.models import LoanApplication, DecisionReview

pytestmark = pytest.mark.django_db


def _app(django_user_model):
    u = django_user_model.objects.create_user(username="c", password="x", role="customer")
    return LoanApplication.objects.create(
        applicant=u, annual_income=50000, credit_score=500, loan_amount=30000,
        debt_to_income=5, employment_length=1, purpose="personal", home_ownership="rent",
        status="denied",
    )


def test_decision_review_defaults_to_requested(django_user_model):
    app = _app(django_user_model)
    review = DecisionReview.objects.create(application=app, requested_by=app.applicant, reason="I disagree")
    assert review.status == DecisionReview.Status.REQUESTED
    assert review.resolved_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest apps/loans/tests/test_decision_review_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'DecisionReview'`.

- [ ] **Step 3: Append the model to `backend/apps/loans/models.py`**

```python
class DecisionReview(models.Model):
    """Customer-initiated request for human review of an automated decision.

    Implements the ADM "right to human review" (Privacy Act APP, Voluntary AI
    Safety Standard contestability guardrail). Deliberately ORTHOGONAL to:
      * the bias-detection escalation queue (model-triggered, bias-only), and
      * `Complaint` (RG 271 grievance + AFCA escalation).
    On `UPHELD` the customer is pointed to the existing Complaint->AFCA path;
    on `OVERTURNED` an officer override re-decides via the locked service in
    `loans/services/decision_review.py`.
    """

    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        UNDER_REVIEW = "under_review", "Under review"
        UPHELD = "upheld", "Decision upheld"
        OVERTURNED = "overturned", "Decision overturned"
        WITHDRAWN = "withdrawn", "Withdrawn by applicant"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(
        LoanApplication, on_delete=models.CASCADE, related_name="decision_reviews"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="decision_reviews"
    )
    reason = models.TextField(help_text="Why the applicant believes the decision is wrong")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.REQUESTED, db_index=True
    )
    assigned_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_decision_reviews",
    )
    resolution_note = models.TextField(blank=True)
    outcome_decision = models.CharField(max_length=20, blank=True, default="")
    sla_deadline = models.DateTimeField(null=True, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]
        indexes = [models.Index(fields=["status", "-requested_at"], name="decisionreview_status_req")]

    def __str__(self):
        return f"DecisionReview {self.id} - {self.get_status_display()}"
```

- [ ] **Step 4: Generate and apply the migration**

```bash
docker compose exec backend python manage.py makemigrations loans
docker compose exec backend python manage.py migrate loans
docker compose exec backend pytest apps/loans/tests/test_decision_review_model.py -v
```
Expected: migration created + applied; test passes.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/loans/models.py backend/apps/loans/migrations/ backend/apps/loans/tests/test_decision_review_model.py
git commit -m "feat(loans): DecisionReview model for ADM contestability"
```

### Task 7: Overturn re-decision service (concurrency-safe)

**Files:**
- Create: `backend/apps/loans/services/__init__.py` (if absent — it exists), `backend/apps/loans/services/decision_review.py`
- Test: `backend/apps/loans/tests/test_decision_review_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/apps/loans/tests/test_decision_review_service.py
import pytest
from apps.loans.models import LoanApplication, LoanDecision, DecisionReview, AuditLog
from apps.loans.services.decision_review import apply_review_outcome

pytestmark = pytest.mark.django_db


def _denied_with_review(django_user_model):
    cust = django_user_model.objects.create_user(username="c", password="x", role="customer", email="c@x.com")
    officer = django_user_model.objects.create_user(username="o", password="x", role="officer")
    app = LoanApplication.objects.create(
        applicant=cust, annual_income=50000, credit_score=500, loan_amount=30000,
        debt_to_income=5, employment_length=1, purpose="personal", home_ownership="rent",
        status="denied",
    )
    LoanDecision.objects.create(application=app, decision="denied", confidence=0.9)
    review = DecisionReview.objects.create(application=app, requested_by=cust, reason="disagree",
                                           status=DecisionReview.Status.UNDER_REVIEW)
    return app, officer, review


def test_uphold_marks_review_and_keeps_denied(django_user_model):
    app, officer, review = _denied_with_review(django_user_model)
    apply_review_outcome(review, officer=officer, outcome="upheld", note="confirmed")
    review.refresh_from_db(); app.refresh_from_db()
    assert review.status == DecisionReview.Status.UPHELD
    assert app.status == "denied"
    assert AuditLog.objects.filter(action="decision_review_resolved", resource_id=str(review.id)).exists()


def test_overturn_approves_and_audits(django_user_model, monkeypatch):
    # Avoid real email send in the unit test
    import apps.loans.services.decision_review as svc
    monkeypatch.setattr(svc, "_send_approval_email", lambda application: None)
    app, officer, review = _denied_with_review(django_user_model)
    apply_review_outcome(review, officer=officer, outcome="overturned", note="manual approve")
    review.refresh_from_db(); app.refresh_from_db()
    assert review.status == DecisionReview.Status.OVERTURNED
    assert app.status == "approved"
    assert app.decision.decision == "approved"


def test_double_resolve_raises(django_user_model):
    app, officer, review = _denied_with_review(django_user_model)
    apply_review_outcome(review, officer=officer, outcome="upheld", note="x")
    with pytest.raises(ValueError):
        apply_review_outcome(review, officer=officer, outcome="overturned", note="y")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest apps/loans/tests/test_decision_review_service.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the service**

```python
# backend/apps/loans/services/decision_review.py
"""Resolve a DecisionReview — uphold (no-op to the loan) or overturn (officer
override -> approve + send approval email). Uses the same locking discipline as
`agents.human_review_handler.resume_after_review` to avoid double-resolution and
respect the FOR-UPDATE-on-nullable-join caveat.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.loans.models import AuditLog, DecisionReview, LoanApplication

logger = logging.getLogger(__name__)

_TERMINAL = {DecisionReview.Status.UPHELD, DecisionReview.Status.OVERTURNED, DecisionReview.Status.WITHDRAWN}


def _send_approval_email(application) -> None:
    """Re-generate + send the approval email after an overturn. Best-effort:
    a delivery failure must not roll back the approved decision."""
    try:
        from apps.email_engine.services.email_generator import EmailGenerator
        from apps.email_engine.services.persistence import EmailPersistenceService
        from apps.email_engine.services.sender import send_decision_email

        result = EmailGenerator().generate(application, "approved", confidence=application.decision.confidence)
        generated = EmailPersistenceService.save_generated_email(application, "approved", result)
        EmailPersistenceService.save_guardrail_logs(generated, result.get("guardrail_results", []))
        recipient = application.applicant.email
        if recipient and result.get("passed_guardrails"):
            send_decision_email(recipient, result["subject"], result["body"], email_type="approval")
    except Exception:  # noqa: BLE001 — email is best-effort post-override
        logger.exception("Approval email after overturn failed for application %s", application.id)


def apply_review_outcome(review: DecisionReview, *, officer, outcome: str, note: str) -> DecisionReview:
    if outcome not in ("upheld", "overturned"):
        raise ValueError(f"Invalid outcome {outcome!r}")

    with transaction.atomic():
        locked = DecisionReview.objects.select_for_update().get(pk=review.pk)
        if locked.status in _TERMINAL:
            raise ValueError(f"DecisionReview already resolved ({locked.status})")

        locked.assigned_officer = officer
        locked.resolution_note = note
        locked.resolved_at = timezone.now()

        if outcome == "upheld":
            locked.status = DecisionReview.Status.UPHELD
            locked.save(update_fields=["assigned_officer", "resolution_note", "resolved_at", "status"])
            application = locked.application
        else:
            locked.status = DecisionReview.Status.OVERTURNED
            locked.outcome_decision = "approved"
            locked.save(update_fields=[
                "assigned_officer", "resolution_note", "resolved_at", "status", "outcome_decision",
            ])
            application = LoanApplication.objects.select_for_update().get(pk=locked.application_id)
            application.decision.decision = "approved"
            application.decision.reasoning = (
                f"Officer override via decision review {locked.id}: {note}".strip()
            )
            application.decision.save(update_fields=["decision", "reasoning"])
            # denied -> processing -> approved (validated transitions, each audited)
            application.transition_to("processing", user=officer, details={"source": "decision_review_overturn"})
            application.transition_to("approved", user=officer, details={"source": "decision_review_overturn"})

        AuditLog.objects.create(
            user=officer,
            action="decision_review_resolved",
            resource_type="DecisionReview",
            resource_id=str(locked.id),
            details={"outcome": outcome, "application_id": str(locked.application_id)},
        )

    if outcome == "overturned":
        _send_approval_email(application)

    return locked
```

- [ ] **Step 4: Run the test**

Run: `docker compose exec backend pytest apps/loans/tests/test_decision_review_service.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/loans/services/decision_review.py backend/apps/loans/tests/test_decision_review_service.py
git commit -m "feat(loans): concurrency-safe DecisionReview overturn re-decision service"
```

### Task 8: Serializer + viewset + throttle + URL + settings flag

**Files:**
- Modify: `backend/apps/loans/serializers.py` (append `DecisionReviewSerializer`)
- Modify: `backend/apps/loans/views.py` (append `DecisionReviewFilingThrottle`, `DecisionReviewViewSet`)
- Modify: `backend/apps/loans/urls.py` (register route)
- Modify: `backend/config/settings/base.py` (add `DECISION_REVIEW_ENABLED = env.bool(..., default=True)` + throttle scope)
- Test: `backend/apps/loans/tests/test_decision_review_api.py`

- [ ] **Step 1: Write the failing API test**

```python
# backend/apps/loans/tests/test_decision_review_api.py
import pytest
from rest_framework.test import APIClient
from apps.loans.models import LoanApplication, LoanDecision, DecisionReview

pytestmark = pytest.mark.django_db


def _denied_app(django_user_model):
    cust = django_user_model.objects.create_user(username="c", password="x", role="customer", email="c@x.com")
    app = LoanApplication.objects.create(
        applicant=cust, annual_income=50000, credit_score=500, loan_amount=30000,
        debt_to_income=5, employment_length=1, purpose="personal", home_ownership="rent", status="denied",
    )
    LoanDecision.objects.create(application=app, decision="denied", confidence=0.9)
    return cust, app


def test_customer_can_file_review_on_own_denied_app(django_user_model):
    cust, app = _denied_app(django_user_model)
    client = APIClient(); client.force_authenticate(cust)
    r = client.post("/api/v1/loans/decision-reviews/", {"application": str(app.id), "reason": "disagree"}, format="json")
    assert r.status_code == 201
    assert DecisionReview.objects.filter(application=app, requested_by=cust).count() == 1


def test_cannot_file_on_non_denied(django_user_model):
    cust, app = _denied_app(django_user_model)
    app.status = "approved"; app.save(update_fields=["status"])
    client = APIClient(); client.force_authenticate(cust)
    r = client.post("/api/v1/loans/decision-reviews/", {"application": str(app.id), "reason": "x"}, format="json")
    assert r.status_code == 400


def test_duplicate_open_review_blocked(django_user_model):
    cust, app = _denied_app(django_user_model)
    client = APIClient(); client.force_authenticate(cust)
    client.post("/api/v1/loans/decision-reviews/", {"application": str(app.id), "reason": "a"}, format="json")
    r = client.post("/api/v1/loans/decision-reviews/", {"application": str(app.id), "reason": "b"}, format="json")
    assert r.status_code == 400


def test_officer_resolve_overturn(django_user_model, monkeypatch):
    import apps.loans.services.decision_review as svc
    monkeypatch.setattr(svc, "_send_approval_email", lambda application: None)
    cust, app = _denied_app(django_user_model)
    officer = django_user_model.objects.create_user(username="o", password="x", role="officer")
    review = DecisionReview.objects.create(application=app, requested_by=cust, reason="x")
    client = APIClient(); client.force_authenticate(officer)
    r = client.post(f"/api/v1/loans/decision-reviews/{review.id}/resolve/",
                    {"outcome": "overturned", "note": "approve"}, format="json")
    assert r.status_code == 200
    app.refresh_from_db()
    assert app.status == "approved"


def test_customer_cannot_resolve(django_user_model):
    cust, app = _denied_app(django_user_model)
    review = DecisionReview.objects.create(application=app, requested_by=cust, reason="x")
    client = APIClient(); client.force_authenticate(cust)
    r = client.post(f"/api/v1/loans/decision-reviews/{review.id}/resolve/",
                    {"outcome": "upheld", "note": "n"}, format="json")
    assert r.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest apps/loans/tests/test_decision_review_api.py -v`
Expected: FAIL — 404 (route not registered).

- [ ] **Step 3a: Add the serializer** (append to `backend/apps/loans/serializers.py`)

```python
class DecisionReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = DecisionReview
        fields = (
            "id", "application", "reason", "status", "resolution_note",
            "outcome_decision", "requested_at", "resolved_at",
        )
        read_only_fields = (
            "id", "status", "resolution_note", "outcome_decision", "requested_at", "resolved_at",
        )

    def validate(self, attrs):
        request = self.context["request"]
        user = request.user
        application = attrs["application"]
        if application.applicant_id != user.id:
            raise serializers.ValidationError("You can only request a review of your own application.")
        if application.status != "denied":
            raise serializers.ValidationError("Reviews can only be requested on declined applications.")
        from .models import DecisionReview as _DR
        open_states = (_DR.Status.REQUESTED, _DR.Status.UNDER_REVIEW)
        if application.decision_reviews.filter(status__in=open_states).exists():
            raise serializers.ValidationError("A review is already in progress for this application.")
        return attrs

    def create(self, validated_data):
        from datetime import timedelta
        from django.utils import timezone

        request = self.context["request"]
        validated_data["requested_by"] = request.user
        validated_data["sla_deadline"] = timezone.now() + timedelta(days=21)
        instance = super().create(validated_data)
        AuditLog.objects.create(
            user=request.user,
            action="decision_review_requested",
            resource_type="DecisionReview",
            resource_id=str(instance.id),
            details={"application_id": str(instance.application_id)},
            ip_address=request.META.get("REMOTE_ADDR"),
        )
        return instance
```

Add `DecisionReview` to the model import at the top of `serializers.py` (`from .models import AuditLog, Complaint, DecisionReview, FraudCheck, LoanApplication, LoanDecision`).

- [ ] **Step 3b: Add the viewset + throttle** (append to `backend/apps/loans/views.py`)

```python
from rest_framework.decorators import action
from .models import DecisionReview
from .serializers import DecisionReviewSerializer
from .services.decision_review import apply_review_outcome


class DecisionReviewFilingThrottle(UserRateThrottle):
    scope = "decision_review_filing"
    rate = "10/hour"


class DecisionReviewViewSet(viewsets.ModelViewSet):
    """Customers file/view their own decision reviews; staff view all + resolve."""

    serializer_class = DecisionReviewSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        qs = DecisionReview.objects.select_related("application", "requested_by")
        if user.role in ("admin", "officer"):
            return qs.all()
        return qs.filter(requested_by=user)

    def get_throttles(self):
        if self.action == "create":
            return [DecisionReviewFilingThrottle()]
        return super().get_throttles()

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated, IsAdminOrOfficer])
    def resolve(self, request, pk=None):
        review = self.get_object()
        outcome = request.data.get("outcome")
        note = request.data.get("note", "")
        if outcome not in ("upheld", "overturned"):
            return Response({"detail": "outcome must be 'upheld' or 'overturned'"}, status=400)
        try:
            apply_review_outcome(review, officer=request.user, outcome=outcome, note=note)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(DecisionReviewSerializer(review, context={"request": request}).data)
```

- [ ] **Step 3c: Register the route** in `backend/apps/loans/urls.py` (after the complaints line):

```python
router.register(r"decision-reviews", views.DecisionReviewViewSet, basename="decision-review")
```

- [ ] **Step 3d: Add the settings flag + throttle scope** in `backend/config/settings/base.py`

Add near other feature flags: `DECISION_REVIEW_ENABLED = env.bool("DECISION_REVIEW_ENABLED", default=True)`.
In the `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]` dict add: `"decision_review_filing": "10/hour",`.

- [ ] **Step 4: Run the API tests**

Run: `docker compose exec backend pytest apps/loans/tests/test_decision_review_api.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/loans/serializers.py backend/apps/loans/views.py backend/apps/loans/urls.py backend/config/settings/base.py backend/apps/loans/tests/test_decision_review_api.py
git commit -m "feat(loans): DecisionReview API — file (throttled) + officer resolve"
```

### Task 9: Django admin for officer resolution

**Files:**
- Modify: `backend/apps/loans/admin.py`
- Test: `backend/apps/loans/tests/test_decision_review_admin.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/apps/loans/tests/test_decision_review_admin.py
import pytest
from django.contrib.admin.sites import site
from apps.loans.models import DecisionReview

pytestmark = pytest.mark.django_db


def test_decision_review_registered_with_resolve_actions():
    model_admin = site._registry[DecisionReview]
    action_names = {a.__name__ if callable(a) else a for a in model_admin.actions}
    assert "mark_overturned" in action_names
    assert "mark_upheld" in action_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest apps/loans/tests/test_decision_review_admin.py -v`
Expected: FAIL — `KeyError: DecisionReview` not in registry.

- [ ] **Step 3: Register the admin with actions**

Add to `backend/apps/loans/admin.py` (import `DecisionReview` and `apply_review_outcome`):

```python
from .models import DecisionReview
from .services.decision_review import apply_review_outcome


@admin.register(DecisionReview)
class DecisionReviewAdmin(admin.ModelAdmin):
    list_display = ("id", "application", "requested_by", "status", "assigned_officer", "requested_at")
    list_filter = ("status",)
    search_fields = ("application__id", "requested_by__username", "reason")
    readonly_fields = ("id", "application", "requested_by", "reason", "requested_at", "resolved_at")
    actions = ["mark_upheld", "mark_overturned"]

    @admin.action(description="Uphold selected decisions (no change to loan)")
    def mark_upheld(self, request, queryset):
        done = 0
        for review in queryset:
            try:
                apply_review_outcome(review, officer=request.user, outcome="upheld",
                                     note="Resolved via Django admin")
                done += 1
            except ValueError as exc:
                self.message_user(request, f"{review.id}: {exc}", level=messages.WARNING)
        self.message_user(request, f"{done} review(s) upheld.", level=messages.SUCCESS)

    @admin.action(description="Overturn selected decisions (officer override -> approve)")
    def mark_overturned(self, request, queryset):
        done = 0
        for review in queryset:
            try:
                apply_review_outcome(review, officer=request.user, outcome="overturned",
                                     note="Overturned via Django admin")
                done += 1
            except ValueError as exc:
                self.message_user(request, f"{review.id}: {exc}", level=messages.WARNING)
        self.message_user(request, f"{done} decision(s) overturned + approval email queued.",
                          level=messages.SUCCESS)
```

- [ ] **Step 4: Run the test**

Run: `docker compose exec backend pytest apps/loans/tests/test_decision_review_admin.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/loans/admin.py backend/apps/loans/tests/test_decision_review_admin.py
git commit -m "feat(loans): Django admin actions to resolve DecisionReviews"
```

---

## Phase 4 — Frontend (customer surfaces)

### Task 10: Types + API hooks

**Files:**
- Modify: `frontend/src/types/index.ts` (add `AdmDisclosure`, `DecisionReview`; extend decision type)
- Create: `frontend/src/hooks/useDecisionReview.ts`
- Test: `frontend/src/__tests__/hooks/useDecisionReview.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/__tests__/hooks/useDecisionReview.test.tsx
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useRequestDecisionReview } from '@/hooks/useDecisionReview'

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

it('exposes a mutation to request a review', () => {
  const { result } = renderHook(() => useRequestDecisionReview(), { wrapper })
  expect(typeof result.current.mutate).toBe('function')
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- useDecisionReview`
Expected: FAIL — cannot resolve `@/hooks/useDecisionReview`.

- [ ] **Step 3: Add types + hook**

In `frontend/src/types/index.ts` add:

```ts
export interface AdmDisclosure {
  mode: 'solely_automated' | 'assisted' | 'human'
  summary: string
  info_used: string[]
  human_review_right: boolean
  review_request_path: string
}

export interface DecisionReview {
  id: string
  application: string
  reason: string
  status: 'requested' | 'under_review' | 'upheld' | 'overturned' | 'withdrawn'
  resolution_note: string
  outcome_decision: string
  requested_at: string
  resolved_at: string | null
}
```

Extend the existing decision interface (the one feeding `application.decision`) to add `adm_disclosure?: AdmDisclosure`.

Create `frontend/src/hooks/useDecisionReview.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { DecisionReview } from '@/types'

export function useRequestDecisionReview() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (vars: { application: string; reason: string }) => {
      const { data } = await api.post<DecisionReview>('/loans/decision-reviews/', vars)
      return data
    },
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: ['decision-review', vars.application] })
    },
  })
}

export function useDecisionReview(applicationId: string) {
  return useQuery({
    queryKey: ['decision-review', applicationId],
    queryFn: async () => {
      const { data } = await api.get<{ results: DecisionReview[] }>('/loans/decision-reviews/')
      return (data.results ?? []).find((r) => r.application === applicationId) ?? null
    },
  })
}
```

(Match the project's actual axios instance import — confirm it is `@/lib/api`; if the codebase exposes named methods, mirror the pattern used in `frontend/src/hooks/useApplications.ts`.)

- [ ] **Step 4: Run the test**

Run: `cd frontend && npm test -- useDecisionReview`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/hooks/useDecisionReview.ts frontend/src/__tests__/hooks/useDecisionReview.test.tsx
git commit -m "feat(frontend): types + hooks for decision reviews + ADM disclosure"
```

### Task 11: `DecisionReviewStatus` + ADM line + Request-review CTA in `DenialExplanationPanel`

**Files:**
- Create: `frontend/src/components/applications/DecisionReviewStatus.tsx`
- Modify: `frontend/src/components/applications/DenialExplanationPanel.tsx`
- Modify: `frontend/src/app/apply/status/[id]/page.tsx:292-299` (pass `admDisclosure` + `applicationId`)
- Test: extend `frontend/src/__tests__/components/denial-explanation-panel.test.tsx`

- [ ] **Step 1: Write the failing test (ADM line + CTA render)**

```tsx
// add to denial-explanation-panel.test.tsx
it('shows the ADM disclosure line and a request-review CTA', () => {
  render(
    <DenialExplanationPanel
      {...defaultProps}
      applicationId="app-1"
      admDisclosure={{
        mode: 'solely_automated',
        summary: 'Declined by our automated credit-decision model.',
        info_used: ['Income'],
        human_review_right: true,
        review_request_path: '/api/v1/loans/decision-reviews/',
      }}
    />
  )
  expect(screen.getByText(/automated credit-decision model/i)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /request a human review/i })).toBeInTheDocument()
})
```

(Wrap the render in the QueryClientProvider helper already used by other hook-driven component tests.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- denial-explanation-panel`
Expected: FAIL — no ADM text / button.

- [ ] **Step 3: Implement the components**

Create `frontend/src/components/applications/DecisionReviewStatus.tsx`:

```tsx
'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ShieldQuestion } from 'lucide-react'
import { useRequestDecisionReview, useDecisionReview } from '@/hooks/useDecisionReview'

const STATUS_LABEL: Record<string, string> = {
  requested: 'Requested — awaiting a lending officer',
  under_review: 'Under review by a lending officer',
  upheld: 'Reviewed — the original decision stands',
  overturned: 'Reviewed — decision overturned, your application was approved',
  withdrawn: 'Withdrawn',
}

export function DecisionReviewStatus({ applicationId }: { applicationId: string }) {
  const { data: review } = useDecisionReview(applicationId)
  const requestReview = useRequestDecisionReview()
  const [reason, setReason] = useState('')

  if (review) {
    return (
      <Card role="region" aria-label="Human review status">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <ShieldQuestion className="h-5 w-5 text-blue-500" />
            Human review
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm">{STATUS_LABEL[review.status] ?? review.status}</p>
          {review.status === 'upheld' && (
            <p className="text-xs text-muted-foreground mt-2">
              If you remain dissatisfied you can lodge a formal complaint with AFCA — see{' '}
              <a href="/rights" className="underline">Your Rights</a>.
            </p>
          )}
        </CardContent>
      </Card>
    )
  }

  return (
    <Card role="region" aria-label="Request a human review">
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <ShieldQuestion className="h-5 w-5 text-blue-500" />
          Request a human review
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <Textarea
          aria-label="Why do you think this decision is wrong?"
          placeholder="Tell us why you think this decision should be reviewed (optional)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
        <Button
          onClick={() => requestReview.mutate({ application: applicationId, reason })}
          disabled={requestReview.isPending}
        >
          {requestReview.isPending ? 'Submitting…' : 'Request a human review'}
        </Button>
      </CardContent>
    </Card>
  )
}
```

In `DenialExplanationPanel.tsx`: extend props with `applicationId: string` and `admDisclosure?: AdmDisclosure | null`; after Card 1 (denial reasons) render an ADM disclosure line when present:

```tsx
{admDisclosure && (
  <p className="text-xs text-muted-foreground">
    {admDisclosure.summary}{' '}
    {admDisclosure.human_review_right && 'You have the right to request a human review.'}
  </p>
)}
```

and render `<DecisionReviewStatus applicationId={applicationId} />` as the final block (replacing the bare "Talk to a specialist" button's role). Keep the existing AFCA link.

- [ ] **Step 4: Wire the status page** — update `apply/status/[id]/page.tsx:292-299`:

```tsx
{application.status === 'denied' && application.decision && (
  <DenialExplanationPanel
    denialReasons={application.decision.denial_reasons || []}
    counterfactuals={application.decision.counterfactuals || []}
    reapplicationGuidance={application.decision.reapplication_guidance || null}
    creditScore={application.credit_score}
    applicationId={application.id}
    admDisclosure={application.decision.adm_disclosure || null}
  />
)}
```

- [ ] **Step 5: Run tests + commit**

Run: `cd frontend && npm test -- denial-explanation-panel DecisionReviewStatus`
Expected: pass.

```bash
git add frontend/src/components/applications/DecisionReviewStatus.tsx frontend/src/components/applications/DenialExplanationPanel.tsx "frontend/src/app/apply/status/[id]/page.tsx" frontend/src/__tests__/components/denial-explanation-panel.test.tsx
git commit -m "feat(frontend): ADM disclosure + request-human-review on denial panel"
```

### Task 12: ADM register section on `/rights`

**Files:**
- Modify: `frontend/src/app/rights/page.tsx` (add a "How automated decisions are made" card after the existing "How We Assess" card)
- Test: `frontend/src/__tests__/app/rights-adm.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/__tests__/app/rights-adm.test.tsx
import { render, screen } from '@testing-library/react'
import ConsumerRightsPage from '@/app/rights/page'

it('discloses automated decision-making and the right to human review', () => {
  render(<ConsumerRightsPage />)
  expect(screen.getByText(/automated decision-making/i)).toBeInTheDocument()
  expect(screen.getByText(/request a human review/i)).toBeInTheDocument()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- rights-adm`
Expected: FAIL — text not present.

- [ ] **Step 3: Add the card** (after the "How We Assess Your Application" card in `rights/page.tsx`)

```tsx
{/* Automated Decision-Making */}
<Card>
  <CardHeader>
    <CardTitle className="flex items-center gap-2">
      <Scale className="h-5 w-5 text-blue-600" />
      Automated Decision-Making
    </CardTitle>
  </CardHeader>
  <CardContent className="space-y-3 text-sm leading-relaxed">
    <p>
      Most decisions are made <strong>solely by an automated credit-decision model</strong>.
      Applications flagged for potential bias, low model confidence, or significant data
      shifts are <strong>reviewed by a lending officer</strong> (an assisted decision).
    </p>
    <p>The information used includes:</p>
    <ul className="list-disc pl-6 space-y-1">
      <li>Income and employment details you provided</li>
      <li>Credit report and repayment history (Equifax/Illion, CCR)</li>
      <li>Existing debts, expenses and serviceability under an interest-rate buffer</li>
      <li>Loan amount, term and purpose</li>
    </ul>
    <p>
      If your application was declined, you have the right to{' '}
      <strong>request a human review</strong> of the decision from your application status
      page. This is in addition to your right to lodge a complaint with AFCA.
    </p>
  </CardContent>
</Card>
```

- [ ] **Step 4: Run test + commit**

Run: `cd frontend && npm test -- rights-adm`
Expected: pass.

```bash
git add frontend/src/app/rights/page.tsx frontend/src/__tests__/app/rights-adm.test.tsx
git commit -m "feat(frontend): ADM disclosure section on /rights (Privacy Act APP 1.7-1.9)"
```

---

## Phase 5 — End-to-end + verification

### Task 13: E2E smoke extension

**Files:**
- Modify: `tools/smoke_e2e.sh` (add a decline→request-review→overturn→approval leg, guarded so it no-ops if `DECISION_REVIEW_ENABLED` is false)
- Test: manual run

- [ ] **Step 1: Add the review leg to the smoke script**

After the decision step, when the decision is `denied`, POST a review request as the customer, then resolve it as admin via the API, and assert the application flips to `approved`. Use the existing `curl` + token helpers in the script. Write the outcome into `.tmp/smoke_result.json` under a new `decision_review` key.

- [ ] **Step 2: Run the full smoke locally**

```bash
docker compose up -d
make seed
tools/smoke_e2e.sh
```
Expected: `.tmp/smoke_result.json` shows `"status": "success"` and a populated `decision_review` block.

- [ ] **Step 3: Commit**

```bash
git add tools/smoke_e2e.sh
git commit -m "test(e2e): smoke covers decision-review overturn leg"
```

### Task 14: Full backend + frontend suite + lint

**Files:** none (verification)

- [ ] **Step 1: Backend suite + coverage floor**

Run: `docker compose exec backend pytest tests/ apps/ -q`
Expected: all pass; coverage ≥ 60% floor holds.

- [ ] **Step 2: Lint + type gates**

```bash
docker compose exec backend ruff check apps/
docker compose exec backend ruff format --check apps/
cd frontend && npm run lint && npm test
```
Expected: clean.

- [ ] **Step 3: Final commit (if lint fixups needed)**

```bash
git add -A
git commit -m "chore: lint + format for decision transparency feature"
```

---

## Self-Review (plan vs. spec)

**Spec coverage:**
- §3 Component 1 (unify explanation) → Tasks 2, 3, 4 + retire orphan Task 5. ✅ (email path deferred — documented refinement.)
- §4 Component 2 (`DecisionReview`) → Tasks 6 (model), 7 (overturn service), 8 (API), 9 (admin). ✅
- §5 Component 3 (ADM disclosure) → Task 1 (register), 3 (per-decision in payload), 11 (panel), 12 (rights). ✅
- §6 Frontend → Tasks 10, 11, 12. ✅
- §8 error handling → Task 7 (double-resolve 409), Task 8 (non-denied 400, duplicate 400). ✅
- §9 testing → unit (1,2,3,4,6,7), API (8), admin (9), frontend (10,11,12), e2e (13). ✅
- §11 flag + branch → Task 0 (branch), Task 8 (`DECISION_REVIEW_ENABLED`). ✅

**Placeholder scan:** No TBD/TODO; every code step has concrete code. Migration generated via `makemigrations` (correct mechanism, not a placeholder).

**Type consistency:** `apply_review_outcome(review, *, officer, outcome, note)`, `build_explanation_payload(...)`, `ranked_denial_drivers(...)`, `resolve_adm_disclosure(decision=, requires_human_review=)`, `DecisionReview.Status`, `useRequestDecisionReview`/`useDecisionReview`, `adm_disclosure` key — consistent across backend and frontend tasks.

**Known assumptions to verify during execution (not blockers):**
- Frontend axios import path (`@/lib/api`) and the exact decision interface name in `types/index.ts` — confirm against `useApplications.ts` before editing.
- `env.bool` settings helper exists in `config/settings/base.py` (the repo uses environ-style config) — match the existing flag-reading pattern.
- A `Textarea` shadcn component exists; if not, add via the project's shadcn workflow or use a styled `<textarea>`.
