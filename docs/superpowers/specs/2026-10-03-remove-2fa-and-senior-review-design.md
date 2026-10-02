# Remove 2FA, then senior review, security audit, architecture review and simplify

Date: 2026-10-03
Status: approved in brainstorming (parts 1 and 2 explicitly, the rest under "yes to all")

## Goal

1. Remove two-factor authentication from the whole system. The owner does not want it.
2. Review the code as a senior engineer and fix the bugs found.
3. Audit security, now that staff accounts rely on passwords alone.
4. Check the design principles and the architecture.
5. Run the `/simplify` pass so the code reads plainly.

## Base branch

Thirteen PRs are open and unmerged. They form a tree on top of #268, not a single line:

- #269, #271, #272, #273 each branch off #268.
- #270 → #275 → #276 → #277 is one chain.
- #274 → #278 → #279 is another chain.

`review/integration-2026-10` merges every leaf except #271 into #268's head: #269, #272, #273, #277 and #279. All five merges were textually clean. #271 enforces staff 2FA, the opposite of goal 1, so it is left out and will be closed with a link to the removal PR.

All work below branches from `review/integration-2026-10`.

## Part 1: remove 2FA (branch `refactor/remove-2fa`)

Backend:

- Delete `apps/accounts/views_2fa.py`, the four `auth/2fa/` routes, the `totp_verify` throttle scope, and the settings `ENFORCE_2FA_FOR_STAFF` and `ALLOW_2FA_BYPASS`.
- Remove `django_otp` and `django_otp.plugins.otp_totp` from `INSTALLED_APPS`, `OTPMiddleware` from `MIDDLEWARE`, and `django-otp` (plus any QR-code library used only by enrolment) from `requirements.txt`.
- `authentication.py` stops calling `enforce_staff_2fa`. `policy.py` keeps only the "who counts as staff" rule. Permission classes go back to plain role checks.
- The login view loses its OTP step. `User.has_confirmed_totp()` goes.
- A new `accounts` migration drops the django-otp tables (`otp_totp_totpdevice`, `otp_static_staticdevice`, `otp_static_statictoken` if present) with `DROP TABLE IF EXISTS`, so stored TOTP secrets do not linger. The reverse is a no-op.
- Existing `AuditLog` rows that mention 2FA (for example `login_2fa_bypassed`) stay untouched. The hash chain must not change.

Overturn gate:

- `VALID_MODES` becomes `("off", "second_approver")`.
- Today an unknown mode collapses to `off`. A deployment still set to `DECISION_OVERTURN_GATE_MODE=2fa` would therefore silently lose its gate. The legacy value `"2fa"` is mapped to `second_approver`, the stricter remaining mode, with a warning log.
- `evaluate_overturn_gate` loses its `officer_has_2fa` parameter.

Frontend:

- Delete `app/dashboard/two-factor/page.tsx` and its test.
- Remove the OTP step from the login page, `useAuth`, `lib/auth.ts` and `lib/api.ts`, and the redirect that sends un-enrolled staff to enrolment.

Docs: README, security docs and `.env.example` lose their 2FA sections.

Tests:

- Delete `tests/test_2fa_enforcement.py` and `tests/test_2fa_staff_paths.py`.
- Overturn tests cover `off`, `second_approver`, and the legacy `"2fa"` value mapping to `second_approver`.
- A new test logs a staff user in with a password only and calls a staff-only endpoint.
- The backend suite, `makemigrations --check` and the frontend vitest suite must pass.

Accepted risk: staff and admin accounts are protected by password only. Mitigations that stay in place: login throttling, the password validators, short-lived JWT access tokens, and the `second_approver` gate on large overturns. The security audit in part 2 re-checks this surface.

## Part 2: audit, verify, fix

Five read-only audit agents run in parallel against the head of `refactor/remove-2fa`:

1. Backend correctness A: `accounts`, `loans`, `config`.
2. Backend correctness B: `ml_engine`, `agents`, `email_engine`, Celery tasks.
3. Frontend correctness.
4. Security: authn/authz on every view, IDOR, injection, SSRF in the LLM and email paths, secrets, PII encryption, headers and CSP, Docker and CI, dependency advisories, and the password-only staff surface.
5. Architecture and design principles: layering (thin views, services, external APIs), coupling between apps, SOLID and DRY, file-size caps, Celery queue boundaries, and the WAT conventions in `CLAUDE.md`.

Each finding carries `file:line`, a severity, a concrete failure scenario and a fix sketch. The `code-review-extras` companion skill and its open observations apply.

Every Critical, High and Medium finding is checked independently against the code before anyone acts on it. Findings the check does not confirm are dropped. Duplicates across agents are merged.

Fix scope: confirmed Critical, High and Medium findings. Fixes are grouped by area, one branch per group, stacked on `refactor/remove-2fa`. Each fix starts with a test that fails on the current code. Groups whose files overlap run one after another, never in parallel.

Low items, nits and large architecture refactors go into `docs/reviews/2026-10-03-senior-review.md`, ranked, for the owner to choose from later.

## Part 3: simplify and delivery

- `/simplify` runs last, over the files changed by parts 1 and 2. It is a quality pass only and must not change behaviour.
- Each branch is pushed and gets its own PR, stacked as above. PR bodies follow the repo's template.
- Nothing is merged without the owner's approval for that merge, and only after `gh pr checks` shows no failing or pending check.

## Testing constraint

Local backend test runs through the compose containers were blocked by the session's permission classifier, because building a test environment needed the running stack's secrets. Backend tests therefore run in GitHub Actions on each pushed branch, which uses its own throwaway credentials. Frontend tests and `ruff` run on the host.

## Decisions taken under delegation

- The integration branch merges five leaves of the PR tree and leaves out #271. "Top of stack" was not a single branch.
- The django-otp tables are dropped, not left orphaned.
- The legacy `"2fa"` overturn mode maps to `second_approver`, not `off`.
