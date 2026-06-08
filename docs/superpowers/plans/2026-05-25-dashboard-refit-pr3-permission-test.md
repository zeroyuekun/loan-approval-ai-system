# Dashboard refit PR-3 — cross-customer permission regression test

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the one outstanding acceptance criterion from Change 3 of the dashboard persona refit spec — "permission test confirms cross-customer access is forbidden" — by adding a regression test that exercises the customer-detail endpoint with two customers and asserts that customer B cannot retrieve customer A's counterfactuals.

**Architecture:** All of the Change 3 functional work is already shipped in master (verified during reconnaissance — see "Background" below). What's missing is a regression test for the queryset isolation that already exists at `backend/apps/loans/views.py:64` (`qs.filter(applicant=user)`). This PR adds two tests against the live API client: cross-customer (negative — expect 404) and own-customer (positive — expect 200 with counterfactuals visible). One file, one commit, one push.

**Tech Stack:** pytest-django, DRF's `APIClient`, the existing `CustomerLoanApplicationSerializer` chain.

**Source spec:** [`docs/superpowers/specs/2026-05-25-dashboard-persona-refit-design.md`](../specs/2026-05-25-dashboard-persona-refit-design.md) — Change 3, acceptance criterion #2.

---

## Background — why this is so small

Reconnaissance against the current code (2026-05-25, branch `feat/dashboard-persona-refit-pr2-status-strip`) found Change 3 is already shipped:

- `CustomerLoanDecisionSerializer.counterfactuals` field already returns `obj.counterfactual_results or []` for denied applications (`backend/apps/loans/serializers.py:49,65-67`).
- `LoanApplicationViewSet.get_serializer_class()` already routes customer-role retrieves to `CustomerLoanApplicationSerializer` → `CustomerLoanDecisionSerializer` (`backend/apps/loans/views.py:50-57`).
- `LoanApplicationViewSet.get_queryset()` already isolates customers to their own applications via `qs.filter(applicant=user)` (`backend/apps/loans/views.py:59-64`).
- Customer status page already renders `<DenialExplanationPanel counterfactuals={...} />` on denial (`frontend/src/app/apply/status/[id]/page.tsx:295`).
- `DenialExplanationPanel` already renders the "Try this and reapply" card with disclaimer (`frontend/src/components/applications/DenialExplanationPanel.tsx:70-91`).
- Serializer unit tests cover denied / approved / guidance paths (`backend/apps/loans/tests/test_serializer_cf_fields.py`).
- Component tests cover panel rendering (`frontend/src/__tests__/components/denial-explanation-panel.test.tsx`).

The one gap: nothing tests **the endpoint with auth** to confirm that customer B cannot retrieve customer A's `decision.counterfactuals`. That's what this PR adds.

---

## Branch setup

This PR stacks on PR-2. Before Task 1 begins, the executor creates the PR-3 branch off PR-2's HEAD:

```bash
git switch feat/dashboard-persona-refit-pr2-status-strip   # PR-2 branch
git switch -c feat/dashboard-persona-refit-pr3-permission-test
```

All commits land on `feat/dashboard-persona-refit-pr3-permission-test`.

---

## File map

**Backend — create:**
- `backend/apps/loans/tests/test_customer_loan_permissions.py` — new test file with two cases.

**Backend — no source changes.** The behaviour under test already exists. These are regression / safety-net tests.

---

## Task 1: Cross-customer permission regression test

**Files:**
- Create: `backend/apps/loans/tests/test_customer_loan_permissions.py`

This is a TWO-case test: one negative (cross-customer access denied), one positive (own access works). Both must pass. The plan calls this "TDD red→green" loosely — in practice both tests will pass on first run because the underlying behaviour already exists in production; the value is *catching regressions* if someone later relaxes `get_queryset` or removes the customer-only serializer routing.

- [ ] **Step 1.1: Confirm branch state**

```bash
git branch --show-current
# Expected output: feat/dashboard-persona-refit-pr3-permission-test
git log --oneline -3
# Expected: top commit is "feat(dashboard): wire StatusStrip; delete approval-rate donut" (4a0cc83 or similar)
```

- [ ] **Step 1.2: Write the test file (full file content)**

