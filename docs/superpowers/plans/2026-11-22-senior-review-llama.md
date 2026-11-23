# Senior review, security hardening, local Llama, README: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the review findings, run the app's AI on local Llama through Ollama, and ship a short, honest README.

**Architecture:** Small, test-first changes inside the existing service layer. One new
service module (`accounts/services/data_export.py`) and one new factory
(`email_engine/services/content_llm.py`); everything else edits existing files.

**Tech Stack:** Django 5 + DRF, Celery, Ollama (OpenAI-compatible `/v1`), Next.js 16, vitest.

**Spec:** `docs/superpowers/specs/2026-11-22-senior-review-llama-design.md`

## Global Constraints

- Work only in `C:/Users/Admin/loan-ai-review` (branch `review/senior-2026-11-22`). Never touch the main checkout's uncommitted files.
- No apology words ("apologise", "sorry", "disappointment") in any email prompt or template.
- Emails stay template-only by default; Ollama writes bias verdicts, never emails.
- Never use `llama3.2:3b` for bias verdicts.
- Do not push to master; open a pull request; no merge without the owner.
- Backend tests run in the backend container against a copy of the worktree's `backend/` (`/tmp/rv`), one run at a time.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Test command (used by every backend task)

```bash
# sync the worktree backend into the container, then run the given tests
cd C:/Users/Admin/loan-approval-ai-system
docker compose exec -T backend rm -rf /tmp/rv
docker compose cp C:/Users/Admin/loan-ai-review/backend backend:/tmp/rv
docker compose exec -T backend bash -lc "cd /tmp/rv && python -m pytest <paths> -p no:cacheprovider -q"
```

`pytest` and `pytest-django` are installed once with `pip install -q --user pytest pytest-django` (lost on container recreate).

---

### Task 1: Refresh endpoint hardening (A1)

**Files:**
- Modify: `backend/apps/accounts/views.py` (`CookieTokenRefreshView`)
- Test: `backend/tests/test_review_2026_11_security.py` (create)

- [ ] **Step 1: Failing tests**

```python
import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from apps.accounts.models import CustomUser

REFRESH_URL = "/api/v1/auth/refresh/"

@pytest.mark.django_db
def test_refresh_rejects_form_encoded_body():
    user = CustomUser.objects.create_user(username="rf1", password="x" * 14, role="customer")
    token = str(RefreshToken.for_user(user))
    resp = APIClient().post(REFRESH_URL, {"refresh": token}, format="multipart")
    assert resp.status_code == 415

@pytest.mark.django_db
def test_refresh_rejects_inactive_user():
    user = CustomUser.objects.create_user(username="rf2", password="x" * 14, role="customer")
    token = str(RefreshToken.for_user(user))
    user.is_active = False
    user.save(update_fields=["is_active"])
    resp = APIClient().post(REFRESH_URL, {"refresh": token}, format="json")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run, expect FAIL** (form body accepted; inactive user refreshed).
- [ ] **Step 3: Implement**

```python
from rest_framework.parsers import JSONParser

class CookieTokenRefreshView(generics.GenericAPIView):
    ...
    # JSON only: a cross-site HTML form cannot send application/json, so it
    # cannot plant an attacker's refresh token in the victim's browser.
    parser_classes = (JSONParser,)

    def _get_user_from_token(self, token):
        try:
            user = CustomUser.objects.get(pk=token["user_id"])
        except CustomUser.DoesNotExist as exc:
            raise TokenError("user no longer exists") from exc
        if not user.is_active:
            raise TokenError("user is inactive")
        return user
