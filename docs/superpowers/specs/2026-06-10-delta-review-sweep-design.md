# Delta Review & Fix Sweep — Design

**Date:** 2026-06-10
**Status:** Approved (brainstorm with owner)
**Goal:** Make "the project is fully reviewed and fixed" a checkable claim for all code merged since the v1.11.1 full-codebase review (PR #209, 93 findings), by reviewing the delta at high effort and fixing every confirmed finding.

## Scope

- **In:** every file changed in `git diff v1.11.1..master`, plus unchanged code in the same function/module where a changed line re-exposes it (the #245 rule: bugs in unchanged lines of a touched function are in scope).
- **Executable config is code:** CI workflows, `tools/smoke_e2e.sh`, docker compose changes are reviewed; pure docs and k8s placeholder manifests are not.
- **Out:** open unmerged PR stacks (#196–#205, #182/#183, dashboard #191–#194), dependency bumps, demo hosting. These remain backlog items, not review targets.
- **Baseline trust:** code unchanged since v1.11.1 is treated as reviewed by #209 and is not re-reviewed.

## Method (per slice — the #245 loop)

1. **Find:** 7 parallel finder agents — line-by-line diff scan, removed-behavior audit, cross-file tracer (correctness); reuse, simplification, efficiency (cleanup); altitude (design depth). Up to 6 candidates each with concrete failure scenarios.
2. **Verify:** dedupe near-duplicates, then one adversarial verifier per candidate (CONFIRMED / PLAUSIBLE / REFUTED; recall-biased — realistic runtime states count as PLAUSIBLE).
3. **Fix:** all CONFIRMED findings; PLAUSIBLE findings are fixed when the fix is small and low-risk, otherwise filed as GitHub issues with the failure scenario. Smallest-change-that-works, following existing patterns.
4. **Test:** targeted suites + full backend suite in the backend container; `ruff check` + `ruff format --check` on host; `vitest run` for frontend slices.
5. **Ship:** one PR per slice with the findings table (severity, file:line, fix) in the body. Merge gated on explicit `gh pr checks` all green and per-action owner approval (`--admin` on this solo repo requires explicit confirmation).
6. Next slice branches from the merged result — sequential, no stale findings.

## Slices (risk order)

| # | Slice | Approx size | Focus |
|---|-------|-------------|-------|
| 1 | `backend/apps/agents` + `backend/apps/email_engine` (+ their tests) | 24 files / ~1.4k lines | Budget funnel, bias pipeline, email backends (Groq/Ollama), Celery reliability. Includes the known template bug: approval/denial subject renders "Personal Loan Loan" when purpose already ends in "Loan". |
| 2 | `backend/apps/ml_engine` | 96 files / ~1.8k lines | Seams of the 2nd-pass decomposition (imports, state, duplicated logic across extracted modules), fairness small-group exclusion, train self-heal. Not re-litigating moved-but-unchanged code. |
| 3 | `frontend/src` | 56 files / ~2.4k lines | Model Metrics tabs/charts, application detail tabs, Py↔TS parity helpers. Adds React best-practices lens; tests via `vitest run`. |
| 4 | Cross-cutting tail: `backend/apps/loans`, `backend/apps/accounts`, `backend/config`, `.github/workflows`, `tools/smoke_e2e.sh` | ~36 files | Auth/throttle deltas, settings, CI/smoke changes (incl. the known gap: email branch not exercised in CI by smoke-e2e). |

## Guardrails

- **No big changes:** findings whose proper fix is structural rework get a GitHub issue with the evidence, not an in-sweep fix. Improve the existing design; do not replace it.
- **Pre-existing environmental failures** (4 `tests/test_email_generator.py` failures when local `.env` routes to a 500ing Ollama) are recorded, excluded from pass/fail judgment, and never "fixed" by weakening tests.
- **Email content rules hold:** no apology/disappointment language in denial templates; neobank tone; Gmail-compatible HTML only.
- **Cost:** ~4–5× the #245 review spend, spread across slices; the sweep can stop cleanly at any slice boundary with everything merged so far still consistent.

## Definition of Done

1. Four slice PRs merged, master CI fully green.
2. Closing summary mapping **every** candidate finding to one of: fixed-in-PR-N / filed-as-issue-N / refuted-with-evidence.
3. Memory/project notes updated so the next session knows the delta-review baseline moved from v1.11.1 to the sweep's final merge commit.

## Error handling

- A slice whose verification round refutes everything ships no PR — the closing summary records the clean slice.
- If a fix breaks the suite, it is reworked or downgraded to a filed issue before the PR opens; no red merges (#238 lesson).
- If master moves mid-slice (other work landing), the slice branch rebases before PR.
