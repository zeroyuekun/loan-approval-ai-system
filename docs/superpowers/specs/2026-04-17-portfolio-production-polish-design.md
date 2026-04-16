# Portfolio Production-Polish Pass — Design Spec

**Date:** 2026-04-17
**Author:** brainstorm session (Neville Zeng + Claude)
**Status:** Approved — ready for implementation plan

## 1. Goal

Bring the Australian Loan Approval AI System from "rated 8.9/10 internally" to "a repo that a senior SWE hiring manager can spend 10 minutes in and come out impressed." The project's architecture and CI pipeline are already strong. The remaining gap is **visible evidence of senior-level engineering discipline** (ADRs, runbooks, SLIs, compliance docs, local enforcement), plus **three concrete fixes** that remove real issues (DiCE tuning, Celery prefetch, frontend exit-243 crash loop).

Robustness must be verified through dedicated code-review passes, not just CI on individual PRs.

## 2. Scope

### In scope — 16 items + 2 review passes

(13 original items + 3 P0 fold-ins added 2026-04-17 after the baseline review surfaced them.)

| ID | Title | Category | Size |
|---|---|---|---|
| P0 | Phase 0 baseline code review | review | M |
| A1 | ADR scaffold + first ADR (XGBoost+RF ensemble) | docs | S |
| A2 | README rewrite with architecture diagram + screenshots + demo steps | docs | S-M |
| A3 | `.pre-commit-config.yaml` (ruff check + ruff format + detect-secrets) | config | S |
| A4 | `backend/pyproject.toml` + `requirements-dev.txt` split | config | S |
| A5 | Incident runbooks (frontend-exit-243, Celery backpressure, migration rollback) | docs | M |
| A6 | SLIs/SLOs doc wired to existing django-prometheus metrics | docs | M |
| A7 | Australian lending compliance doc (NCCP audit, Privacy Act/APP PII, retention, consent) | docs | M |
| A8 | `.github/dependabot.yml` | config | S |
| A9 | `CODEOWNERS` + PR template + issue templates | config | S |
| A10 | Engineering decision journal + interview talking points (`docs/engineering-journal.md`, `docs/interview-talking-points.md`) | docs | M |
| B1 | DiCE timeout alignment + `total_CFs` 5→3 | fix | S |
| B2 | Celery prefetch_multiplier per queue + `task_acks_late = True` | fix | S |
| B3 | State-machine-bypass audit fix (P0 fold-in F-01/F-02/F-03) — replace raw `.update(status=...)` at 6 call sites with `transition_to()` so all final-decision transitions produce `AuditLog` | fix | S |
| B4 | Redis fallback counter thread-safety + reset on recovery (P0 fold-in F-04) | fix | S |
| B5 | Celery integration tests — replace `assert result is not None` with meaningful end-to-end assertions (P0 fold-in F-05) | fix | S |
| C1 | Root-cause and fix the frontend container exit-243 crash loop | fix | S-M |
| P4 | Phase 4 cumulative-diff review | review | S-M |

### Out of scope (explicitly deferred)

- Remaining backend findings B3–B10 (guardrails god class, pandas/xgboost lazy loading, cache TTL hierarchy, N+1 verification, regex compile, CONN_MAX_AGE, etc.)
- Remaining frontend findings C2–C5 (Recharts lazy-load, React Query gcTime, console.error cleanup, localStorage TTL)
- Docker/infra deep-dive (audit agent was rejected earlier this session)
- Architectural rewrites of any kind
- New ML features (Track C counterfactual extensions etc.)

Out-of-scope items may become their own brainstorm/spec cycles later.

## 3. Architecture & approach

### 3.1 Review passes (P0, P4)

Both use `superpowers:requesting-code-review`. Each produces a ranked findings report filed in `docs/reviews/YYYY-MM-DD-<phase>-review.md`.

- **P0** runs against `master` before any item PR is opened. Findings are triaged: critical → scope expansion (must fix in this effort), medium → follow-up issues, low → parking lot.
- **P4** runs against the cumulative diff (`master` at P4 start vs `master` at P0 start). It is the final robustness gate.

Neither pass edits code directly. They only produce reports.

### 3.2 Per-item architecture

Each item is independent; items in the same phase may run in parallel but never merge in parallel (one PR at a time to avoid conflicts).

