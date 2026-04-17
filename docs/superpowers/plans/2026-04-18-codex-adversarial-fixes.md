# v1.9.3 — Security & Reliability Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the four high-severity fixes from the 2026-04-18 Codex adversarial review as four atomic, independently mergeable PRs stacked on master.

**Architecture:** Each fix is scoped to its own PR with its own test surface. PR 1 tightens cookie-JWT auth with CSRF enforcement. PR 2 removes public ops endpoints and gates them behind auth. PR 3 makes orchestration idempotent by default with a staff-only force override. PR 4 adds a durable submission path via `transaction.on_commit` + outbox + retry beat task.

**Tech Stack:** Django 5 + DRF, Celery + Redis + beat, Next.js 15 + TanStack Query, pytest + pytest-django, Jest + React Testing Library, Kubernetes ingress-nginx, Prometheus.

**Spec:** `docs/superpowers/specs/2026-04-18-codex-adversarial-fixes-design.md`

---

## PR 1 — CSRF enforcement on cookie auth

**Branch:** `fix/csrf-on-cookie-auth`

**Files:**
- Modify: `backend/apps/accounts/authentication.py`
- Modify: `backend/tests/test_auth_security.py` (append new test class)
- Modify: `CHANGELOG.md`

### Task 1.1: Write failing CSRF-enforcement tests

**Files:**
- Modify: `backend/tests/test_auth_security.py`

- [ ] **Step 1: Append a new test class**

Add this class to the end of `backend/tests/test_auth_security.py`:

```python
@pytest.mark.django_db
class TestCookieAuthCSRFEnforcement:
    """Cookie-based JWT auth must enforce CSRF on mutating requests."""

    def _login(self, client, user):
        resp = client.post(
            LOGIN_URL,
            {"username": user.username, "password": PASSWORD},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.content
        return resp

    def test_cookie_auth_without_csrf_header_rejected(self, auth_client, login_user):
        """POST with cookie auth but no X-CSRFToken must return 403 CSRF Failed."""
        # APIClient by default has enforce_csrf_checks=False; create an enforcing client
        client = APIClient(enforce_csrf_checks=True)
        self._login(client, login_user)

        # Strip the CSRF header but keep the cookie (browser-like cross-site replay)
        resp = client.post("/api/v1/loans/", data={"loan_amount": 1000}, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        body = resp.json() if resp.content else {}
        assert "CSRF" in (body.get("detail") or "")

    def test_cookie_auth_with_valid_csrf_header_accepted(self, auth_client, login_user):
        """POST with cookie auth AND a valid X-CSRFToken must pass CSRF."""
        client = APIClient(enforce_csrf_checks=True)
        self._login(client, login_user)

        # Grab the csrftoken cookie and pass it back as X-CSRFToken
        csrf_cookie = client.cookies.get("csrftoken")
        assert csrf_cookie is not None, "Login should set csrftoken cookie"
        resp = client.post(
            "/api/v1/loans/",
            data={},  # Empty body -> 400 from serializer, but CSRF check passes first
            format="json",
            HTTP_X_CSRFTOKEN=csrf_cookie.value,
        )
        # We only care that it's NOT 403-CSRF; serializer validation errors are fine
        assert resp.status_code != status.HTTP_403_FORBIDDEN or \
            "CSRF" not in (resp.json().get("detail") or "")

    def test_bearer_header_auth_bypasses_csrf(self, auth_client, login_user):
        """Authorization: Bearer path (programmatic clients) must NOT require CSRF."""
        from rest_framework_simplejwt.tokens import RefreshToken

        token = str(RefreshToken.for_user(login_user).access_token)
        client = APIClient(enforce_csrf_checks=True)
        resp = client.post(
            "/api/v1/loans/",
            data={},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        # Should not be CSRF-403; it may be 400 from serializer, but never CSRF
        assert not (resp.status_code == 403 and "CSRF" in (resp.json().get("detail") or ""))
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd backend && pytest tests/test_auth_security.py::TestCookieAuthCSRFEnforcement -v
```

Expected: `test_cookie_auth_without_csrf_header_rejected` FAILS (current code returns 200/400, not 403). Other two may pass already.

### Task 1.2: Implement CSRF enforcement in CookieJWTAuthentication

**Files:**
- Modify: `backend/apps/accounts/authentication.py`

- [ ] **Step 1: Replace the file with the hardened version**

Replace the entire contents of `backend/apps/accounts/authentication.py` with:

```python
"""Custom JWT authentication that reads tokens from HttpOnly cookies.

Falls back to the standard Authorization header for API clients / tests.
Enforces Django CSRF validation on the cookie path so that cookie-authenticated
mutating requests cannot be replayed cross-site. The header fallback (bearer
tokens) is exempt because the explicit Authorization header itself is proof of
intent and is not sent automatically by browsers.
"""

from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware
from rest_framework import exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication


class _CSRFCheck(CsrfViewMiddleware):
    """Expose CSRF failure reasons rather than returning a 403 response."""

    def _reject(self, request, reason):
        # Returning the reason (string) lets the caller raise PermissionDenied
        return reason


class CookieJWTAuthentication(JWTAuthentication):
    """Authenticate using HttpOnly cookie first, then fall back to header."""

    def authenticate(self, request):
        cookie_name = getattr(settings, "JWT_ACCESS_COOKIE_NAME", "access_token")
        raw_token = request.COOKIES.get(cookie_name)

        if raw_token is not None:
            validated_token = self.get_validated_token(raw_token)
            user = self.get_user(validated_token)
            self._enforce_csrf(request)
            return user, validated_token

        return super().authenticate(request)

    def _enforce_csrf(self, request):
        """Run Django's CSRF check; raise PermissionDenied on failure."""
        check = _CSRFCheck(lambda r: None)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            raise exceptions.PermissionDenied(f"CSRF Failed: {reason}")
```

- [ ] **Step 2: Run tests to verify they pass**

Run:
```bash
cd backend && pytest tests/test_auth_security.py::TestCookieAuthCSRFEnforcement -v
```

Expected: all three tests PASS.

- [ ] **Step 3: Run full auth-security suite to catch regressions**

Run:
```bash
cd backend && pytest tests/test_auth_security.py -v
```

Expected: all existing tests still PASS.

