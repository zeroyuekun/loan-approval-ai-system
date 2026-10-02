# Remove 2FA, then Senior Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove two-factor authentication end to end, then audit the code for bugs, security and architecture, fix confirmed Critical/High/Medium findings, and finish with a simplify pass.

**Architecture:** Part 1 removes 2FA on `refactor/remove-2fa` in five tasks: overturn gate, backend auth, frontend, docs, delivery. Part 2 runs five read-only audit agents against that branch, verifies each finding, and fixes the confirmed ones on stacked branches. Part 3 runs `/simplify` over the changed files and writes the ranked report of what was not fixed.

**Tech Stack:** Django 5 + DRF, simplejwt cookie auth, pytest; Next.js + React Query, vitest + MSW.

**Spec:** `docs/superpowers/specs/2026-10-03-remove-2fa-and-senior-review-design.md`

## Global Constraints

- Worktree: `C:/Users/Admin/loan-review-2026-10`. Base: `review/integration-2026-10`. Part 1 branch: `refactor/remove-2fa`.
- Backend tests run in GitHub Actions (`ci.yml` → `test.yml`). Local container test runs are not available in this session.
- Before each backend commit, run `ruff check` and `ruff format --check` on the host from `backend/`.
- Frontend: `node_modules` is a junction to the main tree's (`cmd /c mklink /J`). Remove it with `cmd /c rmdir`, never `rm -rf`. Run tests with `npx vitest run <path>`. Never use `npm test`, which starts watch mode.
- Existing `AuditLog` rows are never rewritten. The hash chain must not change.
- No apology language in any email prompt or template (project `CLAUDE.md`).
- Never push to `master`. Each merge needs the owner's approval for that merge, after `gh pr checks` shows no failing or pending check.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

---

## Part 1: remove 2FA

### Task 1: Overturn gate without a 2FA mode

**Files:**
- Modify: `backend/apps/loans/services/overturn_policy.py`
- Modify: `backend/apps/loans/services/decision_review.py:27-40`
- Modify: `backend/config/settings/base.py:352-356` (comment only)
- Modify: `backend/config/settings/production.py:78-82`
- Test: `backend/apps/loans/tests/test_overturn_maker_checker.py`

**Interfaces:**
- Produces: `evaluate_overturn_gate(amount, threshold, mode) -> dict` (no `officer_has_2fa`); `VALID_MODES = ("off", "second_approver")`; `normalize_overturn_mode("2fa") == "second_approver"`.

- [ ] **Step 1: Rewrite the tests to the new contract**

Replace the pure-dispatcher block and the DB wiring tests with:

```python
def test_default_mode_is_off():
    assert DEFAULT_MODE == "off"


def test_off_mode_allows_any_amount():
    assert evaluate_overturn_gate(amount=500000, threshold=100000, mode="off")["allowed"] is True


def test_below_threshold_allowed_regardless_of_mode():
    assert evaluate_overturn_gate(amount=50000, threshold=100000, mode="second_approver")["allowed"] is True


def test_second_approver_mode_blocks_high_value():
    gate = evaluate_overturn_gate(amount=150000, threshold=100000, mode="second_approver")
    assert gate["allowed"] is False
    assert gate["reason"]


def test_legacy_2fa_mode_maps_to_second_approver():
    # 2FA was removed. A deployment still configured with "2fa" must keep a
    # gate, so the value maps to the stricter remaining mode, never to "off".
    assert normalize_overturn_mode("2fa") == "second_approver"
    assert evaluate_overturn_gate(amount=150000, threshold=100000, mode="2fa")["allowed"] is False


def test_unknown_mode_collapses_to_off():
    assert normalize_overturn_mode("garbage") == "off"
    assert normalize_overturn_mode(None) == "off"
```