```

In `post`, call `self._get_user_from_token(refresh)` before minting the new access token, for both rotation modes.

- [ ] **Step 4: Run, expect PASS**, plus `tests/test_auth.py`.
- [ ] **Step 5: Commit** `fix(auth): JSON-only refresh and reject inactive users`

### Task 2: APP 12 export through a service with customer-safe content (A2)

**Files:**
- Create: `backend/apps/accounts/services/data_export.py`
- Modify: `backend/apps/accounts/views.py` (`CustomerDataExportView.get` calls the service)
- Test: `backend/tests/test_review_2026_11_security.py`

- [ ] **Step 1: Failing test**: an application with one sent and one unsent
  `GeneratedEmail`, one unsent `MarketingEmail`, and an `AgentRun` with a step
  carrying `result_summary` and a `BiasReport`. Assert the export contains only the
  sent email, no unsent marketing email, steps without `result_summary`, and no
  `bias_reports` key.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** `build_customer_export(user) -> dict` by moving the
  existing view body into the service, with these changes:
  - emails Prefetch filters `sent_at__isnull=False`;
  - marketing emails Prefetch filters `sent=True`;
  - each run is serialised as `{"status", "created_at", "steps"}` where steps use
    `_CUSTOMER_STEP_KEYS` from `apps.agents.serializers`;
  - no bias reports.
  The view keeps the throttle, the audit event, and returns `Response(build_customer_export(user))`.
- [ ] **Step 4: Run PASS** plus existing export tests (`grep -rl data-export backend/tests`).
- [ ] **Step 5: Commit** `fix(privacy): APP 12 export only returns what the customer was sent`

### Task 3: Abuse limits: loan creation, open-application cap, email uniqueness, throttle scopes, page clamp (A3, A4, A5, A7)

**Files:**
- Modify: `backend/apps/loans/views.py` (throttle for `create`; cap check in `perform_create`)
- Modify: `backend/config/settings/base.py` (`MAX_OPEN_APPLICATIONS_PER_CUSTOMER = 5`)
- Modify: `backend/apps/accounts/serializers.py` (`UserSerializer.validate_email`)
- Modify: `backend/apps/agents/views.py`, `backend/apps/email_engine/views.py` (throttle `scope`, `page = max(page, 1)`)
- Test: `backend/tests/test_review_2026_11_security.py`

- [ ] **Step 1: Failing tests**
  - customer with 5 open (`pending`/`processing`/`review`/`queue_failed`) applications gets 400 on the 6th `POST /api/v1/loans/`;
  - `PATCH /api/v1/auth/me/` with another user's email (different case) returns 400;
  - `OrchestrationThrottle.scope == "orchestration"`, `EmailGenerationThrottle.scope == "email_generation"`;
  - `GET /api/v1/agents/runs/?page=0` and `/api/v1/emails/?page=-3` return 200.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**

```python
# loans/views.py
class LoanCreateThrottle(UserRateThrottle):
    scope = "loan_create"
    rate = "10/hour"

OPEN_STATUSES = ("pending", "processing", "review", "queue_failed")

def get_throttles(self):  # on LoanApplicationViewSet
    if self.action == "create":
        return [*super().get_throttles(), LoanCreateThrottle()]
    return super().get_throttles()

# at the top of perform_create, customers only:
if user.role == "customer":
    cap = getattr(django_settings, "MAX_OPEN_APPLICATIONS_PER_CUSTOMER", 5)
    open_count = LoanApplication.objects.filter(
        applicant=user, status__in=OPEN_STATUSES, deleted_at__isnull=True
    ).count()
    if open_count >= cap:
        raise ValidationError({"detail": f"You already have {open_count} applications in progress. Wait for a decision before applying again."})
```

```python
# accounts/serializers.py, UserSerializer
def validate_email(self, value):
    if value and CustomUser.objects.filter(email__iexact=value).exclude(pk=getattr(self.instance, "pk", None)).exists():
        raise serializers.ValidationError("An account with this email already exists.")
    return value
```

Throttles: add `scope = "orchestration"` / `scope = "email_generation"`. Pagination: `page = max(page, 1)` after parsing in both list views.
- [ ] **Step 4: Run PASS** plus `apps/loans/tests`, `tests/test_auth.py`, `tests/test_api*.py`.
- [ ] **Step 5: Commit** `fix(api): cap open applications, scope throttles, unique email on profile edit, clamp page`

### Task 4: Bias verdict robustness (A6, B1, B2, B4, B5)

**Files:**
- Modify: `backend/apps/agents/services/bias/helpers.py`
- Modify: `backend/apps/agents/services/bias/core.py`, `bias/marketing.py`
- Modify: `backend/apps/agents/services/next_best_offer.py` (drop its `_extract_tool_result` copy; re-raise soft limit)
- Modify: `backend/apps/email_engine/tasks.py` (`_EMAIL_TIME_LIMIT = 330`, soft 300)
- Modify: `backend/config/settings/base.py` (`BIAS_LLM_TIMEOUT = _env_int("BIAS_LLM_TIMEOUT", 240)`)
- Test: `backend/tests/test_review_2026_11_reliability.py` (create)

- [ ] **Step 1: Failing tests**

```python
from celery.exceptions import SoftTimeLimitExceeded
from apps.agents.services.bias.helpers import _call_with_fallback, coerce_llm_score