**Docs items (A1, A2, A5, A6, A7, plus ADRs referenced by A1):** markdown only, live under `docs/`. A1 establishes `docs/adr/` with a template (`000-template.md`) and the first ADR. A2 rewrites root `README.md`. A5 creates `docs/runbooks/`. A6 creates `docs/slo.md` and cross-links Prometheus metric names. A7 creates `docs/compliance/australia.md`.

**Config items (A3, A4, A8, A9):** one file each (or a tiny cluster). A3 adds `.pre-commit-config.yaml` at repo root. A4 creates `backend/pyproject.toml`, splits runtime deps (`requirements.txt`) from dev deps (`requirements-dev.txt`), updates `.github/workflows/ci.yml` to use the split. A8 adds `.github/dependabot.yml` (pip + npm + github-actions ecosystems, weekly). A9 adds `.github/CODEOWNERS`, `.github/PULL_REQUEST_TEMPLATE.md`, and issue templates under `.github/ISSUE_TEMPLATE/`.

**Backend fixes (B1, B2):** small, surgical code changes.
- B1 edits `backend/apps/ml_engine/services/counterfactual_engine.py` — align timeout between caller and callee, reduce `total_CFs` to 3.
- B2 edits Django settings (`backend/config/celery.py` or equivalent) — add `CELERY_WORKER_PREFETCH_MULTIPLIER` per queue and `CELERY_TASK_ACKS_LATE = True`.

**Frontend fix (C1):** root-cause-driven. Sequence:
1. Reproduce the crash locally (build and run the frontend container as CI/compose does).
2. Capture the actual cause (OOM kill, entrypoint failure, healthcheck timeout, bad Node signal handling).
3. Apply the minimal fix that addresses the root cause — not a band-aid memory bump unless memory genuinely is the cause.
4. Add a regression signal if practical (container healthcheck test in CI, or a note in the runbook if unfeasible).

### 3.3 Cross-cutting: CI impact

Most items leave CI as-is. Two items touch it:
- **A3** may add a pre-commit CI job (run the same hooks server-side so PRs without local hooks still get caught). Optional; default is local-only.
- **A4** updates the `Install dependencies` step in `backend-test` and `backend-lint` jobs to reference the dev-deps file. This is a backwards-compatible change — runtime deps stay in `requirements.txt`, dev/test deps move to `requirements-dev.txt`, and CI installs both.

All CI changes must keep the pipeline green.

## 4. Testing protocol

Applied to every PR:

| PR type | Requirements |
|---|---|
| Docs-only (A1, A2, A5, A6, A7) | CI green. Markdown renders correctly on GitHub (check preview). No broken internal links. |
| Config (A3, A4, A8, A9) | CI green *with the new config active*. A3: pre-commit runs clean locally on a fresh clone. A4: `pip install -r requirements.txt -r requirements-dev.txt` works in CI. A8: dependabot.yml validates (GitHub parses it on push). A9: PR template shows up on next PR. |
| Backend fix (B1, B2) | Unit test first (TDD where feasible). Existing test suite still passes. Coverage must not drop. B2 needs an integration test asserting task routing + prefetch behavior. |
| Frontend fix (C1) | A reproduction script or documented steps that fail before the fix and pass after. CI docker-build job + DAST smoke test must pass. |
| Review passes (P0, P4) | Report committed. No code edits in the review PR. |

Global rules:
- No PR merges on red CI. No `--no-verify` or bypassing hooks.
- Target diff ≤ 300 lines including tests (docs PRs may be larger — content is the point).
- One logical change per PR.
- Squash merge with a conventional commit title (`feat:`, `fix:`, `docs:`, `chore:`, `ci:`).

## 5. Branching & rollout

- Branch naming: `<type>/<id>-<short-slug>` — e.g. `docs/a1-adr-scaffold`, `fix/b1-dice-timeout`, `fix/c1-frontend-exit-243`.
- All branches off latest `master`; rebase before merge if master has advanced.
- One PR merged at a time. No long-lived feature branches.
- If a PR needs rework, it stays open; push new commits (no amending after first push).
- If P0 identifies a must-fix that isn't in this scope, raise it with the user before expanding scope — don't silently grow the plan.

## 6. Phase ordering