Create `backend/apps/loans/tests/test_customer_loan_permissions.py`:

```python
"""Cross-customer permission regression tests for the loan-detail endpoint.

Verifies that:
  1. Customer A cannot retrieve customer B's loan application via the
     standard GET /api/v1/loans/{id}/ retrieve action. The queryset
     isolation at LoanApplicationViewSet.get_queryset() filters by
     applicant=request.user, so cross-customer requests return 404
     (not 403 — the resource is invisible, not forbidden).
  2. Customer A CAN retrieve their own denied application, and the
     response includes the counterfactuals serialized by
     CustomerLoanDecisionSerializer.

Closes the Change 3 acceptance criterion from the dashboard persona
refit spec (docs/superpowers/specs/2026-05-25-dashboard-persona-refit-design.md).
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.loans.models import LoanApplication, LoanDecision

User = get_user_model()


@pytest.fixture
def customer_a(db):
    return User.objects.create_user(
        username="customer_a",
        password="test1234",
        email="a@aussieloanai.test",
        role="customer",
    )


@pytest.fixture
def customer_b(db):
    return User.objects.create_user(
        username="customer_b",
        password="test1234",
        email="b@aussieloanai.test",
        role="customer",
    )


@pytest.fixture
def denied_app_for_a(customer_a):
    """A denied LoanApplication owned by customer_a, with attached LoanDecision
    carrying counterfactual_results. Mirrors the shape PR-1's counterfactual
    pipeline emits.
    """
    app = LoanApplication.objects.create(
        applicant=customer_a,
        annual_income=Decimal("50000"),
        credit_score=520,
        loan_amount=Decimal("100000"),
        loan_term_months=36,
        debt_to_income=Decimal("6.0"),
        employment_length=2,
        purpose="home",
        home_ownership="rent",
        status="denied",
    )
    LoanDecision.objects.create(
        application=app,
        decision="denied",
        confidence=0.3,
        shap_values={"credit_score": -0.4, "debt_to_income": -0.3},
        counterfactual_results=[
            {"changes": {"loan_amount": 50000.0}, "statement": "Reduce loan to $50,000"},
            {"changes": {"loan_term_months": 60}, "statement": "Extend term to 60 months"},
        ],
    )
    return app


@pytest.mark.django_db
class TestCustomerLoanDetailPermissions:
    """End-to-end auth tests against the live LoanApplicationViewSet retrieve action."""

    def test_customer_b_cannot_retrieve_customer_a_loan(self, customer_b, denied_app_for_a):
        client = APIClient()
        client.force_authenticate(user=customer_b)
        # Customer A's app id, requested by customer B
        response = client.get(f"/api/v1/loans/{denied_app_for_a.id}/")
        # Queryset filter makes the resource invisible, so the API returns 404
        # not 403. This is the standard Django REST pattern for object-level
        # isolation and matches what get_queryset() implements at views.py:64.
        assert response.status_code == 404

    def test_customer_b_cannot_see_a_counterfactuals_via_list(self, customer_b, denied_app_for_a):
        """Even on the list endpoint, customer B's queryset is filtered
        to their own applications — none of customer A's data leaks
        into the paginated results.
        """
        client = APIClient()
        client.force_authenticate(user=customer_b)
        response = client.get("/api/v1/loans/")
        assert response.status_code == 200
        body = response.json()
        # Customer B has no applications of their own and cannot see A's
        results = body.get("results", body) if isinstance(body, dict) else body
        assert results == []  # or count == 0 on paginated payloads
        if isinstance(body, dict) and "count" in body:
            assert body["count"] == 0

    def test_customer_a_can_retrieve_own_denied_app_with_counterfactuals(
        self, customer_a, denied_app_for_a
    ):
        client = APIClient()
        client.force_authenticate(user=customer_a)
        response = client.get(f"/api/v1/loans/{denied_app_for_a.id}/")
        assert response.status_code == 200
        body = response.json()
        # CustomerLoanApplicationSerializer chains to
        # CustomerLoanDecisionSerializer for the decision field
        decision = body.get("decision")
        assert decision is not None
        assert decision["decision"] == "denied"
        # The counterfactuals serializer-method-field surfaces the JSON.
        # Spec acceptance: denied customer sees actionable counterfactuals.
        assert "counterfactuals" in decision
        assert len(decision["counterfactuals"]) == 2
        statements = [cf["statement"] for cf in decision["counterfactuals"]]
        assert "Reduce loan to $50,000" in statements
        assert "Extend term to 60 months" in statements

    def test_unauthenticated_request_is_rejected(self, denied_app_for_a):
        """Sanity-check: no auth → 401/403 (DRF default), never 200."""
        client = APIClient()
        response = client.get(f"/api/v1/loans/{denied_app_for_a.id}/")
        assert response.status_code in (401, 403)
```

