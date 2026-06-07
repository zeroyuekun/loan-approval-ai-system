# Decision Transparency & Contestability — Design Spec

- **Date:** 2026-05-28
- **Status:** Draft (awaiting review)
- **Author:** Neville Zeng (with Claude)
- **Scope:** `backend/apps/ml_engine`, `backend/apps/loans`, `frontend/src` (customer + officer surfaces)

## 1. Motivation

A market scan of Australian AI lenders (CBA, Westpac, MoneyMe, Wisr, Harmoney, Tic:Toc,
Athena) plus the regulatory landscape produced two findings:

1. **Consumer-facing explainability is the rarest capability in the AU market.** Lenders
   compete on *speed* (seconds-to-minutes decisioning) and *open-banking verification*.
   Only Westpac/RDC.ai market "explainable credit decisioning." This system already owns
   the hard parts — `counterfactual_engine`, `shap_attribution`, `reason_codes` (70 codes),
   `adverse_action` — but they are not assembled into a single coherent customer experience,
   and there is **no in-app mechanism to contest an automated decision**.
2. **There is one concrete, dated regulatory requirement this system does not yet meet:**
   the Privacy Act automated-decision-making (ADM) transparency reforms (APP 1.7–1.9),
   which **commence 10 December 2026**. They require disclosing which decisions are
   solely/substantially automated and supporting a right to human review. This maps directly
   to the Voluntary AI Safety Standard's "contestability" and "human oversight" guardrails
   and to ASIC REP 798's expectation that licensees disclose AI use and explain outputs.

The work also resolves a real piece of technical debt surfaced during design: denial-reason
and counterfactual logic is **duplicated across at least five sites**.

### Current duplication (the cleanup target)

| Site | What it does today |
|------|--------------------|
| `loans.serializers.CustomerLoanDecisionSerializer` | Computes `denial_reasons` + `reapplication_guidance` for the customer status page |
| `email_engine.services.email_generator._format_denial_reasons` | Independently formats denial reasons for the email body |
| `agents.services.human_review_handler` (l.190–195) | Ad-hoc `", ".join(f"{k}: {v:.3f}")` denial-reason string |
| `ml_engine.services.counterfactual_engine.CounterfactualEngine` | Counterfactuals over **actionable** features (loan_amount, term, co-signer) |
| `ml_engine.services.prediction_explanations.search_counterfactuals` | Counterfactuals over credit_score/income/DTI — its own docstring calls it "distinct" |

These disagree on *which* features to vary and *how* to phrase reasons. A single source of
truth removes the divergence risk.

## 2. Goals / Non-Goals

### Goals
- Assemble all decision-explanation data behind **one typed contract** consumed by the API
  serializer, the email generator, and the human-review handler.
- Give declined applicants an **in-app "request a human review"** flow with a tracked
  lifecycle and an officer resolution path that can re-decide.
- Disclose **automated decision-making** per-decision and on `/rights`, satisfying APP 1.7–1.9.
- Preserve all current outputs (test-guarded refactor) and add **zero** new LLM/API spend.

### Non-Goals
- Real Consumer Data Right / open-banking integration (requires accreditation).
- Instant-decision / latency re-architecture.
- Refactor of the genuine god-modules (`data_generator` 1565, `trainer` 1334, `metrics`
  1018, `underwriting_engine` 1009, `recommendation_engine` 1002) — tracked separately.
- Any change to the **bias-detection human-review queue** (it stays bias-only, per the
  established product rule) or to scoring/training code paths.

## 3. Component 1 — `DecisionExplanation` (unify the explanation backend)

### New module: `backend/apps/ml_engine/services/decision_explanation.py`

A pure assembler (no Django model writes) that takes a `LoanDecision` (or a live
`prediction_result` dict) and returns a single typed structure:

```python
@dataclass(frozen=True)
class DecisionExplanation:
    decision: str                      # "approved" | "denied"
    confidence: float
    probability: float
    conformal_interval: dict | None    # from prediction_explanations.compute_conformal_interval
    principal_reasons: list[ReasonCode]  # {code, reason, feature} — from reason_codes/adverse_action
    counterfactuals: list[Counterfactual]  # actionable only — ONE strategy
    reapplication_guidance: dict | None
    credit_score_disclosure: dict | None
    adm_disclosure: AdmDisclosure      # see Component 3
    afca_complaint_info: dict          # reuse adverse_action constants
```

### Decisions
- **Counterfactual reconciliation:** `CounterfactualEngine` (actionable features:
  loan_amount, loan_term_months, has_cosigner) is the primary strategy because its outputs
  are things an applicant can actually change. `prediction_explanations.search_counterfactuals`
  is demoted to an explicit, documented fallback *inside* `DecisionExplanation` (used only
  when the primary yields nothing), not a parallel public path. No behaviour is silently
  dropped; the fallback ordering is unit-tested.
- **Reason codes:** wrap the existing `adverse_action.generate_adverse_action_notice(...)`
  rather than re-deriving — it already composes `principal_reasons`, `reapplication_guidance`,
  AFCA info, and AU right-to-request text. `DecisionExplanation` becomes the typed face of it.
- **Consumers refactored to call the assembler:**
  - `CustomerLoanDecisionSerializer` → returns `DecisionExplanation` fields (same JSON keys
    the frontend already reads: `denial_reasons`, `reapplication_guidance`, plus new
    `adm_disclosure`).
  - `email_generator._format_denial_reasons` → delegates to the assembler's `principal_reasons`.
  - `human_review_handler` denial-reason string → built from the assembler.

### Reuse of existing storage
`LoanDecision` already persists `feature_importances`, `shap_values`, `counterfactual_results`,
`decision_waterfall`, `risk_grade`, `confidence`, `model_version`. The assembler reads these;
**no schema change is required for Component 1.**

## 4. Component 2 — Contestability (`DecisionReview`)

### New model: `backend/apps/loans/models.py :: DecisionReview`

```python
class DecisionReview(models.Model):
    class Status(TextChoices):
        REQUESTED   = "requested",   "Requested"
        UNDER_REVIEW = "under_review","Under review"
        UPHELD      = "upheld",      "Decision upheld"
        OVERTURNED  = "overturned",  "Decision overturned"
        WITHDRAWN   = "withdrawn",   "Withdrawn by applicant"

    id            = UUIDField(pk)
    application   = ForeignKey(LoanApplication, related_name="decision_reviews")
    requested_by  = ForeignKey(AUTH_USER_MODEL)         # the customer
    reason        = TextField()                          # why they think it's wrong
    status        = CharField(choices=Status, default=REQUESTED, db_index=True)
    assigned_officer = ForeignKey(AUTH_USER_MODEL, null=True)
    resolution_note  = TextField(blank=True)
    outcome_decision = CharField(blank=True)             # set on overturn
    requested_at  = DateTimeField(auto_now_add=True)
    resolved_at   = DateTimeField(null=True)
    sla_deadline  = DateTimeField(null=True)             # mirror RG 271 cadence
```