def test_coerce_llm_score():
    assert coerce_llm_score(-5, 50) == 0
    assert coerce_llm_score(250, 50) == 100
    assert coerce_llm_score("42", 50) == 42
    assert coerce_llm_score("n/a", 50) == 50
    assert coerce_llm_score(None, 50) == 50

def test_soft_time_limit_propagates(monkeypatch):
    def boom(*a, **k):
        raise SoftTimeLimitExceeded()
    monkeypatch.setattr("apps.agents.services.bias.helpers.guarded_api_call", boom)
    with pytest.raises(SoftTimeLimitExceeded):
        _call_with_fallback(object(), {"score": 1}, "svc", "x")

def test_backend_error_returns_fallback_without_critical(monkeypatch, caplog):
    from apps.email_engine.services.exceptions import EmailBackendError
    def boom(*a, **k):
        raise EmailBackendError("ollama down")
    monkeypatch.setattr("apps.agents.services.bias.helpers.guarded_api_call", boom)
    assert _call_with_fallback(object(), {"score": 1}, "svc", "x") == {"score": 1}
    assert not [r for r in caplog.records if r.levelname == "CRITICAL"]

def test_bias_timeout_fits_inside_email_task(settings):
    from apps.email_engine import tasks
    assert settings.BIAS_LLM_TIMEOUT < 300 == tasks.generate_email_task.soft_time_limit
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**

```python
# helpers.py
from celery.exceptions import SoftTimeLimitExceeded
from apps.email_engine.services.exceptions import EmailBackendError, RateLimited

def coerce_llm_score(value, fallback):
    """A local model ignores the tool schema, so its score may be any type or range."""
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return fallback

# _call_with_fallback
    except ApiGateClosed:
        raise
    except SoftTimeLimitExceeded:
        raise  # the task's time limit must stop the task, not become a fallback
    except (anthropic.APIError, EmailBackendError, RateLimited) as e:
        logger.error(...); return fallback
    except Exception as e: ... (unchanged)

# _make_bias_llm_client: timeout=httpx.Timeout(float(django_settings.BIAS_LLM_TIMEOUT), connect=10.0)
```

`core.py:185` and `marketing.py:170`: `llm_raw_score = coerce_llm_score(result.get("score"), det_score)`.
Remove the unused `self._format_prescreen_results(prescreen)` call in `core.py:124` only if nothing reads it (it returns a string that is discarded).
NBO: `from .bias.helpers import _extract_tool_result`; add `except SoftTimeLimitExceeded: raise` before each `except Exception`.
- [ ] **Step 4: Run PASS** plus `apps/agents/tests`, `tests/test_bias*.py`, `tests/test_next_best_offer*.py`.
- [ ] **Step 5: Commit** `fix(bias): validate local LLM scores, keep task time limits, bound the Ollama timeout`

### Task 5: One switch for customer-facing LLM copy (B3)

**Files:**
- Create: `backend/apps/email_engine/services/content_llm.py`
- Modify: `backend/apps/agents/services/next_best_offer.py`, `backend/apps/agents/services/marketing_agent.py`
- Test: `backend/tests/test_review_2026_11_reliability.py`

- [ ] **Step 1: Failing tests**

```python
def test_template_backend_gives_no_content_client(monkeypatch):
    monkeypatch.setenv("EMAIL_LLM_BACKEND", "template")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    from apps.email_engine.services.content_llm import make_content_llm_client
    assert make_content_llm_client() == (None, "")

def test_nbo_and_marketing_follow_email_backend(monkeypatch):
    monkeypatch.setenv("EMAIL_LLM_BACKEND", "template")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    from apps.agents.services.next_best_offer import NextBestOfferGenerator
    from apps.agents.services.marketing_agent import MarketingAgent
    assert NextBestOfferGenerator().client is None
    assert MarketingAgent().client is None
```