- [ ] **Step 1.3: Run the new test file**

Run:

```bash
docker compose exec backend pytest apps/loans/tests/test_customer_loan_permissions.py -v
```

Expected: all 4 cases pass. The two "cannot" tests pass because the existing `get_queryset` filter already enforces isolation; the "can retrieve own" test passes because the existing serializer routing already exposes counterfactuals to the owner. If any test fails — STOP and report; the failure means a real regression (or a bug in this test's fixture data), not a missing feature.

- [ ] **Step 1.4: Run the wider loans suite to confirm no collateral damage**

```bash
docker compose exec backend pytest apps/loans/tests/ -v
```

Expected: previously-green tests still green, plus the 4 new tests. Total should be roughly 30 + 4 = 34 tests (the loans test count after PR-2 was 30).

- [ ] **Step 1.5: Commit**

```bash
git add backend/apps/loans/tests/test_customer_loan_permissions.py
git commit -m "$(cat <<'EOF'
test(loans): cross-customer permission regression for counterfactuals

Adds 4 endpoint-level auth tests against LoanApplicationViewSet:

  - test_customer_b_cannot_retrieve_customer_a_loan — 404 by queryset
    filter (not 403; the resource is invisible, not forbidden)
  - test_customer_b_cannot_see_a_counterfactuals_via_list — list
    endpoint returns empty/0-count for cross-customer caller
  - test_customer_a_can_retrieve_own_denied_app_with_counterfactuals —
    owner sees decision.counterfactuals via CustomerLoanDecisionSerializer
  - test_unauthenticated_request_is_rejected — sanity check

All 4 pass on master because the existing queryset filter at
views.py:64 already enforces isolation and the customer-role
serializer chain already exposes counterfactuals. These are
regression guards — closes the Change 3 acceptance criterion in
docs/superpowers/specs/2026-05-25-dashboard-persona-refit-design.md
("permission test confirms cross-customer access is forbidden").

No source changes; functional surface for Change 3 was already
shipped in prior work (DenialExplanationPanel + serializer fields).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 1.6: Verify commit landed**

```bash
git log --oneline -2
```

Expected: top commit is the new test commit; parent is PR-2's `4a0cc83` (`feat(dashboard): wire StatusStrip; delete approval-rate donut`).

---

## Push + open PR (done by main orchestrator, not subagent)

After Task 1 commits, the main agent pushes the branch and opens the PR — this matches how PR-1 and PR-2 wrapped up. The PR opens against `feat/dashboard-persona-refit-pr2-status-strip` (PR-2's branch) and will be retargeted to master after PR-1 and PR-2 merge per the user's stacked-PR convention.

---

## Self-review notes

**Spec coverage check (PR-3 acceptance criterion):**
- ✅ "permission test confirms cross-customer access is forbidden" — Task 1's first two test methods cover the detail and list endpoints.
- ✅ "denied customer sees actionable counterfactuals on status page" — already shipped; Task 1's third test confirms the API path that feeds the page still works (regression guard).

**Placeholder scan:** no TBDs, no "implement later". The plan is single-task, single-file, single-commit.

**Type consistency:** the fixture data (`counterfactual_results` shape — `{"changes": {...}, "statement": "..."}`) matches what `CounterfactualEngine.generate()` emits and what `DenialExplanationPanel` expects (both verified during reconnaissance).

**Out of scope:** PR-4 (Model Health consolidation), CDR adapter, service decomposition, security gap-closure. Each gets its own foundation spec when its turn comes. PR-3 closes Change 3 of the dashboard persona refit; the refit then has PR-4 left.