### Why a dedicated model (not `Complaint`, not the bias queue)
The codebase already keeps review workflows **orthogonal** — see the `referral_status`
comment at `loans/models.py:289` ("intentionally orthogonal to the customer-facing bias
review queue"). This design follows that established convention:

- **Bias queue** (`AgentRun` escalation → `human_review_handler`): model-triggered, bias/
  low-confidence/drift only. **Untouched.**
- **`Complaint`** (RG 271 / s.12CM): a *grievance* mechanism with AFCA escalation and a
  resolution SLA. Kept as-is.
- **`DecisionReview`** (this design): the ADM "**right to human review of an automated
  decision**." Distinct lifecycle (uphold/overturn) with a **re-decision consequence**.
  On `UPHELD`, the customer is offered the existing `Complaint`→AFCA path (a link, not a
  copy). This avoids duplicating the AFCA machinery.

### Endpoints (mirror the existing `/api/loans/referrals/` officer-workflow pattern)
- `POST /api/v1/loans/{id}/review-request/` — customer files a review. Throttled to **one
  open review per application** (mirrors complaint-filing throttle). 403 unless the requester
  owns the application and the decision was `denied` + automated.
- `GET  /api/v1/loans/decision-reviews/` — officer/admin queue (paginated, filter by status).
- `POST /api/v1/loans/decision-reviews/{id}/resolve/` — officer action `{outcome: upheld|
  overturned, note}`.

### Overturn → re-decision (concurrency-safe)
On `overturned`, re-decision reuses the **locked** pattern from
`human_review_handler.resume_after_review`: `select_for_update` on `AgentRun` + a separate
lock on `LoanApplication`, status checked inside the lock, then `application.transition_to(...)`
(which validates the transition and writes `AuditLog`). This respects the documented
"FOR UPDATE cannot be applied to the nullable side of an outer join" caveat and the
UUID-ordering/monotonicity lesson — no new locking primitive is invented.

### Audit
Every state change writes an `AuditLog` row (`action="decision_review_requested"` /
`"decision_review_resolved"`, `resource_type="DecisionReview"`), consistent with how
`transition_to` and complaint creation already audit.

## 5. Component 3 — ADM Disclosure

### New module: `backend/apps/ml_engine/services/adm_disclosure.py`
A small, code-level register describing each decision path:

```python
ADM_REGISTER = {
    "automated_approve": {"mode": "solely_automated", "info_used": [...], "human_review_right": True},
    "automated_decline": {"mode": "solely_automated", "info_used": [...], "human_review_right": True},
    "escalated_review":  {"mode": "assisted",          "info_used": [...], "human_review_right": True},
}
```

`AdmDisclosure` (embedded in `DecisionExplanation`) resolves the register entry for a given
decision and exposes: `mode`, `info_used`, `human_review_right`, `review_request_url`.

### Surfacing (three places, one source)
1. **Per-decision** — `DecisionExplanation.adm_disclosure` → JSON on the customer decision payload.
2. **`DenialExplanationPanel`** — a disclosure line ("This decision was made by an automated
   model. You have the right to request a human review.") + a **"Request a human review"**
   CTA that opens the Component 2 flow and then shows live review status.
3. **`/rights` page** — a new "How automated decisions are made" section rendering the register
   (what's automated vs assisted, what information is used, how to request review).

## 6. Frontend changes (`frontend/src`)
- `components/applications/DenialExplanationPanel.tsx` — add the ADM disclosure line + a
  `RequestReviewButton` (opens a reason form → POST → optimistic status). Existing three
  cards unchanged.
- `components/applications/DecisionReviewStatus.tsx` (**new**) — renders the review lifecycle
  (requested / under review / outcome) on the `/apply/status/[id]` page.
- `app/rights/page.tsx` — add the ADM register section.
- Officer surface (v1) — resolution via the `/decision-reviews/` + `resolve/` DRF endpoints
  surfaced through **Django admin actions** (mirrors how `referral_status` is operated). A
  dedicated frontend officer queue is a deliberate fast-follow, deferred to keep v1 scope tight
  and avoid re-introducing an admin UI surface (the bias UI was removed in PR #75).
- `types/index.ts` — extend the decision type with `adm_disclosure` and add `DecisionReview`.

## 7. Data flow

```
Decline decision (LoanDecision persisted)
        │
        ▼
DecisionExplanation assembler ── reads LoanDecision JSON fields + ADM register
        │
   ┌────┴───────────────┬─────────────────────────┐
   ▼                    ▼                         ▼
Customer serializer   Email generator      human_review_handler
   │                                              (denial reasons)
   ▼
/apply/status/[id]  ── shows reasons + counterfactuals + ADM disclosure + "Request review"
   │
   ▼  (customer requests)
POST /review-request  → DecisionReview(REQUESTED)  → AuditLog
   │
   ▼  (officer)
GET /decision-reviews → resolve(upheld|overturned)
   ├── upheld     → status UPHELD, offer Complaint→AFCA link
   └── overturned → locked re-decision (transition_to) → approval email re-generated
```

## 8. Error handling & edge cases
- Review requested on a non-denied or non-automated decision → 409/403 (guarded server-side).
- Duplicate open review → throttle returns the existing review (idempotent), no second row.
- Overturn race (two officers) → resolved by `select_for_update`; the second resolve sees a
  non-`under_review` status and 409s.
- Assembler with missing `counterfactual_results`/`shap_values` → returns partial explanation
  (reasons without counterfactuals), never raises into the request path (mirrors current
  fail-soft behaviour in `decision_assembly`).
- Email re-generation on overturn failing guardrails → re-escalate, exactly as the existing
  resume path does (no new failure mode).

## 9. Testing strategy
- **Parity tests:** `DecisionExplanation` reproduces the current `CustomerLoanDecisionSerializer`
  and email denial-reason output for existing fixtures (lock behaviour before refactor).
- **Counterfactual reconciliation:** primary-vs-fallback ordering; only actionable features surfaced.
- **`DecisionReview` lifecycle:** request → resolve(uphold) and request → resolve(overturn →
  re-decision → approval email); permission checks (owner-only file, officer-only resolve);
  throttle; concurrency (two simultaneous resolves).
- **ADM disclosure:** register resolves per decision mode; disclosure present in payload + on `/rights`.
- **Frontend:** `DenialExplanationPanel` renders disclosure + CTA; `DecisionReviewStatus` renders
  each lifecycle state; extends existing `denial-explanation-panel.test.tsx`.
- **E2E (`smoke_e2e.sh` extension):** decline → request review → officer overturn → approval email.

## 10. Regulatory mapping
| Requirement | Where satisfied |
|-------------|-----------------|
| Privacy Act ADM transparency APP 1.7–1.9 (10 Dec 2026) | Component 3 (register + per-decision disclosure) |
| Right to human review / contestability (Voluntary AI Safety Standard) | Component 2 (`DecisionReview`) |
| ASIC REP 798 — disclose AI use, explain outputs | Components 1 + 3 |
| ASIC RG 209 — specific reasons | Component 1 (`principal_reasons`) |
| APRA CPS 230 — operational control + audit of the review process | Component 2 (`AuditLog`, officer queue, SLA) |

## 11. Rollout & reversibility
- One migration (`DecisionReview` model only). Additive; no destructive migration.
- Component 1 is a pure refactor behind parity tests — revertable without data impact.
- Feature is independent of the scoring path; can ship behind a settings flag if desired
  (`DECISION_REVIEW_ENABLED`, default on in dev).
- Branch: a fresh `feat/decision-transparency-contestability` off `master` (kept clear of the
  current `feat/perf-prompt-caching` branch). PR per the project's normal flow.

## 12. Resolved design decisions
These were decided rather than left open (per "choose the best decision"):
1. **Officer surface:** v1 = DRF endpoints + Django admin actions for resolution; a dedicated
   frontend officer queue page is a fast-follow. Keeps v1 scope tight; the customer-facing
   request→status→outcome flow is the demo-critical path and is fully built in v1.
2. **ADM disclosure copy:** as written in §3 and §5 ("This decision was made by an automated
   model. You have the right to request a human review."). Wording is refinable in the PR; not
   a design blocker.
3. **Feature flag:** ship behind `DECISION_REVIEW_ENABLED`, default **on** in all envs.
   Additive and reversible — the flag exists so the surface can be disabled instantly if needed.
