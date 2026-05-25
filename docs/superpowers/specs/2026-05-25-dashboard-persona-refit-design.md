# Dashboard persona refit — design

**Date:** 2026-05-25
**Author:** Architecture review (Claude Opus 4.7) with Neville Zeng
**Branch target:** `feat/dashboard-persona-refit` (new, off `master`)
**Status:** Draft — awaiting user review

---

## Problem statement

The dashboard has grown the way most ML side-projects grow: every model artefact got a chart, every feature got a page. The result is technically impressive but operationally hollow.

Concrete verified problems:

1. **`avgProcessingTime` is hardcoded as the string `"2.3s"`** in `frontend/src/app/dashboard/page.tsx:49`. It is never computed from data.
2. **The dashboard home shows four tiles and two cards** — Total Applications, Approval Rate, the bogus 2.3s, Active Model name; plus an approval-rate donut and a recent-apps list. There is no signal an operator can act on: queue depth, today's LLM spend vs cap, pending-review SLA, drift/fairness status, watchdog activity, latency percentiles — none surfaced.
3. **`/dashboard/model-metrics` is a data-science thesis page.** Eight metric cards (Accuracy/Precision/Recall/F1/AUC/Gini/KS/Brier) followed by 10+ charts (ConfusionMatrix, ROC, FeatureImportance, Calibration, Threshold, Fairness, Decile, DriftOverview, DriftPSI, Training Metadata). An MRM reviewer wants *alerts requiring action*, not 10 charts to interpret by hand.
4. **`/dashboard/model-card` overlaps `/dashboard/model-metrics`** — both show Accuracy/Precision/Recall/AUC/Fairness, just laid out differently. Five tabs on one, ten charts on the other.
5. **Counterfactuals (DiCE) are already computed and persisted** on `LoanDecision.counterfactual_results` (migration 0021) but are not surfaced on the customer-facing status page — the single most actionable explanation we have for a denied applicant is hidden in officer view.
6. **The "human override" feedback loop is invisible.** Officers submit reviews via `/dashboard/human-review` (well-built), but no page asks "what did officers disagree with the ML on this week?" — the most valuable data the system produces is not aggregated.

The CS50 video and any portfolio walkthrough lands harder when each page answers a clear "who is this for, and what do they do with it?" rather than "look at the graphs."

## Goals

1. Every dashboard page answers a stated persona × action.
2. The dashboard home becomes operator-useful (real numbers, real signals, real alerts).
3. The customer status page surfaces DiCE counterfactuals on denial.
4. `/dashboard/model-metrics` and `/dashboard/model-card` consolidate into one **Model Health** page with action-first information architecture.
5. No new flashy charts. Strip noise, keep what's actionable.

## Non-goals

- Real CDR / Open Banking integration upgrade (separate spec).
- Service decomposition of `data_generator.py`, `trainer.py`, `metrics.py`, `underwriting_engine.py` (separate spec).
- Security gap-closure (separate spec).
- New "Decision Quality / Human Override Insights" page — flagged as the next-spec follow-up; would require new backend aggregation endpoints. Out of scope here to keep this shippable in one cycle.
- Touching the audit page — already functional, derived-metrics enrichment deferred.
- Brand-new ML capabilities or model architecture work.

## Personas

| Persona | Who | Primary need |
|---|---|---|
| **Customer** | Loan applicant on `/apply/*` routes | Know status. Understand decision. Know next steps. |
| **Loan Officer** | `role=officer` staff on `/dashboard/*` | Process queue. Review escalations. Override correctly. |
| **MRM / Compliance reviewer** | `role=admin` periodically, plus external auditors via screenshots | Confirm model is healthy, fair, in-scope, evidenced. |
| **Engineer on-call / Admin** | `role=admin` daily ops | Spot failures, cost overruns, stuck pipelines. |

These four personas drive every page decision in this refit.

## Changes

### Change 1 — Compute real average processing time, then re-purpose the tile

**Problem:** `avgProcessingTime="2.3s"` is a literal string passed to `<StatsCards>`. It survives because no test catches it and the number is plausible.