Replace the three DB tests with a `second_approver` block test, a legacy `"2fa"` block test and the existing default-off allow test. Each uses `_denied_app_with_review` and `client.force_authenticate(officer)` exactly as now. The block tests set `settings.DECISION_OVERTURN_GATE_MODE` to `"second_approver"` and `"2fa"` and assert `resp.status_code == 403`. Remove the `django_otp` import. Update the module docstring: "Wiring tests exercise the resolve endpoint in `second_approver` mode and with the legacy `2fa` value."

- [ ] **Step 2: Confirm red**

The new tests call `evaluate_overturn_gate` without `officer_has_2fa`, so they fail with `TypeError: evaluate_overturn_gate() missing 1 required positional argument: 'officer_has_2fa'`, and `normalize_overturn_mode("2fa")` returns `"2fa"`. Backend tests run in CI, so confirm red by reading: the current signature at `overturn_policy.py:43` requires the argument.

- [ ] **Step 3: Implement**

In `overturn_policy.py`:

```python
VALID_MODES = ("off", "second_approver")
DEFAULT_MODE = "off"
# Two-factor authentication was removed. "2fa" maps to the stricter remaining
# mode so a deployment still configured with it keeps a gate.
_LEGACY_MODES = {"2fa": "second_approver"}


def normalize_overturn_mode(mode: str | None) -> str:
    """Coerce arbitrary input to a valid mode; unknown values collapse to off.

    A misconfigured deployment never silently enables a stricter gate than
    intended — unknown values fall back to the no-op ``off`` mode. The legacy
    ``2fa`` value is the exception: it maps to ``second_approver``.
    """
    if mode in _LEGACY_MODES:
        logger.warning(
            "DECISION_OVERTURN_GATE_MODE=%r is no longer supported; using %r",
            mode,
            _LEGACY_MODES[mode],
        )
        return _LEGACY_MODES[mode]
    if mode in VALID_MODES:
        return mode
    if mode is not None:
        logger.warning(
            "Unknown DECISION_OVERTURN_GATE_MODE=%r — defaulting to %r",
            mode,
            DEFAULT_MODE,
        )
    return DEFAULT_MODE
```

Change the signature to `def evaluate_overturn_gate(amount, threshold, mode) -> dict:`. Delete the `officer_has_2fa` arg doc and the whole `if mode == "2fa":` block. The mode doc becomes `One of "off", "second_approver"`.

In `decision_review.py`, delete the `officer_has_2fa=officer.has_confirmed_totp(),` line. `_enforce_overturn_gate(application, officer)` keeps its signature because callers pass the officer.

In `production.py`:

```python
# "second_approver" refuses high-value overturns at the API (dual approval is
# out of band). The legacy "2fa" value maps to it: two-factor authentication
# was removed, and an old env file must not turn the gate off.
_overturn_mode = _gate_mode("DECISION_OVERTURN_GATE_MODE", "second_approver", ("off", "2fa", "second_approver"))
DECISION_OVERTURN_GATE_MODE = "second_approver" if _overturn_mode == "2fa" else _overturn_mode
```

In `base.py`, rewrite the comment above `DECISION_OVERTURN_GATE_MODE`: drop the `"2fa"` sentence and add "The legacy value "2fa" maps to "second_approver"."

- [ ] **Step 4: Lint**

Run: `cd backend && ruff check apps/loans config && ruff format --check apps/loans config`. Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/loans backend/config/settings
git commit -m "refactor(loans): overturn gate drops the 2FA mode; legacy value maps to second_approver"
```

### Task 2: Backend authentication without 2FA

**Files:**
- Delete: `backend/apps/accounts/views_2fa.py`, `backend/apps/accounts/throttles.py`, `backend/config/admin_site.py`, `backend/tests/test_2fa_enforcement.py`, `backend/tests/test_2fa_staff_paths.py`
- Modify: `backend/apps/accounts/views.py:258-321` (LoginView), `:329`, `:710`
- Modify: `backend/apps/accounts/policy.py`, `permissions.py`, `authentication.py`, `urls.py`, `models.py:73-85`
- Modify: `backend/config/urls.py:23,208-209`, `backend/config/settings/base.py:73-74,95,180,372-387`
- Modify: `backend/requirements.in:27-28`, `backend/requirements.txt:31,72`
- Create: `backend/apps/accounts/migrations/0012_drop_otp_tables.py`
- Test: `backend/tests/test_staff_password_login.py`

**Interfaces:**
- Consumes: Task 1 (no remaining caller of `has_confirmed_totp`).
- Produces: `apps.accounts.policy` exports `STAFF_ROLES` and `is_staff_role` only. The login response body is `{"user": {...}}`, with no `requires_2fa` or `requires_2fa_setup` key.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_staff_password_login.py`:

```python
"""Two-factor authentication was removed: staff sign in with a password."""

import pytest
from rest_framework.test import APIClient

PASSWORD = "Corr3ct-horse-battery"


@pytest.mark.django_db
def test_staff_password_login_reaches_a_staff_endpoint(django_user_model, settings):
    # The old enforcement flag must have no effect any more.
    settings.ENFORCE_2FA_FOR_STAFF = True
    django_user_model.objects.create_user(
        username="officer_pw", password=PASSWORD, role="officer", email="officer_pw@x.com"
    )
    client = APIClient()
    resp = client.post("/api/v1/auth/login/", {"username": "officer_pw", "password": PASSWORD}, format="json")
    assert resp.status_code == 200
    assert resp.data["user"]["role"] == "officer"
    assert "requires_2fa" not in resp.data
    assert "requires_2fa_setup" not in resp.data
    assert client.get("/api/v1/auth/customers/").status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["setup", "verify", "status", "disable"])
def test_two_factor_routes_are_gone(path):
    assert APIClient().get(f"/api/v1/auth/2fa/{path}/").status_code == 404


def test_otp_apps_are_not_installed(settings):
    assert not [app for app in settings.INSTALLED_APPS if app.startswith("django_otp")]
    assert "django_otp.middleware.OTPMiddleware" not in settings.MIDDLEWARE
```

- [ ] **Step 2: Confirm red by reading**

On the current code: login returns `requires_2fa_setup` for staff (`views.py:315-317`); with `ENFORCE_2FA_FOR_STAFF=True`, `/auth/customers/` returns 403 `2fa_enrolment_required` (`authentication.py:49`); `/auth/2fa/status/` resolves (`urls.py:32`); `django_otp` is in `INSTALLED_APPS` (`base.py:73`). All three tests fail.

- [ ] **Step 3: LoginView**

Replace everything from the `# 2FA gate.` comment block through `body["requires_2fa_setup"] = True` with:

```python
        _record_activity(user.pk)
        refresh = RefreshToken.for_user(user)
        _audit_user_event(request, user, "login_success")

        response = Response({"user": UserSerializer(user).data})
```

Keep `_set_jwt_cookies`, `rotate_token` and `get_csrf_token` as they are. Delete `allow_unenrolled_staff = True` at `UserProfileView` and `LogoutView`. Remove imports that become unused: `is_staff_role` if unused, and `django_settings` if unused. `ruff` reports them.

- [ ] **Step 4: policy, permissions, authentication**

`policy.py` becomes:

```python
"""Who counts as staff — one place for the rule.

Staff access used to be decided in four places (DRF permission classes,
role-string compares in querysets, ``check_loan_access`` and
``TaskStatusView``); they all ask ``is_staff_role`` now.
"""

STAFF_ROLES = ("admin", "officer")


def is_staff_role(user) -> bool:
    """Admin or officer role, or a Django superuser (whose role may be the
    ``customer`` default that ``createsuperuser`` leaves)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return getattr(user, "role", None) in STAFF_ROLES or bool(getattr(user, "is_superuser", False))
```

`permissions.py` becomes:

```python
from rest_framework.permissions import BasePermission

from apps.accounts.policy import is_staff_role


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and (request.user.role == "admin" or request.user.is_superuser)


class IsLoanOfficer(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "officer"


class IsCustomer(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "customer"


class IsAdminOrOfficer(BasePermission):
    def has_permission(self, request, view):
        return is_staff_role(request.user)
```