- [ ] **Step 2: Run, expect FAIL** (both hard-code Anthropic).
- [ ] **Step 3: Implement**

```python
# content_llm.py
"""Client for customer-facing copy that an LLM may word (offer reasoning,
marketing follow-up). It follows EMAIL_LLM_BACKEND, so one switch governs every
LLM-written customer text: ``template`` means none is written by a model."""
import os

def email_backend():
    return (os.environ.get("EMAIL_LLM_BACKEND", "template") or "template").lower()

def make_content_llm_client():
    """Return ``(client_or_None, model)`` for the configured email backend."""
    from .email_generator import EmailGenerator
    client, _provider, model = EmailGenerator._build_client(email_backend(), os.environ.get("EMAIL_LLM_MODEL", ""))
    return client, model
```

NBO and MarketingAgent: `self.client, self.model = make_content_llm_client()`, pass `model=self.model`
instead of `"claude-sonnet-4-6"`. NBO's typed-error tuple and MarketingAgent's
transient arm add `EmailBackendError, RateLimited` (template fallback). NBO's two
calls skip straight to their deterministic fallbacks when `self.client is None`
(no CRITICAL log for an intentional template run).
- [ ] **Step 4: Run PASS** plus `apps/agents/tests`, `tests/test_marketing*.py`, `tests/test_next_best_offer*.py`.
- [ ] **Step 5: Commit** `refactor(llm): offers and marketing copy follow EMAIL_LLM_BACKEND`

### Task 6: Local Llama defaults (C)

**Files:**
- Modify: `backend/config/settings/base.py` (`EMAIL_LLM_BACKEND` default `template`, `BIAS_LLM_BACKEND` default `ollama`, `BIAS_OLLAMA_MODEL` default `llama3.1:8b`)
- Modify: `backend/apps/email_engine/services/email_generator.py` (`EmailGenerator.__init__` uses `content_llm.email_backend()`)
- Modify: `.env.example`, `docker-compose.yml` (`ollama` image pinned to `ollama/ollama:0.30.7`; `ollama-init` pulls `${BIAS_OLLAMA_MODEL:-llama3.1:8b}`; memory comment), `ollama/Modelfile` (`FROM llama3.1:8b`)
- Modify: `backend/config/env_validation.py` (Anthropic key warning only when a backend is `anthropic`; reviewer-model warning only when `BIAS_LLM_BACKEND=anthropic`)
- Test: `backend/tests/test_review_2026_11_reliability.py`; fix any existing test that relied on the old `anthropic` default by setting `EMAIL_LLM_BACKEND`/`BIAS_LLM_BACKEND` explicitly.

- [ ] **Step 1: Failing test**: with `EMAIL_LLM_BACKEND` and `BIAS_LLM_BACKEND` unset, a reloaded settings module yields `template`, `ollama`, `llama3.1:8b`; `EmailGenerator().provider == "template"`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** the defaults and file edits above. Model choice depends on the live comparison (spec decision 4); if llama3.1:8b loses, keep `qwen2.5:7b` and say so in the PR.
- [ ] **Step 4: Run PASS**, then the full backend suite.
- [ ] **Step 5: Commit** `feat(ai): run the AI locally on Llama 3.1 8B by default; Claude is opt-in`

### Task 7: Smaller hardening (A8, A9, A10, B5)

**Files:**
- Modify: `backend/config/middleware.py` (request ID validation), `backend/config/logging_filters.py` (exception args and `exc_text`), `backend/entrypoint.sh` (`validate_password`; skip creation with a clear message when weak), `backend/.dockerignore` and `frontend/.dockerignore` (`.env`, `.env.*`, `!.env.example`), `backend/apps/ml_engine/apps.py` (log the signals import failure), `backend/apps/agents/services/api_budget.py` (docstring says `BudgetExhausted`)
- Test: `backend/tests/test_review_2026_11_security.py`