### Task 1.3: Update CHANGELOG and commit

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add a new v1.9.3 section**

Open `CHANGELOG.md` and insert a new section at the top (above the current v1.9.2 section):

```markdown
## v1.9.3 — Security & Reliability Hardening (2026-04-18)

### Security

- Enforce Django CSRF validation on cookie-based JWT authentication. Mutating requests authenticated via the `access_token` HttpOnly cookie now require a matching `X-CSRFToken` header. Bearer-header auth is unchanged. Addresses Codex adversarial review finding #1.
```

- [ ] **Step 2: Commit PR 1**

```bash
git checkout -b fix/csrf-on-cookie-auth
git add backend/apps/accounts/authentication.py backend/tests/test_auth_security.py CHANGELOG.md
git commit -m "fix(auth): enforce CSRF on cookie JWT authentication

Cookie-authenticated mutating requests now require a matching X-CSRFToken
header. Header-based (bearer token) auth is unchanged — the explicit
Authorization header itself is proof of intent that cookies lack.

Addresses Codex adversarial review finding #1 (2026-04-18).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## PR 2 — Ops endpoints hardening

**Branch:** `fix/ops-endpoints-hardening`

**Files:**
- Create: `backend/config/ops_auth.py` (new decorator)
- Modify: `backend/config/urls.py`
- Modify: `k8s/ingress.yaml`
- Modify: `monitoring/prometheus.yml`
- Create: `backend/tests/test_ops_endpoints.py`
- Modify: `backend/docs/RUNBOOK.md`
- Modify: `CHANGELOG.md`

### Task 2.1: Create the ops-auth decorator

**Files:**
- Create: `backend/config/ops_auth.py`

- [ ] **Step 1: Write the decorator**

Create `backend/config/ops_auth.py` with:

```python
"""Authentication helper for operational endpoints (metrics, deep health).

Accepts either:
  1. Staff session (user.is_staff True) — for ad-hoc inspection via the admin
  2. X-Health-Token header matching settings.HEALTH_CHECK_TOKEN — for Prometheus
     scrapes and automated tooling

Denies all other requests with 403.
"""

import hmac
from functools import wraps

from django.conf import settings
from django.http import JsonResponse


def require_ops_auth(view_func):
    """Gate a view behind staff session OR X-Health-Token header."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if getattr(request.user, "is_staff", False):
            return view_func(request, *args, **kwargs)

        token = getattr(settings, "HEALTH_CHECK_TOKEN", "") or ""
        provided = request.headers.get("X-Health-Token", "") or ""
        if token and hmac.compare_digest(provided.encode(), token.encode()):
            return view_func(request, *args, **kwargs)

        return JsonResponse({"error": "unauthorized"}, status=403)

    return _wrapped
```

- [ ] **Step 2: Commit the scaffolding (no tests yet — tested via urls.py in Task 2.3)**

No commit yet; we commit PR 2 as a single logical unit at the end.

### Task 2.2: Write failing ops-endpoint tests

**Files:**
- Create: `backend/tests/test_ops_endpoints.py`

- [ ] **Step 1: Write the test file**

Create `backend/tests/test_ops_endpoints.py`:

```python
"""Tests for operational endpoint gating: /metrics and /api/v1/health/deep/.