In `authentication.py`, remove the `enforce_staff_2fa` import and the second paragraph of the class docstring, and make `authenticate`:

```python
    def authenticate(self, request):
        cookie_name = getattr(settings, "JWT_ACCESS_COOKIE_NAME", "access_token")
        raw_token = request.COOKIES.get(cookie_name)
        if raw_token is None:
            return super().authenticate(request)

        validated_token = self.get_validated_token(raw_token)
        user = self.get_user(validated_token)
        self._enforce_csrf(request)
        return user, validated_token
```

- [ ] **Step 5: routes, admin site, model, settings, dependencies**

- `accounts/urls.py`: drop the `views_2fa` import and the four `2fa/` paths with their comment.
- `config/urls.py`: drop `from config.admin_site import StaffOTPAdminSite` and the two lines at 208-209. The admin uses the stock `AdminSite`.
- Delete `views_2fa.py`, `throttles.py` and `config/admin_site.py`. First run `git grep -n "throttles\|TOTPVerifyThrottle\|admin_site"` and confirm the only hits are the files being deleted.
- `models.py`: delete `has_confirmed_totp`.
- `base.py`: remove the two `django_otp` apps, `OTPMiddleware`, the `"totp_verify": "5/min",` rate, and the whole `# Two-factor authentication` block with `ENFORCE_2FA_FOR_STAFF` and `ALLOW_2FA_BYPASS`.
- `requirements.in`: remove `django-otp>=1.5` and `qrcode>=8.0`. `requirements.txt`: remove `django-otp==1.7.0` and `qrcode==8.2`. First run `git grep -n "qrcode"` to confirm nothing else imports it. If `requirements.txt` is pip-compiled with `# via` comments, also remove any package listed only `# via django-otp` or `# via qrcode`.
- Delete `tests/test_2fa_enforcement.py` and `tests/test_2fa_staff_paths.py`.

- [ ] **Step 6: Migration that drops the TOTP tables**

`backend/apps/accounts/migrations/0012_drop_otp_tables.py`:

```python
"""Drop django-otp's tables: two-factor authentication was removed.

The TOTP secrets they hold must not outlive the feature. Removing the
migration-history rows means a future re-install starts clean instead of
assuming the tables exist. Reversing is a no-op: the secrets are gone.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("accounts", "0011_customuser_deidentified_at")]

    operations = [
        migrations.RunSQL(
            sql=[
                "DROP TABLE IF EXISTS otp_totp_totpdevice;",
                "DELETE FROM django_migrations WHERE app = 'otp_totp';",
            ],
            reverse_sql=migrations.RunSQL.noop,
        )
    ]
```

Confirm `0011_customuser_deidentified_at` is the latest accounts migration on this branch: `ls backend/apps/accounts/migrations`.

- [ ] **Step 7: Sweep and lint**

Run: `git grep -nIiE "otp|totp|2fa|two.?factor|allow_unenrolled_staff|StaffEnrolmentRequired" -- backend ':!backend/apps/accounts/migrations/0012_drop_otp_tables.py'`. Expected: only the overturn legacy mapping (Task 1), the new test file, and unrelated words (for example `notes`). Then `cd backend && ruff check . && ruff format --check .`.

- [ ] **Step 8: Commit**

```bash
git add -A backend
git commit -m "refactor(accounts): remove two-factor authentication; staff sign in with a password"
```

### Task 3: Frontend without 2FA

**Files:**
- Delete: `frontend/src/app/dashboard/two-factor/` (whole directory), `frontend/src/__tests__/pages/TwoFactorSetupPage.test.tsx`
- Modify: `frontend/src/app/(auth)/login/page.tsx`, `frontend/src/hooks/useAuth.tsx:49-80`, `frontend/src/lib/auth.ts`, `frontend/src/lib/api.ts:191,201-205`
- Test: `frontend/src/__tests__/pages/LoginPage.test.tsx`, `frontend/src/__tests__/hooks/useAuth.test.tsx`