- [ ] **Step 1: Failing tests**: a request with `X-Request-ID: <script>` + 200 chars gets a fresh 32-hex ID back; a valid `abc-123` is echoed; `PiiMaskingFilter` redacts `ValueError("mail a@b.com")` passed as an arg; a record with `exc_info` gets a redacted `exc_text`.
- [ ] **Step 2: Run FAIL. Step 3: Implement**

```python
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
incoming = request.META.get("HTTP_X_REQUEST_ID", "")
cid = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
```

```python
def _redact_arg(a):
    if isinstance(a, str):
        return redact_pii(a)
    if isinstance(a, BaseException):
        return redact_pii(str(a))
    return a
...
if record.exc_info and not record.exc_text:
    record.exc_text = redact_pii(logging.Formatter().formatException(record.exc_info))
```
- [ ] **Step 4: PASS** plus `tests/test_logging*.py`, `tests/test_middleware*.py`. **Step 5: Commit** `fix(security): validate request IDs, redact exceptions in logs, ignore .env in images`

### Task 8: CI smoke test (B6)

**Files:** `docker-compose.yml` (beat `--schedule /tmp/celerybeat-schedule`), `.github/workflows/smoke-e2e.yml` (failure step: `docker compose ps -a`, `docker compose logs --tail 200`, beat health JSON)

- [ ] Recreate `celery_beat` locally in the main stack only after the PR merges; here verify with `docker compose config` that the command renders. Commit `fix(ci): celery beat writes its schedule to /tmp so smoke-e2e can start it`.

### Task 9: Frontend (A11, A12, A13, B7, B8)

**Files:** `frontend/package-lock.json`, `frontend/src/components/emails/EmailPreview.tsx`, `frontend/next.config.js`, `frontend/src/hooks/useMetrics.ts`, `frontend/src/lib/api.ts`; tests under `frontend/src/__tests__/`.

- [ ] **Step 1: Failing tests** (vitest):
  - `sanitizeEmailHtml('<div style="position:fixed;z-index:9;color:red">x</div>')` keeps `color` and drops `position` and `z-index` (export the function);
  - the axios response interceptor does not retry a POST on 503 but retries a GET (check `_retryCount`);
  - `isTerminalTaskStatus('REVOKED')` is true; `shouldStopPolling(startedAt)` is true after 15 minutes.
- [ ] **Step 2: Run FAIL. Step 3: Implement**
  - DOMPurify `uponSanitizeAttribute` hook scoped to the call: strip `position`, `z-index`, `inset`, `top`, `left`, `right`, `bottom` declarations from `style`.
  - `api.ts`: retry 429/503 only when the method is `get`, `head` or `options`.
  - `useMetrics.ts`: terminal set `{SUCCESS, FAILURE, REVOKED}`; stop and set `failure` after 15 minutes from the job start; `REVOKED` sets `failure`.
  - `next.config.js`: add `Strict-Transport-Security: max-age=31536000; includeSubDomains` when `NODE_ENV === 'production'`.
  - `npm update next follow-redirects source-map-js vite undici dompurify` (in-range only), then `npm audit --omit=dev` shows no critical or high except zod.
- [ ] **Step 4:** `npx vitest run`, `npx tsc --noEmit`, `npm run lint`, `npm run build` all pass.
- [ ] **Step 5: Commit** `fix(frontend): patch Next.js RCE advisory, safer email preview, HSTS, bounded polling, no POST retries`

### Task 10: README (D)

**Files:** `README.md`

- [ ] Rewrite: one-paragraph summary; "What it does" (3 bullets); one diagram; "Run it" ($0: template emails, local Llama verdicts; `COMPOSE_PROFILES=ollama`; Claude optional); "How I built this"; "Tech"; collapsed details (pipeline, guardrails, ML, security, testing, limits). Keep the ADR table link, drop duplicated detail.
- [ ] Verify every command, path and number against the tree (`grep`, `ls`, test counts from the suite run).
- [ ] Commit `docs(readme): shorter README, local Llama setup, how it was built`

### Task 11: Verification and pull request

- [ ] Full backend suite in the container (ignore the two hypothesis files), ruff on the host, frontend checks.
- [ ] Live: bias comparison results recorded in the PR.
- [ ] Push `review/senior-2026-11-22`, open a PR into master that states it contains #289, wait for `gh pr checks`, report. No merge.