```
P0 (baseline review)
  ↓
Phase 1 — Quick wins (parallel authoring, serial merging)
  A3 pre-commit
  A4 pyproject + dev-deps split
  A8 dependabot
  A9 CODEOWNERS + templates
  A1 ADR scaffold + first ADR
  B1 DiCE timeout/count
  B2 Celery prefetch + acks_late
  ↓
Phase 2 — Signal-heavy docs
  A2 README rewrite
  A5 runbooks
  A6 SLIs/SLOs
  A7 AU compliance
  A10 engineering journal + interview talking points
  (additional ADRs — Celery queue separation, DiCE vs SHAP — are optional.
   Written as separate PRs if a decision-worth-documenting arises during
   Phase 2 work. Not required for completion.)
  ↓
Phase 3 — Real bugs
  B3 state-machine-bypass audit fix (P0 fold-in)
  B4 Redis fallback counter thread-safety + reset (P0 fold-in)
  B5 Celery integration test assertions (P0 fold-in)
  C1 frontend exit-243 root-cause and fix
  ↓
P4 (cumulative review)
  ↓
Done
```

Ordering rationale:
- Phase 0 first so scope decisions are informed by a fresh robustness read.
- Config/docs before behavioral fixes so lint/pre-commit is active when those PRs land.
- A1 ADR scaffold near the start; later ADRs (in Phase 2) can be written as decisions recur in the work.
- C1 last because it needs focused root-cause investigation; doing it under parallel-PR pressure would compromise rigor.

## 7. Success criteria

The polish pass is done when all of the following hold:

1. P0 and P4 review reports are filed under `docs/reviews/`.
2. All 16 item PRs are merged to `master` (13 planned + 3 P0 fold-ins).
3. CI is green on `master` end-to-end, including docker-build, DAST (master-only), and load test (master-only).
4. Coverage floor is at least the current `--cov-fail-under=60`; no regression.
5. No P0-identified critical issue remains open.
6. The repo passes this 10-minute-recruiter walkthrough:
   - README top → architecture diagram, screenshots, demo steps visible.
   - `docs/adr/` → at least 1 ADR visible (the XGBoost+RF ensemble decision), with `000-template.md` scaffold for future ADRs.
   - `docs/runbooks/` → at least 3 runbooks.
   - `docs/compliance/australia.md` exists and is substantive.
   - `docs/slo.md` exists with concrete SLIs and targets.
   - `docs/engineering-journal.md` + `docs/interview-talking-points.md` exist, covering project origin → incidents → tradeoffs → ratings journey, each claim cited to a commit / ADR / memory entry.
   - `.pre-commit-config.yaml` at root.
   - `CODEOWNERS` + PR template visible in `.github/`.
   - Recent commit log is clean, conventional, and PR-linked.

## 8. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| P0 review surfaces more critical work than expected, blowing up scope | medium | Raise with user before expanding; default is to log as follow-up issues unless truly blocking. |
| C1 root cause is non-trivial and eats the schedule | medium | Time-box diagnosis to 1 day; if no root cause found, move to a documented workaround + runbook entry and track the real fix as a follow-up. |
| Pre-commit adoption breaks contributor flow | low | Make it opt-in (via README setup step) before making it mandatory in CI. |
| Splitting requirements into dev/prod breaks an unexpected CI path | low | Run CI locally with `act` or push to a throwaway branch first. |
| Docs PRs merged without review become stale | low | Same PR review rules apply to docs PRs; no auto-merge. |
| Multiple PRs in flight step on each other | low | Serial merge rule enforced; rebase before merge if master moved. |

## 9. Timeline (estimate only)

- Phase 0: 0.5 day
- Phase 1 (7 PRs, ~half-day each): 3–4 days
- Phase 2 (4 PRs, ~1 day each; optional ADRs add 0.5 day each): 4–5 days
- Phase 3 (1 PR with root-cause work): 1–2 days
- Phase 4: 0.5 day

Total: ~10 working days of focused effort, spread however the user wants.

## 10. Follow-ups (captured here so they aren't lost)

From the audit, **not in scope** for this spec but explicitly preserved:
- Backend: B3 guardrails god-class split · B4 regex pre-compile · B5 CONN_MAX_AGE tune · B6 AuditLog N+1 verification · B7 pandas/xgboost lazy load · B8 cache TTL hierarchy · B9 DiCE dataset pre-compute · B10 others
- Frontend: C2 Recharts lazy-load · C3 React Query gcTime · C4 console.error in prod · C5 localStorage TTL
- Docker/infra deep-dive (rejected agent)
- Broader compliance items beyond A7 (e.g., SBOM, model card, fairness reporting to Open Banking standards)

After P4 completes, the user may choose to brainstorm a Phase-5 follow-up pass pulling from this list.