Both endpoints must be unreachable without either staff session or a valid
X-Health-Token. Deep health must also refuse to respond in production-like
settings when HEALTH_CHECK_TOKEN is unset.
"""

import pytest
from django.test.utils import override_settings
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser


@pytest.fixture
def staff_user(db):
    return CustomUser.objects.create_user(
        username="ops_staff",
        email="ops@test.com",
        password="testpass123",
        role="admin",
        is_staff=True,
        first_name="Ops",
        last_name="Staff",
    )


@pytest.fixture
def regular_user(db):
    return CustomUser.objects.create_user(
        username="ops_regular",
        email="regular@test.com",
        password="testpass123",
        role="customer",
        is_staff=False,
        first_name="Regular",
        last_name="User",
    )


@pytest.mark.django_db
class TestMetricsEndpointGating:
    """GET /metrics must be gated behind staff session or X-Health-Token."""

    def test_unauthenticated_denied(self):
        client = APIClient()
        resp = client.get("/metrics")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_non_staff_user_denied(self, regular_user):
        client = APIClient()
        client.force_authenticate(user=regular_user)
        resp = client.get("/metrics")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_staff_user_allowed(self, staff_user):
        client = APIClient()
        client.force_authenticate(user=staff_user)
        resp = client.get("/metrics")
        assert resp.status_code == status.HTTP_200_OK
        assert b"django_http_requests_total" in resp.content or b"# HELP" in resp.content

    @override_settings(HEALTH_CHECK_TOKEN="s3cr3t-ops-token")
    def test_valid_token_header_allowed(self):
        client = APIClient()
        resp = client.get("/metrics", HTTP_X_HEALTH_TOKEN="s3cr3t-ops-token")
        assert resp.status_code == status.HTTP_200_OK

    @override_settings(HEALTH_CHECK_TOKEN="s3cr3t-ops-token")
    def test_invalid_token_header_denied(self):
        client = APIClient()
        resp = client.get("/metrics", HTTP_X_HEALTH_TOKEN="wrong-token")
        assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestDeepHealthConfigured:
    """Deep health must refuse to respond if token is unconfigured in production."""

    @override_settings(DEBUG=False, HEALTH_CHECK_TOKEN="")
    def test_unconfigured_token_in_prod_returns_503(self):
        client = APIClient()
        resp = client.get("/api/v1/health/deep/")
        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "not configured" in resp.json().get("error", "").lower()

    @override_settings(DEBUG=True, HEALTH_CHECK_TOKEN="")
    def test_unconfigured_token_in_debug_allowed(self):
        """Local dev with DEBUG=True may run deep health without a token."""
        client = APIClient()
        resp = client.get("/api/v1/health/deep/")
        # 200 healthy or 503 degraded (no DB/Redis locally) — both OK, not "unconfigured"
        body = resp.json()
        assert "error" not in body or "not configured" not in body.get("error", "")

    @override_settings(DEBUG=False, HEALTH_CHECK_TOKEN="health-tok-xyz")
    def test_configured_token_wrong_header_denied(self):
        client = APIClient()
        resp = client.get("/api/v1/health/deep/", HTTP_X_HEALTH_TOKEN="wrong")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    @override_settings(DEBUG=False, HEALTH_CHECK_TOKEN="health-tok-xyz")
    def test_configured_token_correct_header_allowed(self):
        client = APIClient()
        resp = client.get("/api/v1/health/deep/", HTTP_X_HEALTH_TOKEN="health-tok-xyz")
        # Status may be 200 or 503 depending on DB/Redis availability — both pass auth
        assert resp.status_code in (200, 503)
        body = resp.json()
        assert body.get("error") != "unauthorized"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd backend && pytest tests/test_ops_endpoints.py -v
```

Expected: most tests FAIL — `/metrics` currently has no auth, deep health is permissive.

### Task 2.3: Gate /metrics in urls.py and tighten deep health

**Files:**
- Modify: `backend/config/urls.py`

- [ ] **Step 1: Replace the Prometheus metrics URL inclusion**

In `backend/config/urls.py`, find the line:
```python
path("", include("django_prometheus.urls")),
```

Replace it with:
```python
from django_prometheus.exports import ExportToDjangoView  # at the top with other imports

from config.ops_auth import require_ops_auth  # at the top

# ...inside urlpatterns:
path("metrics", require_ops_auth(ExportToDjangoView), name="prometheus-django-metrics"),
```

- [ ] **Step 2: Tighten `deep_health_check` to refuse when unconfigured in prod**

In `deep_health_check`, replace the opening token block:

```python
    from django.conf import settings as django_settings

    token = getattr(django_settings, "HEALTH_CHECK_TOKEN", "")
    if token:
        provided = request.headers.get("X-Health-Token", "")
        is_staff = getattr(request.user, "is_staff", False)
        if not hmac.compare_digest(provided.encode(), token.encode()) and not is_staff:
            return JsonResponse({"error": "unauthorized"}, status=403)
```

with:

```python
    from django.conf import settings as django_settings

    token = getattr(django_settings, "HEALTH_CHECK_TOKEN", "") or ""
    debug = getattr(django_settings, "DEBUG", False)

    if not token:
        if not debug:
            return JsonResponse(
                {"error": "deep health not configured — set HEALTH_CHECK_TOKEN"},
                status=503,
            )
        # DEBUG=True: allow open access for local development
    else:
        provided = request.headers.get("X-Health-Token", "") or ""
        is_staff = getattr(request.user, "is_staff", False)
        if not hmac.compare_digest(provided.encode(), token.encode()) and not is_staff:
            return JsonResponse({"error": "unauthorized"}, status=403)
```

- [ ] **Step 3: Run the new test file to verify it passes**

Run:
```bash
cd backend && pytest tests/test_ops_endpoints.py -v
```

Expected: all tests PASS.

- [ ] **Step 4: Run the rest of the test suite to catch regressions**

Run:
```bash
cd backend && pytest tests/ -x -q
```

Expected: no regressions.

### Task 2.4: Remove /metrics from public ingress

**Files:**
- Modify: `k8s/ingress.yaml`

- [ ] **Step 1: Delete the /metrics path rule**

In `k8s/ingress.yaml`, delete these seven lines:
```yaml
          - path: /metrics
            pathType: Prefix
            backend:
              service:
                name: backend
                port:
                  number: 8000
```

The resulting `paths:` list should contain only `/api` and `/`.

### Task 2.5: Add auth header to Prometheus scrape config

**Files:**
- Modify: `monitoring/prometheus.yml`

- [ ] **Step 1: Add the authorization header to the django-backend job**

In `monitoring/prometheus.yml`, find:

```yaml
  - job_name: 'django-backend'
    metrics_path: '/metrics'
    static_configs:
      - targets: ['backend:8000']
    scrape_interval: 10s
```

Replace with:

```yaml
  - job_name: 'django-backend'
    metrics_path: '/metrics'
    static_configs:
      - targets: ['backend:8000']
    scrape_interval: 10s
    authorization:
      type: Bearer
      credentials_file: /etc/prometheus/health_check_token
```

Note: the Bearer scheme won't match our `X-Health-Token` header. Prometheus does not natively support arbitrary custom headers in the open-source config, so use its `http_headers` feature instead:

```yaml
  - job_name: 'django-backend'
    metrics_path: '/metrics'
    static_configs:
      - targets: ['backend:8000']
    scrape_interval: 10s
    http_headers:
      X-Health-Token:
        values:
          - ${HEALTH_CHECK_TOKEN}
```

The `http_headers` feature is available in Prometheus 2.44+. If `envsubst` is not applied to the file, hardcode the value or use the `credentials_file` variant with a custom header — whichever matches the existing deployment model.

- [ ] **Step 2: Document the token requirement in docker-compose**

Grep for `HEALTH_CHECK_TOKEN` in `docker-compose*.yml`:
```bash
grep -rn "HEALTH_CHECK_TOKEN" docker-compose*.yml
```

If not already set, add `HEALTH_CHECK_TOKEN` to the `prometheus` service environment block (or `.env.example`).

### Task 2.6: Update RUNBOOK and CHANGELOG, commit PR 2

**Files:**
- Modify: `backend/docs/RUNBOOK.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update RUNBOOK.md**

In `backend/docs/RUNBOOK.md`, find the row:
```markdown
| GET | `/metrics` | No | Prometheus metrics (django-prometheus) |
```

Replace with:
```markdown
| GET | `/metrics` | **Yes** (staff session or X-Health-Token) | Prometheus metrics (django-prometheus). Not publicly routed. |
```

- [ ] **Step 2: Update CHANGELOG**

Add to the `v1.9.3` section (under Security):

```markdown
- Gate `/metrics` and deep-health behind staff session or `X-Health-Token` header. Remove `/metrics` from public Kubernetes ingress. Deep health refuses to respond in production when `HEALTH_CHECK_TOKEN` is unset. Addresses Codex adversarial review finding #2.
```

- [ ] **Step 3: Commit PR 2**

```bash
git checkout master && git pull
git checkout -b fix/ops-endpoints-hardening
git add backend/config/ops_auth.py backend/config/urls.py \
  backend/tests/test_ops_endpoints.py \
  k8s/ingress.yaml monitoring/prometheus.yml \
  backend/docs/RUNBOOK.md CHANGELOG.md
git commit -m "fix(ops): gate metrics and deep health behind auth

- /metrics now requires staff session OR X-Health-Token header
- Remove /metrics from public Kubernetes ingress (still reachable in-cluster)
- deep_health_check refuses when HEALTH_CHECK_TOKEN unset in non-DEBUG envs
- Prometheus scrape config carries the token via http_headers

Addresses Codex adversarial review finding #2 (2026-04-18).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## PR 3 — Orchestration force guard

**Branch:** `fix/orchestration-force-guard`

**Files:**
- Modify: `backend/apps/agents/views.py` (`OrchestrateView.post`)
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/hooks/useAgentStatus.ts`
- Modify: `frontend/src/app/dashboard/human-review/page.tsx`
- Create: `backend/tests/test_orchestration_force.py`
- Modify: `CHANGELOG.md`

### Task 3.1: Write failing backend force-guard tests

**Files:**
- Create: `backend/tests/test_orchestration_force.py`

- [ ] **Step 1: Write the test file**

Create `backend/tests/test_orchestration_force.py`:

```python
"""Tests for the staff-only, reason-audited force rerun on /agents/orchestrate/."""

from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.loans.models import AuditLog


@pytest.fixture
def customer(db):
    return CustomUser.objects.create_user(
        username="cust_force",
        email="cust@test.com",
        password="testpass123",
        role="customer",
        first_name="Cust",
        last_name="F",
    )


@pytest.fixture
def officer(db):
    return CustomUser.objects.create_user(
        username="officer_force",
        email="officer@test.com",
        password="testpass123",
        role="officer",
        first_name="Off",
        last_name="F",
    )


@pytest.fixture
def loan_app(db, customer):
    from apps.loans.models import LoanApplication
    return LoanApplication.objects.create(
        applicant=customer,
        loan_amount=20000,
        annual_income=80000,
        credit_score=700,
        loan_term_months=24,
        debt_to_income=0.3,
        employment_length=5,
        purpose="personal",
        home_ownership="rent",
    )


@pytest.fixture
def completed_run(db, loan_app):
    from apps.agents.models import AgentRun
    return AgentRun.objects.create(
        application_id=loan_app.id,
        status=AgentRun.Status.COMPLETED,
    )


@pytest.mark.django_db
class TestOrchestrationForceGuard:
    @patch("apps.agents.views.orchestrate_pipeline_task.delay")
    def test_customer_with_force_true_denied(self, mock_delay, customer, loan_app):
        client = APIClient()
        client.force_authenticate(user=customer)
        resp = client.post(f"/api/v1/agents/orchestrate/{loan_app.id}/?force=true")
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert "staff" in (resp.json().get("detail") or "").lower()
        assert mock_delay.call_count == 0

    @patch("apps.agents.views.orchestrate_pipeline_task.delay")
    def test_staff_force_without_reason_denied(self, mock_delay, officer, loan_app):
        client = APIClient()
        client.force_authenticate(user=officer)
        resp = client.post(f"/api/v1/agents/orchestrate/{loan_app.id}/?force=true")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "reason" in (resp.json().get("detail") or "").lower()
        assert mock_delay.call_count == 0

    @patch("apps.agents.views.orchestrate_pipeline_task.delay")
    def test_staff_force_with_reason_dispatches_and_audits(
        self, mock_delay, officer, loan_app
    ):
        mock_delay.return_value.id = "task-abc"
        client = APIClient()
        client.force_authenticate(user=officer)
        resp = client.post(
            f"/api/v1/agents/orchestrate/{loan_app.id}/?force=true&reason=bias_fix"
        )
        assert resp.status_code == status.HTTP_202_ACCEPTED
        mock_delay.assert_called_once_with(str(loan_app.id), force=True)

        audit_entries = AuditLog.objects.filter(
            action="pipeline_force_rerun",
            resource_id=str(loan_app.id),
        )
        assert audit_entries.exists()
        assert audit_entries.first().details.get("reason") == "bias_fix"

    @patch("apps.agents.views.orchestrate_pipeline_task.delay")
    def test_customer_non_force_on_completed_returns_existing(
        self, mock_delay, customer, loan_app, completed_run
    ):
        """Non-force path on a completed loan returns existing run without dispatching."""
        mock_delay.return_value.id = "should-not-dispatch"
        client = APIClient()
        client.force_authenticate(user=customer)
        resp = client.post(f"/api/v1/agents/orchestrate/{loan_app.id}/")
        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert body.get("status") == "already_completed"
        assert body.get("existing_run_id") == str(completed_run.id)
        assert mock_delay.call_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd backend && pytest tests/test_orchestration_force.py -v
```

Expected: all four tests FAIL — current view has no force guard or short-circuit.

### Task 3.2: Implement the force guard in OrchestrateView

**Files:**
- Modify: `backend/apps/agents/views.py`

- [ ] **Step 1: Replace OrchestrateView.post with the guarded version**

In `backend/apps/agents/views.py`, find the `OrchestrateView` class (around line 167–190) and replace its `post` method body with:

```python
    def post(self, request, loan_id):
        """Trigger pipeline orchestration for a loan application.

        Non-force path (default): idempotent. If a completed AgentRun exists, return
        it without dispatching. Otherwise dispatch a new run.

        Force path: staff-only, requires `reason` query/body param, writes an
        AuditLog entry before dispatching.
        """
        check_loan_access(request, loan_id)

        force = request.query_params.get("force", "").lower() == "true"
        reason = (
            request.query_params.get("reason")
            or (request.data.get("reason") if isinstance(request.data, dict) else None)
            or ""
        ).strip()

        if force:
            if request.user.role not in ("admin", "officer"):
                return Response(
                    {"detail": "force rerun requires staff role"},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if not reason:
                return Response(
                    {"detail": "reason is required for force rerun"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            # Idempotent short-circuit: if a completed run exists, return it
            from apps.agents.models import AgentRun
            existing = (
                AgentRun.objects.filter(
                    application_id=loan_id,
                    status=AgentRun.Status.COMPLETED,
                )
                .order_by("-created_at")
                .first()
            )
            if existing is not None:
                return Response(
                    {
                        "status": "already_completed",
                        "existing_run_id": str(existing.id),
                    },
                    status=status.HTTP_200_OK,
                )

        task = orchestrate_pipeline_task.delay(str(loan_id), force=force)

        audit_action = "pipeline_force_rerun" if force else "pipeline_triggered"
        audit_details = {"task_id": task.id}
        if force:
            audit_details["reason"] = reason

        AuditLog.objects.create(
            user=request.user,
            action=audit_action,
            resource_type="LoanApplication",
            resource_id=str(loan_id),
            details=audit_details,
            ip_address=request.META.get("REMOTE_ADDR"),
        )

        return Response(
            {"task_id": task.id, "status": "pipeline_queued"},
            status=status.HTTP_202_ACCEPTED,
        )
```

- [ ] **Step 2: Run the new test file**

Run:
```bash
cd backend && pytest tests/test_orchestration_force.py -v
```

Expected: all four tests PASS.

- [ ] **Step 3: Run the agents test suite for regressions**

Run:
```bash
cd backend && pytest tests/ -k "agent or orchestrat" -v
```

Expected: no regressions.

### Task 3.3: Update frontend API layer

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Replace the `agentsApi.orchestrate` line and add `forceRerun`**

In `frontend/src/lib/api.ts`, find:

```typescript
export const agentsApi = {
  orchestrate: (loanId: string) => api.post(`/agents/orchestrate/${loanId}/?force=true`, null, { timeout: 60000 }),
```

Replace with:

```typescript
export const agentsApi = {
  orchestrate: (loanId: string) => api.post(`/agents/orchestrate/${loanId}/`, null, { timeout: 60000 }),
  forceRerun: (loanId: string, reason: string) =>
    api.post(
      `/agents/orchestrate/${loanId}/?force=true&reason=${encodeURIComponent(reason)}`,
      null,
      { timeout: 60000 },
    ),
```

### Task 3.4: Add the `useForceRerun` React hook

**Files:**
- Modify: `frontend/src/hooks/useAgentStatus.ts`

- [ ] **Step 1: Add a new hook below `useOrchestrate`**

In `frontend/src/hooks/useAgentStatus.ts`, append this hook after the existing `useOrchestrate` (around line 77):

```typescript
export function useForceRerun() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ loanId, reason }: { loanId: string; reason: string }) => {
      const { data } = await agentsApi.forceRerun(loanId, reason)
      return data
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['agentRun', variables.loanId] })
      queryClient.invalidateQueries({ queryKey: ['application', variables.loanId] })
      queryClient.invalidateQueries({ queryKey: ['email', variables.loanId] })
    },
    onError: (error: any) => {
      if (error?.response?.status === 403) {
        throw new Error('Force rerun requires staff role.')
      }
      if (error?.response?.status === 400) {
        throw new Error(error?.response?.data?.detail || 'A reason is required.')
      }
      if (error?.response?.status === 429) {
        const retryAfter = error.response.headers?.['retry-after']
        const waitSec = retryAfter ? parseInt(retryAfter, 10) : 60
        throw new Error(`Rate limited — try again in ${waitSec}s`)
      }
      throw error
    },
  })
}
```

### Task 3.5: Wire the force-rerun UI into the human-review page

**Files:**
- Modify: `frontend/src/app/dashboard/human-review/page.tsx`

- [ ] **Step 1: Read the current file**

Read `frontend/src/app/dashboard/human-review/page.tsx` in full to understand its structure. Find the section where individual review items are rendered.

- [ ] **Step 2: Add a Force-Rerun button + reason modal**

For each item row (scoped to staff — this page is already staff-gated), add a "Force Rerun" button that:
- Opens an inline dialog/popover with a textarea labeled "Reason (required)"
- On submit, calls `forceRerunMutation.mutate({ loanId, reason })`
- Disables submit while pending
- Surfaces `.error?.message` under the textarea

Import:
```typescript
import { useForceRerun } from '@/hooks/useAgentStatus'
```

Example minimal inline dialog (adapt to the page's existing shadcn components):

```tsx
// Uses the same Dialog + native <textarea> pattern as ReviewActionModal
// (there is no shadcn Textarea in this project).

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import { useForceRerun } from '@/hooks/useAgentStatus'

function ForceRerunButton({ loanId }: { loanId: string }) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const force = useForceRerun()

  const submit = async () => {
    setError(null)
    try {
      await force.mutateAsync({ loanId, reason })
      setOpen(false)
      setReason('')
    } catch (e: any) {
      setError(e?.message || 'Force rerun failed')
    }
  }

  return (
    <>
      <Button variant="destructive" size="sm" onClick={() => setOpen(true)}>
        Force Rerun
      </Button>
      <Dialog open={open} onOpenChange={(o) => !force.isPending && setOpen(o)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Force pipeline rerun</DialogTitle>
          </DialogHeader>
          <textarea
            className="w-full min-h-[80px] rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            placeholder="Reason (required) — e.g. bias flag resolved, model retrained"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          {error && <p className="text-sm text-red-600">{error}</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={force.isPending}>
              Cancel
            </Button>
            <Button onClick={submit} disabled={!reason.trim() || force.isPending}>
              {force.isPending ? 'Submitting…' : 'Confirm force rerun'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
```

Place `<ForceRerunButton loanId={item.application_id} />` next to the existing per-item actions in the review queue.

- [ ] **Step 3: Verify frontend type-checks and builds**

Run:
```bash
cd frontend && npm run typecheck && npm run lint
```

Expected: no new errors.

- [ ] **Step 4: Verify existing frontend tests still pass**

Run:
```bash
cd frontend && npm test -- --run
```

Expected: all existing tests pass. The `useOrchestrate` test in `__tests__/hooks/usePipelineOrchestration.test.tsx` should continue to pass because the mutation shape is unchanged; only the URL changed.

### Task 3.6: Update CHANGELOG and commit PR 3

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Append to the v1.9.3 section**

Under the existing `v1.9.3` section, add a new subsection:

```markdown
### Reliability

- Orchestrate endpoint is now idempotent by default. `force=true` requires staff role and a non-empty `reason`; writes an `AuditLog(action="pipeline_force_rerun")` entry. Frontend drops unconditional `force=true` and exposes a separate `useForceRerun` hook wired into the staff-only human-review page. Addresses Codex adversarial review finding #3.
```

- [ ] **Step 2: Commit PR 3**

```bash
git checkout master && git pull
git checkout -b fix/orchestration-force-guard
git add backend/apps/agents/views.py backend/tests/test_orchestration_force.py \
  frontend/src/lib/api.ts frontend/src/hooks/useAgentStatus.ts \
  frontend/src/app/dashboard/human-review/page.tsx \
  CHANGELOG.md
git commit -m "fix(agents): make orchestration idempotent, staff-gate force rerun

Non-force orchestrate path short-circuits completed runs and returns the
existing AgentRun ID without dispatch. Force path requires admin/officer
role and a non-empty reason, written to AuditLog before dispatch.

Frontend drops unconditional force=true and wires a reason-collecting
force-rerun action into the staff-only human-review page.

Addresses Codex adversarial review finding #3 (2026-04-18).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## PR 4 — Durable submission outbox

**Branch:** `fix/submission-outbox`

**Files:**
- Modify: `backend/apps/loans/models.py`
- Create: `backend/apps/loans/migrations/NNNN_pipeline_dispatch_outbox.py` (auto-generated)
- Modify: `backend/apps/loans/views.py` (`perform_create`)
- Create: `backend/apps/loans/tasks.py`
- Modify: `backend/config/celery.py` (beat schedule)
- Modify: `backend/apps/loans/admin.py`
- Create: `backend/tests/test_submission_outbox.py`
- Modify: `backend/docs/RUNBOOK.md`
- Modify: `CHANGELOG.md`

### Task 4.1: Add the new model and status

**Files:**
- Modify: `backend/apps/loans/models.py`

- [ ] **Step 1: Add `QUEUE_FAILED` to `LoanApplication.Status`**

In `backend/apps/loans/models.py`, find:
```python
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        APPROVED = "approved", "Approved"
        DENIED = "denied", "Denied"
        REVIEW = "review", "Under Review"
```

Add one line:
```python
        QUEUE_FAILED = "queue_failed", "Queue Dispatch Failed"
```

- [ ] **Step 2: Append the `PipelineDispatchOutbox` model at the bottom of the file**

At the end of `backend/apps/loans/models.py`, add:

```python
class PipelineDispatchOutbox(models.Model):
    """Outbox row for loan applications whose Celery dispatch failed.

    A beat task drains this table on a 60s cadence. Rows that reach
    MAX_DISPATCH_ATTEMPTS remain for operator visibility — they are NOT
    retried further by the automated loop.
    """

    MAX_DISPATCH_ATTEMPTS = 5

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.OneToOneField(
        LoanApplication,
        on_delete=models.CASCADE,
        related_name="dispatch_outbox",
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Pipeline Dispatch Outbox Entry"
        verbose_name_plural = "Pipeline Dispatch Outbox"
        ordering = ["created_at"]

    def __str__(self):
        return f"outbox<{self.application_id}> attempts={self.attempts}"
```

(Assumes `uuid` is already imported — verify.)

### Task 4.2: Generate and apply the migration

**Files:**
- Create: `backend/apps/loans/migrations/NNNN_pipeline_dispatch_outbox.py` (auto)

- [ ] **Step 1: Generate the migration**

```bash
cd backend && python manage.py makemigrations loans
```

Expected output includes: `- Create model PipelineDispatchOutbox` and `- Alter field status on loanapplication`.

- [ ] **Step 2: Inspect the migration file**

```bash
ls -la backend/apps/loans/migrations/
```

Open the newly created migration file and verify:
- Adds `QUEUE_FAILED` to the `status` choices
- Creates `PipelineDispatchOutbox` with the fields above
- No other unintended changes

- [ ] **Step 3: Apply the migration**

```bash
cd backend && python manage.py migrate loans
```

Expected: applied cleanly.

### Task 4.3: Write failing outbox tests

**Files:**
- Create: `backend/tests/test_submission_outbox.py`

- [ ] **Step 1: Write the test file**

Create `backend/tests/test_submission_outbox.py`:

```python
"""Tests for the durable submission outbox.