**Interfaces:**
- Consumes: Task 2 login body `{"user": {...}}`.
- Produces: `login(username: string, password: string): Promise<void>`. `LoginResult` is deleted.

- [ ] **Step 1: Tests first**

`LoginPage.test.tsx`: delete the two 2FA tests (`prompts for a 2FA code…`, `shows the server error when the 2FA code is wrong…`). Add:

```tsx
  it('never asks for an authentication code', async () => {
    mockLogin.mockResolvedValueOnce(undefined)
    render(<LoginPage />)
    await userEvent.type(screen.getByLabelText('Username'), 'officer1')
    await userEvent.type(screen.getByLabelText('Password'), 'pw')
    await userEvent.click(screen.getByRole('button', { name: 'Sign In' }))
    await waitFor(() => expect(mockLogin).toHaveBeenCalledWith('officer1', 'pw'))
    expect(screen.queryByLabelText('Authentication code')).not.toBeInTheDocument()
  })
```

Use the file's existing mock name for `login` (read the top of the file) in place of `mockLogin` if it differs.

`useAuth.test.tsx`: rename `describe('two-factor login'` to `describe('login'`. Delete the three tests about `otp_required`, `otp_token` and the 2FA setup redirect. Keep `rejects an unexpected login response…`. Add a test, built the same way as the existing ones in that block (MSW `server.use(http.post('*/auth/login/', …))` and the existing harness component), asserting that an officer login response `{ user: { ...mockUser, username: 'officer1', role: 'officer' } }` leads to `mockReplace` being called with `'/dashboard'`.

- [ ] **Step 2: Run red**

Run: `cd frontend && npx vitest run src/__tests__/pages/LoginPage.test.tsx src/__tests__/hooks/useAuth.test.tsx`. Expected: the new LoginPage test fails, because current code calls `login('officer1', 'pw')` and that passes. If it passes, tighten it: render the page with `mockLogin` resolving `{ status: 'otp_required' }` and assert the code field still never appears. The officer redirect test passes already and guards behaviour.

- [ ] **Step 3: Implement**

`lib/auth.ts`: delete the `LoginResult` type and its doc comment. Set `login: (username: string, password: string) => Promise<void>;` and the default `login: async () => {},`.

`hooks/useAuth.tsx`:

```tsx
  const login = useCallback(async (username: string, password: string) => {
    // Ensure we have a CSRF token before the login POST
    await authApi.getCsrfToken()
    const { data } = await authApi.login({ username, password })
    if (!data?.user?.role || !data.user.username) {
      throw new Error('Unexpected login response from the server.')
    }

    // A new session starts with an empty cache: React Query keys are not
    // user-scoped, so anything cached before this point belongs to whoever
    // used this browser last.
    queryClient.clear()
    clearForeignDraft(data.user.username)
    // Server sets HttpOnly cookies; we keep only the non-PII render hints
    storeSessionUser(data.user)
    setUser(data.user)
    setIsLoading(false)
    router.replace(data.user.role === 'customer' ? '/apply' : '/dashboard')
  }, [router, queryClient])
```

Drop `type LoginResult` from the import.

`lib/api.ts`: `login: (data: { username: string; password: string }) => api.post('/auth/login/', data),`. Delete the comment and the three `twoFactor*` entries.

`login/page.tsx`: remove the `needsCode` and `code` state, `startOver`, the OTP input branch, the "Use a different account" button and the `otp_required` check. The submit handler becomes `await login(username, password)` inside the try, with `setError(errorDetail(err, 'Invalid credentials. Please try again.'))` in the catch. The heading is fixed to `Welcome back` and `Sign in to your account to continue`. The button reads `{isLoading ? 'Signing in...' : 'Sign In'}`.

Delete `app/dashboard/two-factor/` and `TwoFactorSetupPage.test.tsx`. Then run `git grep -nIiE "two-factor|twoFactor|otp|2fa" -- frontend/src`. Expected: no hits.

- [ ] **Step 4: Run green**

Run: `cd frontend && npx vitest run && npx tsc --noEmit && npm run lint`. Expected: all pass with no type errors.