**Change:**
- Backend: add a small derived metric to `/api/v1/loans/stats/` (or whichever stats endpoint the dashboard hits) — `decision_latency_p50_ms_24h` and `decision_latency_p95_ms_24h`, computed from `AgentRun.total_duration_ms` over the last 24h with a max-rows guard.
- Frontend: replace the bogus 2.3s tile with a real **"Today's decisions"** tile showing count + p95 latency, and add a **"LLM spend"** tile showing today's $ vs $5 cap (data already available via `agents.services.api_budget`).
- The two original tiles (Total Applications, Approval Rate) stay; "Active Model" moves into Model Health.

**Acceptance:** dashboard tiles all derive from live data; remove the `avgProcessingTime` prop from `StatsCards.tsx` and update its test.

### Change 2 — Operator-grade dashboard home

**Problem:** The home page is decorative for operators.

**Change:** Replace the current home layout with three rows:

1. **Today's tiles** (Change 1) — Total Applications, Approval Rate, Today's Decisions (count + p95 latency), LLM Spend (today's $ / $5 cap with progress bar).
2. **Status strip** — a horizontal strip of four small status indicators (traffic-light dot + label + small detail):
   - Drift gate: latest PSI breach status from `DriftReport`
   - Fairness gate: latest disparate-impact status across protected attributes
   - Pending human review: count + oldest waiting age (SLA breach if >24h)
   - Watchdog: last-recovered count today (green if 0, amber otherwise)
3. **Recent decisions** — keep `<RecentApplications>` but link each row directly to `/dashboard/applications/[id]`.

The approval-rate donut comes out — it duplicates the Approval Rate tile.

**Acceptance:** every element on the home page has a documented persona-action mapping in the spec (in the implementation plan's PR description). No element is decorative-only.

### Change 3 — Surface DiCE counterfactuals on customer status page

**Problem:** `LoanDecision.counterfactual_results` is computed on denial (orchestrator step) but only rendered on the staff-facing application detail. The customer (who needs it most) doesn't see it.

**Change:**
- Extend `/api/v1/loans/{id}/status/` (the endpoint feeding `/apply/status/[id]`) to include serialized counterfactuals when the application is in `denied` state and the requesting user is the application's owner.
- On `/apply/status/[id]`, when status is `denied`, render a **"What could change this"** panel below the existing `<DenialExplanationPanel>`, listing the top 2-3 counterfactuals in plain English ("If your annual income was $X higher, this application would have been approved"). Reuse `formatCurrency`, `formatPercent` from `lib/utils.ts`.
- Add a small disclaimer block (already established pattern in the codebase) explaining that counterfactuals are illustrative, not a guarantee, and that customers can reapply once their situation changes.

This is the CFPB / EU AI Act 2026 direction — explainable adverse-action communication. Already computed; just hidden.

**Acceptance:** denied customer sees actionable counterfactuals on status page; permission test confirms cross-customer access is forbidden.

### Change 4 — Consolidate Model Metrics + Model Card → **Model Health**

**Problem:** Two pages, overlapping content, both academic.

**Change:** Replace both pages with one `/dashboard/model-health` page with three tabs in this order:

1. **Production status** (default tab — what an MRM reviewer opens first)
   - Drift status card (PSI by feature, status traffic light)
   - Fairness gate card (disparate impact by protected attribute, 80% rule pass/fail)
   - Calibration drift card (ECE current vs baseline)
   - Decision threshold + recent threshold drift
   - Alerts band at top if any of the above breach
2. **Model detail**
   - Active model summary card (algorithm, version, training date, file hash)
   - Performance metric tiles (Accuracy, Precision, Recall, F1, AUC, Gini, KS, Brier)
   - FeatureImportance (kept — it's actually useful)
   - Decile chart (kept — bank-standard ranking diagnostic)
   - **Removed: ROC, ConfusionMatrix moved to a collapsed "Diagnostics" detail accordion** at the bottom of this tab — they're stable across runs and rarely add information once you trust AUC.
3. **Governance**
   - Intended use, training data summary, synthetic data validation advisory
   - Independent validation status + MRM dossier link
   - Regulatory compliance checklist (APRA CPG 235, NCCP, Banking Code)
   - Limitations list

The "Train New Model" admin button moves to the Model Detail tab.

Old routes `/dashboard/model-metrics` and `/dashboard/model-card` redirect to `/dashboard/model-health` (`/dashboard/model-health#model-detail` and `/dashboard/model-health#governance` respectively) so any bookmarks survive.

**Acceptance:** zero overlapping content between tabs; every chart on the page is either action-orienting or compliance-evidence; redirects work; existing tests for both old pages either pass against the new page or are explicitly retired with rationale in the PR.

## Sequencing

Four PRs, in order. Each PR ships independently green; no PR depends on a later PR.

1. **PR-1: Real average decision latency + LLM spend tile + remove hardcoded 2.3s** (Change 1 — smallest, smoking-gun fix, builds the backend stats shape)
2. **PR-2: Operator-grade dashboard home** (Change 2 — depends on PR-1's backend shape)
3. **PR-3: Counterfactual surfacing on customer status** (Change 3 — independent of dashboard; can be done in parallel but sequenced after PR-2 for cognitive simplicity)
4. **PR-4: Model Health consolidation + redirects from old routes** (Change 4 — largest visible change, last because most testing surface)

## Risks

- **Test surface is large.** Existing tests for `DashboardPage`, `StatsCards`, `ModelMetricsPage`, `ModelCardPage` will need updating. Mitigation: per-PR plan updates the tests touched in that PR; no big-bang test rewrite.
- **Visual regression on the home page** if screenshots in README go stale. Mitigation: README screenshot refresh as the final PR-4 commit, before merging.
- **Customer-facing counterfactual misinterpretation.** Need careful copy and disclaimer; this is the regulatory-sensitive change. Mitigation: have the existing guardrail rule set extended to also lint the counterfactual rendering copy (no "guaranteed approval if you do X").
- **Redirect breakage** for any documentation or interview-prep walkthroughs referencing `/dashboard/model-metrics`. Mitigation: the redirects + `interview-talking-points.md` update in PR-4.

## What this lays foundation for

Each future architecture improvement now has a clear home and rubric:

- **CDR / Open Banking real integration** (separate spec) — once Model Health exists, CDR connection health gets its own card under "Production status" or a new fourth tab "External integrations."
- **Service decomposition** (separate spec) — once the dashboard has stopped depending on grab-bag service files, refactor risk drops.
- **Decision Quality / Human Override Insights** (separate spec) — the obvious next page, slotted into the same sidebar group as Model Health; requires a backend aggregation endpoint that can be designed in isolation.
- **Security gap closure** (separate spec) — KMS abstraction, hash-chained audit log, structured prompt-injection isolation. The dashboard refit makes operational signals visible, which is a precondition for any security alerting story.

## Approval gate

This spec is the foundation document for the architectural improvements identified in the 2026-05-25 senior-architect audit. After user review and approval, the next step per the brainstorming skill is to invoke `writing-plans` to produce a concrete implementation plan for PR-1 (the smallest unit), then iterate plan-execute for each subsequent PR.

---

## Audit findings that motivated this spec (verified 2026-05-25)

| Claim | Verified |
|---|---|
| `avgProcessingTime` hardcoded `"2.3s"` | ✅ `frontend/src/app/dashboard/page.tsx:49` |
| `/dashboard/model-metrics` is academic / too dense | ✅ 10+ chart components, no narrative |
| `/dashboard/model-card` overlaps `/dashboard/model-metrics` | ✅ both show same core metrics differently |
| Counterfactuals hidden from customer | ✅ `LoanDecision.counterfactual_results` exists, customer status page does not render it |
| `open_banking_service.py` is a mock | ❌ Real Adatree CDR / Open Bank Project adapter |
| `credit_bureau_service.py` is a mock | ❌ Real Equifax/Experian sandbox adapter (minor: uses `sandbox-us-api.experian.com` — Australian endpoint preferred) |
| 2FA not wired | ❌ Backend wired in `accounts/urls.py`; frontend wiring not verified in this audit |
| Bloated services (1565/1334/1018/1009 LOC) | ✅ confirmed; deferred to a separate decomposition spec |
| Service kitchen-sink in `ml_engine/services/` (~50 flat files) | ✅ confirmed; deferred to a separate decomposition spec |
| No event-driven backbone | ✅ confirmed; not in scope for this refit |
| Audit log not tamper-evident | ✅ confirmed; deferred to security spec |