Covers:
- Happy path: submission dispatches successfully and no outbox row is created.
- Failure path: broker down during dispatch → loan saved, outbox row created,
  status transitions to QUEUE_FAILED.
- Retry: beat task drains an outbox row successfully → deletes row + resets status.
- Exhaustion: beat task leaves a max-attempts row untouched.
"""

from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.loans.models import LoanApplication, PipelineDispatchOutbox


@pytest.fixture
def customer(db):
    return CustomUser.objects.create_user(
        username="cust_outbox",
        email="outbox@test.com",
        password="testpass123",
        role="customer",
        first_name="Out",
        last_name="Box",
    )


@pytest.fixture
def loan_payload():
    return {
        "loan_amount": 15000,
        "annual_income": 75000,
        "credit_score": 680,
        "loan_term_months": 36,
        "debt_to_income": 0.25,
        "employment_length": 4,
        "purpose": "personal",
        "home_ownership": "rent",
    }


@pytest.mark.django_db(transaction=True)
class TestSubmissionOutbox:
    @patch("apps.loans.views.orchestrate_pipeline_task.delay")
    def test_happy_path_no_outbox_row(self, mock_delay, customer, loan_payload):
        mock_delay.return_value.id = "task-ok"
        client = APIClient()
        client.force_authenticate(user=customer)
        resp = client.post("/api/v1/loans/", loan_payload, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert mock_delay.call_count == 1

        loan = LoanApplication.objects.get(id=resp.json()["id"])
        assert loan.status == LoanApplication.Status.PENDING
        assert not PipelineDispatchOutbox.objects.filter(application=loan).exists()

    @patch("apps.loans.views.orchestrate_pipeline_task.delay")
    def test_dispatch_failure_creates_outbox_row(
        self, mock_delay, customer, loan_payload
    ):
        mock_delay.side_effect = RuntimeError("broker unreachable")
        client = APIClient()
        client.force_authenticate(user=customer)
        resp = client.post("/api/v1/loans/", loan_payload, format="json")

        # Submission still succeeds — the user's data is persisted
        assert resp.status_code == status.HTTP_201_CREATED

        loan = LoanApplication.objects.get(id=resp.json()["id"])
        assert loan.status == LoanApplication.Status.QUEUE_FAILED

        outbox = PipelineDispatchOutbox.objects.get(application=loan)
        assert outbox.attempts == 0
        assert "broker unreachable" in outbox.last_error

    @patch("apps.loans.tasks.orchestrate_pipeline_task.delay")
    def test_retry_beat_task_drains_successful_row(
        self, mock_delay, customer, loan_payload
    ):
        from apps.loans.tasks import retry_failed_dispatches

        loan = LoanApplication.objects.create(
            applicant=customer,
            status=LoanApplication.Status.QUEUE_FAILED,
            **loan_payload,
        )
        outbox = PipelineDispatchOutbox.objects.create(application=loan, attempts=2)

        mock_delay.return_value.id = "retry-ok"
        retry_failed_dispatches()

        # Row is drained and loan goes back to pending
        assert not PipelineDispatchOutbox.objects.filter(pk=outbox.pk).exists()
        loan.refresh_from_db()
        assert loan.status == LoanApplication.Status.PENDING
        mock_delay.assert_called_once_with(str(loan.id))

    @patch("apps.loans.tasks.orchestrate_pipeline_task.delay")
    def test_retry_beat_task_records_failure_and_increments_attempts(
        self, mock_delay, customer, loan_payload
    ):
        from apps.loans.tasks import retry_failed_dispatches

        loan = LoanApplication.objects.create(
            applicant=customer,
            status=LoanApplication.Status.QUEUE_FAILED,
            **loan_payload,
        )
        outbox = PipelineDispatchOutbox.objects.create(application=loan, attempts=1)

        mock_delay.side_effect = RuntimeError("still down")
        retry_failed_dispatches()

        outbox.refresh_from_db()
        assert outbox.attempts == 2
        assert "still down" in outbox.last_error
        assert outbox.last_attempt_at is not None
        loan.refresh_from_db()
        assert loan.status == LoanApplication.Status.QUEUE_FAILED

    @patch("apps.loans.tasks.orchestrate_pipeline_task.delay")
    def test_retry_beat_task_skips_exhausted_rows(
        self, mock_delay, customer, loan_payload
    ):
        from apps.loans.tasks import retry_failed_dispatches

        loan = LoanApplication.objects.create(
            applicant=customer,
            status=LoanApplication.Status.QUEUE_FAILED,
            **loan_payload,
        )
        outbox = PipelineDispatchOutbox.objects.create(
            application=loan,
            attempts=PipelineDispatchOutbox.MAX_DISPATCH_ATTEMPTS,
        )

        retry_failed_dispatches()

        outbox.refresh_from_db()
        assert outbox.attempts == PipelineDispatchOutbox.MAX_DISPATCH_ATTEMPTS
        assert mock_delay.call_count == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
cd backend && pytest tests/test_submission_outbox.py -v
```

Expected: all five tests FAIL — the outbox plumbing doesn't exist yet.

### Task 4.4: Implement `perform_create` with on_commit + outbox

**Files:**
- Modify: `backend/apps/loans/views.py`

- [ ] **Step 1: Replace the dispatch block at the end of `perform_create`**

In `backend/apps/loans/views.py`, find the dispatch block (around line 103–111):

```python
        # Auto-trigger AI pipeline for new applications (outside transaction
        # so the committed data is visible to the Celery worker)
        from apps.agents.tasks import orchestrate_pipeline_task

        try:
            orchestrate_pipeline_task.delay(str(instance.pk))
            logger.info("Auto-triggered pipeline for application %s", instance.pk)
        except Exception as e:
            logger.warning("Failed to auto-trigger pipeline for %s: %s", instance.pk, e)
```

Replace with:

```python
        # Durable dispatch: on_commit so the row is visible to the worker,
        # and an outbox fallback so a broker outage never swallows a submission.
        from apps.agents.tasks import orchestrate_pipeline_task
        from apps.loans.models import PipelineDispatchOutbox

        def _dispatch():
            try:
                orchestrate_pipeline_task.delay(str(instance.pk))
                logger.info("Auto-triggered pipeline for application %s", instance.pk)
            except Exception as exc:
                logger.error(
                    "Queue dispatch failed for %s (outbox fallback engaged): %s",
                    instance.pk,
                    exc,
                )
                PipelineDispatchOutbox.objects.create(
                    application=instance,
                    last_error=str(exc)[:1000],
                )
                LoanApplication.objects.filter(pk=instance.pk).update(
                    status=LoanApplication.Status.QUEUE_FAILED
                )

        transaction.on_commit(_dispatch)
```

The surrounding `with transaction.atomic():` context is preserved; `on_commit` is safe inside or outside the atomic block — it fires only after the outer commit.

- [ ] **Step 2: Note — the function is `perform_create`; the dispatch was outside `transaction.atomic()`**

Read the file again to confirm `transaction.on_commit(_dispatch)` is placed OUTSIDE the `with transaction.atomic():` block, at the same indentation as the original dispatch code.

### Task 4.5: Implement the retry beat task

**Files:**
- Create: `backend/apps/loans/tasks.py`

- [ ] **Step 1: Write the task module**

Create `backend/apps/loans/tasks.py`:

```python
"""Celery tasks for the loans app.

