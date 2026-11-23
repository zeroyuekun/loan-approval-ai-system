# Senior review, security hardening, local Llama, README

Date: 2026-11-22
Status: approved by delegation (owner: "auto accept the recommendations for me")
Branch: `review/senior-2026-11-22`, cut from `0367e5b` (head of PR #289, which this work builds on)

## Goal

Act on a fresh senior review of the project (architecture, security, frontend, CI),
make the app's AI run on a local Llama model through Ollama instead of Claude, test
every change, and rewrite the README so it is short, plain and honest about how the
project was built (by the owner, in conjunction with AI).

This spec sits next to `2026-11-22-portfolio-readiness-design.md` (branch
`fix/ci-health`, written earlier the same day). That spec's phases 1-3 (dependabot
batch, lending-overview commit, fairness reweighing) are not repeated here. Its
phase 4 README wording for "How I built this" is reused, because the owner approved
it.

## Inputs

Three read-only reviews on `0367e5b`: backend security, architecture plus an LLM
call-site inventory, and frontend/CI. Items already fixed by the 2026-10-03 review
were excluded.

## Decisions taken under delegation

1. **Base on PR #289, not master.** The Ollama bias client lives there. The pull
   request targets master so CI runs, and says it contains #289.
2. **Uncommitted `feat/lending-overview` work is left alone.** Work happens in a
   separate worktree (`C:/Users/Admin/loan-ai-review`).
3. **"Llama instead of Claude" means:** every runtime LLM call defaults to local
   Ollama or a deterministic template; Claude becomes an opt-in backend. Emails stay
   template-only (owner decision 2026-10-03: Ollama writes verdicts, not emails).
4. **Bias verdict model:** `llama3.1:8b` replaces `qwen2.5:7b` as the default only if
   a live test shows it flags the genuine cases and clears the false positives at
   least as well as qwen. `llama3.2:3b` is never used (it passed blatant
   discrimination in an earlier test).
5. **Not changed (reported instead):** GitHub branch protection (repo admin
   setting), dependabot backlog (covered by the other spec), splitting files over
   1,000 lines (large refactor with regression risk), making the base compose file
   production-default (the owner's uncommitted work edits the override file),
   moving Ollama to its own network, an email-verification flow, the zod 3→4 major
   upgrade.

## Workstream A: security

| # | Finding | Fix |
|---|---|---|
| A1 | Login CSRF through `CookieTokenRefreshView` (form body token) | JSON parser only; take the refresh token from the cookie when present, body only as fallback for JSON clients; reject inactive users on refresh |
| A2 | APP 12 data export leaks unsent drafts, raw agent steps and bias analysis | Move the export into `accounts/services/data_export.py`; export only sent emails and the customer-safe agent run view |
| A3 | Customers can create applications at 60/min, each running the full pipeline | Scoped `loan_create` throttle and a cap on open (non-final) applications per customer |
| A4 | Email change accepts an address another account uses | Case-insensitive uniqueness check in the profile serializer |
| A5 | Orchestration and email throttles share the default throttle history | Give each its own `scope` and rate |
| A6 | LLM bias score is not validated | Coerce to int, clamp 0-100, use the deterministic fallback when invalid |
| A7 | `?page=0` or negative page returns 500 | Clamp to 1 |
| A8 | `X-Request-ID` trusted without limits | Accept `^[A-Za-z0-9-]{1,64}$`, else generate one |
| A9 | `.env*` not in `.dockerignore`; bootstrap superuser password skips validation | Add the ignore rules; run `validate_password` in the entrypoint |
| A10 | PII log filter skips exception arguments | Redact `str(exc)` for exception arguments |
| A11 | Next.js 16.3.8 critical image-optimizer RCE plus runtime advisories | In-range lockfile updates (next ≥16.4.5, follow-redirects, source-map-js, vite, undici, dompurify) |
| A12 | Email HTML preview allows `position`/`z-index` styles | DOMPurify hook strips them |
| A13 | Frontend responses have no HSTS | Add HSTS in `next.config.js` for production |

## Workstream B: reliability and architecture

| # | Finding | Fix |
|---|---|---|
| B1 | `except Exception` swallows Celery `SoftTimeLimitExceeded` in bias helpers and NBO | Re-raise it first |
| B2 | Bias Ollama timeout (300 s) exceeds the email task limit (100 s soft) | Bias client timeout from a setting that defaults below the soft limit |
| B3 | LLM clients built in four places; NBO and marketing hard-code Anthropic | One `make_llm_client(purpose)` factory; NBO and marketing honour the email backend (template → deterministic, ollama → local) |
| B4 | Ollama errors logged as "UNEXPECTED" at CRITICAL | Catch `EmailBackendError` alongside `anthropic.APIError` |
| B5 | Duplicate `_extract_tool_result`; stale docstrings; silent signals import | Keep one copy; fix docstrings; log the import error |
| B6 | `celery_beat` unhealthy in CI (`smoke-e2e` red on master) because it writes its schedule into the bind-mounted, runner-owned `/app` | `--schedule /tmp/celerybeat-schedule`; failure step dumps logs for all services |
| B7 | Training-status polling never stops on `PENDING`/`REVOKED` | Treat `REVOKED` as terminal and cap polling at 15 minutes |
| B8 | Frontend retries POST on 429/503 (double submit) | Retry only idempotent methods |

## Workstream C: local Llama as the AI

- Defaults in `config/settings/base.py` and `.env.example`: `EMAIL_LLM_BACKEND=template`,
  `BIAS_LLM_BACKEND=ollama`, `BIAS_OLLAMA_MODEL=llama3.1:8b` (subject to decision 4).
- `ollama-init` pulls `${BIAS_OLLAMA_MODEL}` instead of a hard-coded tag; image
  pinned to a version.
- `env_validation.py` text no longer claims the reviewer always calls Anthropic.
- Claude stays available by setting the backends to `anthropic` with a key.

## Workstream D: README

Rewrite for a reader who has two minutes: what it does, how it works (one diagram),
how to run it ($0, no API key), how it was built, then details in collapsed
sections. "How I built this" follows the approved wording: the owner designed the
architecture and made the product decisions, wrote parts of the code by hand, used
AI (Claude Code) as a pair programmer for much of the implementation, and reviewed,
tested and debugged every change. No external tutorial is named. Every number,
command and path is checked against the tree.

## Testing

- Test-driven for every backend behaviour change: a failing test first, then the fix.
- Backend tests run inside the running backend container against a copy of the
  worktree's `backend/` (the container's own env and Postgres test database), one run
  at a time; full suite before the pull request.
- Frontend: `vitest run`, `tsc --noEmit`, `eslint`, `next build` in the worktree.
- Live check: the bias-model comparison script on qwen2.5:7b and llama3.1:8b.
- CI on the pull request into master is the final gate. No merge without the owner.

## Out of scope

Everything in "Not changed" above, plus anything in the portfolio-readiness spec.