- [ ] **Step 5: Commit**

```bash
git add -A frontend
git commit -m "refactor(frontend): sign-in is username and password only; 2FA page removed"
```

### Task 4: Docs

**Files:**
- Modify: `docs/adr/008-security-architecture.md:24`, `docs/runbooks/operations.md:572,692`, `CHANGELOG.md` (new Unreleased entry)

Historical specs and plans under `docs/superpowers/` stay as written. They record past decisions.

- [ ] **Step 1: Edit**
  - ADR 008: replace the 2FA bullet with "**Two-factor authentication:** removed on 2026-10-03 at the owner's request. Staff accounts rely on passwords, login throttling and account lockout; high-value overturns stay behind the `second_approver` gate."
  - `operations.md:572`: the modes are `off` and `second_approver`, and the legacy `2fa` maps to `second_approver`. Line 692: replace `` `2fa` or `off` `` with `` `off` ``. Read the table first to confirm the column meaning.
  - `CHANGELOG.md`: under Unreleased, add "Removed: two-factor authentication (TOTP enrolment, the login code step, the staff enrolment gate and the OTP admin login). A migration drops the stored TOTP devices. `DECISION_OVERTURN_GATE_MODE=2fa` now means `second_approver`."
- [ ] **Step 2: Commit**: `git commit -am "docs: record the removal of two-factor authentication"`

### Task 5: Deliver part 1

- [ ] **Step 1:** `git push -u origin refactor/remove-2fa`
- [ ] **Step 2:** Push `review/integration-2026-10` and open a PR for it into `fix/senior-review-findings`, titled "chore: integrate the open review stack (all leaves except #271)". Open the 2FA PR into `review/integration-2026-10`, using the repo PR template if one exists.
- [ ] **Step 3:** Close #271 with a comment: "Superseded: the owner decided to remove two-factor authentication. See #<new PR>."
- [ ] **Step 4:** `gh pr checks <new PR> --watch=false`. Poll briefly; do not block on long waits. On a backend test failure, read the log, fix with a test-first change, and push.

---

## Part 2: audit, verify, fix

### Task 6: Five read-only audits in parallel

- [ ] Dispatch five agents in one message against `C:/Users/Admin/loan-review-2026-10` at the head of `refactor/remove-2fa`. Areas: backend correctness A (`accounts`, `loans`, `config`); backend correctness B (`ml_engine`, `agents`, `email_engine`, Celery tasks); frontend; security; architecture and design principles. Each agent is read-only: no edits, no commits, no `docker` and no env or secret reads. Each returns findings as `file:line | severity | failure scenario | fix sketch`, and is told to load `code-review-extras` and apply its open observations.
- [ ] Merge duplicates. Save the raw findings to the scratchpad.

### Task 7: Verify

- [ ] For each Critical, High and Medium finding, an independent verifier agent reads the cited code and returns CONFIRMED (with evidence) or REJECTED. Drop the rejected ones.

### Task 8: Fix plan and fixes

- [ ] Append one task per fix group to this plan, in Task 1's format: a failing test, the fix, lint, commit. Group by area. Branch names follow `fix/review-2026-10-<area>`, stacked on `refactor/remove-2fa`.
- [ ] Execute the groups. Groups that touch disjoint files run in parallel worktrees; overlapping groups run in sequence.
- [ ] Push each branch and open a PR. Check CI as in Task 5.

## Part 3: simplify and report

### Task 9: Simplify

- [ ] Run `/simplify` (load `code-review-extras` alongside it) over the files changed in Parts 1 and 2. Behaviour-preserving only. Commit as `refactor: simplify pass over the review changes` on the last branch of the stack.

### Task 10: Report

- [ ] Write `docs/reviews/2026-10-03-senior-review.md`: what was fixed (with PR links); ranked Low items and nits; architecture refactors proposed but not done, each with cost and benefit. Commit and push.
- [ ] Final summary to the owner: PR list, CI state, accepted risks, and what needs their decision.