Currently hosts `retry_failed_dispatches`, the beat task that drains the
PipelineDispatchOutbox when Celery was down at submission time.
"""

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="apps.loans.tasks.retry_failed_dispatches")
def retry_failed_dispatches():
    """Drain the PipelineDispatchOutbox with bounded retries."""
    from apps.agents.tasks import orchestrate_pipeline_task
    from apps.loans.models import LoanApplication, PipelineDispatchOutbox

    pending = PipelineDispatchOutbox.objects.filter(
        attempts__lt=PipelineDispatchOutbox.MAX_DISPATCH_ATTEMPTS
    ).order_by("created_at")

    drained = 0
    failed = 0
    for row in pending.iterator():
        try:
            orchestrate_pipeline_task.delay(str(row.application_id))
            with transaction.atomic():
                LoanApplication.objects.filter(pk=row.application_id).update(
                    status=LoanApplication.Status.PENDING
                )
                row.delete()
            drained += 1
            logger.info("Drained outbox row for application %s", row.application_id)
        except Exception as exc:
            row.attempts = row.attempts + 1
            row.last_error = str(exc)[:1000]
            row.last_attempt_at = timezone.now()
            row.save(update_fields=["attempts", "last_error", "last_attempt_at"])
            failed += 1
            logger.error(
                "Outbox retry failed for %s (attempts=%d): %s",
                row.application_id,
                row.attempts,
                exc,
            )

    return {"drained": drained, "failed": failed}
```

- [ ] **Step 2: Register the beat schedule entry**

In `backend/config/celery.py`, find the `app.conf.beat_schedule = {` block (around line 78) and add an entry:

```python
    "retry-failed-dispatches": {
        "task": "apps.loans.tasks.retry_failed_dispatches",
        "schedule": 60.0,  # every 60 seconds
    },
```

### Task 4.6: Register the outbox in Django admin

**Files:**
- Modify: `backend/apps/loans/admin.py`

- [ ] **Step 1: Add the registration**

Append to `backend/apps/loans/admin.py`:

```python
from apps.loans.models import PipelineDispatchOutbox


@admin.register(PipelineDispatchOutbox)
class PipelineDispatchOutboxAdmin(admin.ModelAdmin):
    list_display = ("application", "attempts", "last_attempt_at", "created_at")
    list_filter = ("attempts",)
    readonly_fields = ("id", "application", "created_at", "last_attempt_at", "last_error")
    ordering = ("created_at",)
```

(Ensure `admin` is already imported; if not, add `from django.contrib import admin`.)

### Task 4.7: Run the outbox tests

- [ ] **Step 1: Run tests**

```bash
cd backend && pytest tests/test_submission_outbox.py -v
```

Expected: all five tests PASS.

- [ ] **Step 2: Run the full loans test suite for regressions**

```bash
cd backend && pytest tests/ -k "loan or submission or outbox" -v
```

Expected: no regressions.

### Task 4.8: Update RUNBOOK and CHANGELOG, commit PR 4

**Files:**
- Modify: `backend/docs/RUNBOOK.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add a RUNBOOK entry for the new status**

Append to the relevant section of `backend/docs/RUNBOOK.md`:

```markdown
### Loan status: `queue_failed`

A loan with `status=queue_failed` means submission succeeded but the initial
Celery dispatch failed (e.g. Redis was temporarily unreachable). A beat task
`apps.loans.tasks.retry_failed_dispatches` retries up to 5 times at 60-second
intervals. Rows exhausted past 5 attempts remain in the
`PipelineDispatchOutbox` admin view for operator intervention.

**Manual recovery:** In Django admin, delete the outbox row and set the loan
status back to `pending`. A worker will pick it up on the next beat pass or
via the dashboard's batch-orchestrate action.
```

- [ ] **Step 2: Append to the v1.9.3 CHANGELOG section**

Under the `Reliability` subsection (from PR 3), add:

```markdown
- Loan submission is now durable. Dispatch to Celery happens under `transaction.on_commit()`; if the broker is unreachable, the submission is persisted in a new `PipelineDispatchOutbox` table and the loan is flagged `queue_failed`. A beat task `retry_failed_dispatches` drains the outbox every 60 seconds with up to 5 attempts. Addresses Codex adversarial review finding #4.
```

- [ ] **Step 3: Commit PR 4**

```bash
git checkout master && git pull
git checkout -b fix/submission-outbox
git add backend/apps/loans/models.py \
  backend/apps/loans/migrations/ \
  backend/apps/loans/views.py \
  backend/apps/loans/tasks.py \
  backend/apps/loans/admin.py \
  backend/config/celery.py \
  backend/tests/test_submission_outbox.py \
  backend/docs/RUNBOOK.md CHANGELOG.md
git commit -m "fix(loans): durable submission via on_commit + dispatch outbox

perform_create now dispatches orchestrate_pipeline_task under
transaction.on_commit. If the broker is unreachable, the failure is
persisted in a new PipelineDispatchOutbox row and the loan transitions to
a QUEUE_FAILED status. A beat task retry_failed_dispatches drains the
outbox every 60s with a 5-attempt cap.

Addresses Codex adversarial review finding #4 (2026-04-18).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Final verification

After all four PRs are merged:

- [ ] **Step 1: Run the full backend test suite on master**

```bash
cd backend && pytest tests/ -q
```

Expected: all tests pass, no regressions.

- [ ] **Step 2: Run the frontend test suite**

```bash
cd frontend && npm test -- --run && npm run typecheck && npm run lint
```

Expected: no failures or new lints.

- [ ] **Step 3: Smoke test the metrics gate manually**

In a running local stack:
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/metrics
# Expected: 403

curl -s -o /dev/null -w "%{http_code}\n" -H "X-Health-Token: $HEALTH_CHECK_TOKEN" http://localhost:8000/metrics
# Expected: 200
```

- [ ] **Step 4: Smoke test idempotent orchestration**

In the browser, submit a loan, wait for the pipeline to complete, then click the orchestrate button twice. Confirm only ONE new `AgentRun` row appears in the database.

- [ ] **Step 5: Smoke test the outbox**

Stop Redis (`docker compose stop redis`), submit a loan via the UI, confirm:
- UI shows 201 success
- DB: loan status = `queue_failed`, outbox row exists with `attempts=0`

Start Redis, wait up to 60s, confirm:
- Outbox row is gone
- Loan status reverted to `pending`
- AgentRun created

---

## Self-review notes

**Spec coverage check:**
- ✅ Finding 1 (CSRF): Tasks 1.1–1.3
- ✅ Finding 2 (ops endpoints): Tasks 2.1–2.6
- ✅ Finding 3 (force guard): Tasks 3.1–3.6
- ✅ Finding 4 (outbox): Tasks 4.1–4.8
- ✅ CHANGELOG entries in every PR
- ✅ RUNBOOK updates in PRs 2 and 4
- ✅ Cross-cutting smoke tests in the final verification section

**Type/signature consistency:**
- `PipelineDispatchOutbox.MAX_DISPATCH_ATTEMPTS` (class attr) used consistently in model, task, and tests.
- `agentsApi.orchestrate(loanId)` and `agentsApi.forceRerun(loanId, reason)` match between `api.ts` and the consuming hooks.
- `LoanApplication.Status.QUEUE_FAILED` referenced identically in model, views, tasks, and tests.
- Backend test fixtures use `force_authenticate(user=...)` consistently.

**Placeholder check:** None — every code block is concrete.
