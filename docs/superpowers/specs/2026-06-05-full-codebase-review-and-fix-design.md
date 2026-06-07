# Full-Codebase Review & Fix Design

**Date:** 2026-06-05
**Version:** v1.11.0 baseline
**Scope:** All layers — backend, ML, email, agents, frontend, infra

---

## Goal

Systematically identify and fix correctness bugs, security issues, type errors, flaky patterns, dead code, inefficient queries, missing error handling, and test gaps across the entire codebase. Output: a cleaner, more stable codebase with an atomic-commit trail of every fix applied.

---

## Approach: Hybrid A + B

- **Phase 1 (A): Parallel analysis** — 6 simultaneous agents, one per layer, return structured findings
- **Phase 2: Triage** — merge and prioritise all findings (CRITICAL → HIGH → MEDIUM → LOW)
- **Phase 3 (B): Layer-by-layer fixes** — apply in severity-first, layer-ordered sequence with atomic commits

---

## Phase 1 — Parallel Analysis

Six agents run concurrently. Each reviews its layer through 5 lenses and returns structured findings.

### Review Lenses

| Lens | What it covers |
|---|---|
| Correctness | Logic bugs, wrong assumptions, off-by-one, race conditions, bad defaults |
| Security | Injection, auth bypass, secrets in code, unvalidated input, OWASP Top 10 |
| Efficiency | N+1 queries, unnecessary API calls, missing DB indexes, memory leaks |
| Tests | Missing coverage on critical paths, tests that can never fail, fixture rot |
| Operability | Missing error handling at system boundaries, silent failures, unlogged exceptions |

### Finding Format (per agent)

Each finding includes:
- **Severity**: CRITICAL / HIGH / MEDIUM / LOW
- **Layer**: which agent found it
- **File:line**: exact location
- **Lens**: which of the 5 lenses applies
- **Description**: what is wrong
- **Fix**: concrete recommendation

### Agents

| # | Layer | Scope |
|---|---|---|
| 1 | Backend core | `backend/apps/accounts/`, `backend/apps/loans/`, `backend/core/`, `backend/config/settings/` |
| 2 | ML engine | `backend/apps/ml_engine/`, training pipeline, prediction service, feature preprocessing |
| 3 | Email engine | `backend/apps/email_engine/`, Claude API calls, guardrails, HTML templates, SMTP |
| 4 | Agents | `backend/apps/agents/`, orchestrator, bias detection, NBO, Celery task chains |
| 5 | Frontend | `frontend/src/`, Next.js pages/components, TypeScript types, API client, React Query |
| 6 | Infra | `docker-compose.yml`, `requirements.txt`, `package.json`, Celery config, env handling, CI |

---

## Phase 2 — Triage

All findings merged into a single list. Grouped by severity, then by layer within each severity band. Duplicates collapsed. This triage list drives Phase 3 ordering — no fix is applied before triage completes.

---

## Phase 3 — Layer-by-Layer Fixes

### Ordering

1. **CRITICAL** — all layers, applied immediately regardless of layer order
2. **HIGH** — backend → ML → email → agents → frontend → infra
3. **MEDIUM** — same layer order
4. **LOW** — same layer order (style, dead code, minor cleanup)

### Commit discipline

- One atomic commit per issue cluster (same file/concern)
- Commit message format: `fix(<layer>): <what and why>`
- No mixed-concern commits
- Tests run after each layer's fixes before moving to the next

---

## Scope Boundaries

### In scope

- Correctness bugs and logic errors
- Security vulnerabilities (auth, injection, secrets, validation)
- Type errors and missing type annotations on public interfaces
- N+1 queries and unnecessary external API calls
- Dead code removal
- Missing error handling at system boundaries (user input, external APIs)
- Test gaps on critical paths (prediction, email, orchestrator, auth)
- Silent failures and unlogged exceptions
- Flaky patterns (race conditions, missing locks, missing retries)

### Out of scope

- New features
- Infrastructure rewrites
- Dependency major-version upgrades (separate PR, separate risk)
- Database schema migrations
- UI redesign or visual changes

---

## Success Criteria

- No CRITICAL or HIGH findings remain unaddressed after Phase 3
- Each fix has an atomic commit with a clear message
- Backend test suite passes after all fixes (`python -m pytest`)
- Frontend type-check passes after all fixes (`tsc --noEmit`)
- No regressions introduced (existing tests still green)
