# Project Hardening Roadmap

**Date:** 2026-04-18
**Status:** Lightweight backlog — each workstream below becomes its own brainstorm session and spec before implementation
**Scope:** Enumerates the non-v1.9.4 workstreams from the 2026-04-18 hardening session

## Background

The 2026-04-18 session started with a broad ask: "do code review from the Codex, fix errors, check security, use best SWE principles, clean up unused files, check all parts of the project." Scope decomposition produced four workstreams:

| # | Workstream | Status |
|---|---|---|
| A | Codex v1.9.4 follow-ups | **Shipped as its own spec** → `2026-04-18-codex-v1.9.4-follow-ups-design.md` |
| B | Broader security sweep | Deferred — see below |
| C | SWE design-principles audit | Deferred — see below |
| D | Dead-code / orphan-file cleanup | Deferred — see below |
| — | Staff 2FA enforcement (Codex critical) | Deferred — see below |

Each deferred item is too broad to spec cold. They need codebase exploration first to scope the surface, then their own brainstorm → spec → plan → implementation cycle.

## Deferred items

### Staff 2FA enforcement (critical)

**What.** `LoginView` in `backend/apps/accounts/views.py:182-250` issues JWT cookies immediately after password validation. The half-implemented `/2fa/setup|verify|status|disable/` views exist but are never consulted during login. Critical finding from the 2026-04-18 second-pass Codex review.

**Why deferred.** The enforcement flow is a real UX and product decision (strict out-of-band enrollment vs. two-step login with pending-state vs. grace-window enrollment). Bootstrap problem: 1 staff account exists today, 0 confirmed TOTP devices — enforcing without an enrollment path locks everyone out.

**Two viable end states.** Either (a) finish the 2FA flow end-to-end, or (b) rip out the half-built 2FA scaffolding so the "stated 2FA requirement" Codex is complaining about no longer exists. Both are legitimate.

**Next step.** Separate brainstorm session on 2FA product direction.

### Workstream B — broader security sweep

**What.** Hunt for issues the Codex adversarial review did not surface. Likely targets:

- Other IDOR/tenant-isolation gaps (the complaint finding suggests similar issues may exist on loan detail, email view, audit log endpoints, bias reports)
- Rate limiting: are all mutation endpoints throttled? What's the coverage gap vs the sensitive-op list?
- Secrets hygiene: `.env` handling, secret rotation, field encryption key scope
- SSRF: any outbound URL callers with user-controlled input (Claude API, Sentry, webhooks)
- Prompt injection on the Claude API boundary (`email_engine`, `agents`): guardrails today vs. what an adversarial applicant note could do

**Why deferred.** Open-ended — needs a codebase sweep before the surface can be enumerated.

**Next step.** Brainstorm session framed around "which of these targets would actually find something and is worth the time."

### Workstream C — SWE design-principles audit

**What.** Surgical refactors only, no rewrites. Targets:

- Oversized files (anything >500 lines in `apps/*/views.py`, `services/*.py`, `tasks.py`)
- Responsibilities tangled across layers (views doing service-layer work, serializers doing persistence work)
- Dead abstractions — protocols, base classes, or config knobs with a single implementation
- Inconsistent patterns — multiple ways to do the same thing (e.g. audit logging call sites)

**Why deferred.** Requires reading the code to know what to target. Cold-brainstormed refactors tend to miss the actual problems.

**Next step.** Codebase audit pass to enumerate candidate files and patterns, then brainstorm the top 3–5.

### Workstream D — dead-code / orphan-file cleanup

**What.**

- Un-imported Python modules (`.orig`, `_old`, commented-out imports)
- Orphan frontend components (not referenced by any route or other component)
- Stale docs claiming features that don't match the code
- Merged feature branches that weren't deleted (`chore/a3-pre-commit`, etc.)
- Dependencies in `requirements.txt` / `package.json` that are no longer imported

**Why deferred.** Low urgency, grindy work, benefits from tooling (`ruff`, `knip`, `depcheck`) to enumerate candidates before a human decision on each.

**Next step.** Run `ruff --select F401` for unused imports, `knip` for orphan frontend files, `pip-audit` and `npm-check` for unused deps; feed the list into a brainstorm.

## Ordering recommendation

1. **v1.9.4 follow-ups (Workstream A)** — in flight, ship this first
2. **Staff 2FA decision** — critical finding, needs a product call even if the call is "rip it out"
3. **Workstream B** — higher security ROI than C or D
4. **Workstream D** — quick wins to keep the repo tidy once it's ruff/knip-instrumented
5. **Workstream C** — last, because it's the most subjective and the codebase is already in reasonable shape

This ordering is a default — the user can reshuffle when picking up each workstream.
