# Full-Codebase Review & Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Perform a full-sweep review across all six layers of the codebase, triage every finding by severity, and apply fixes in CRITICAL → HIGH → MEDIUM → LOW order with one atomic commit per fix cluster.

**Architecture:** Phase 1 fans out six parallel review agents (one per layer), each writing structured findings to `.tmp/review/<layer>.md`. Phase 2 triages all findings into a single ranked list. Phase 3 applies fixes layer-by-layer within each severity tier using the triage list as the work queue.

**Tech Stack:** Django 4.x + DRF, Next.js 16 + TypeScript, Celery + Redis, scikit-learn + XGBoost, Anthropic Claude API, PostgreSQL, Docker Compose, pytest, vitest, Playwright

---

## Review Lenses (apply to every task)

| Lens | What to check |
|---|---|
| **Correctness** | Logic bugs, wrong assumptions, off-by-one, bad defaults, race conditions, missing null guards |
| **Security** | Auth bypass, injection (SQL/command/prompt), secrets in code, unvalidated input at boundaries, OWASP Top 10 |
| **Efficiency** | N+1 queries, unnecessary API calls, missing `select_related`/`prefetch_related`, redundant DB round-trips |
| **Tests** | Missing coverage on critical paths, tests that can never fail, fixture rot, missing edge-case assertions |
| **Operability** | Silent failures, unlogged exceptions, missing error handling at system boundaries, unhandled task failure modes |

## Finding Format

Every finding written to `.tmp/review/<layer>.md` must use this format:

```
## SEVERITY: <CRITICAL|HIGH|MEDIUM|LOW>
**File:** `path/to/file.py:line`
**Lens:** <lens name>
**Issue:** One sentence describing the problem.
**Fix:** Concrete description of what to change, including the specific code pattern to fix.
```

---

## Phase 1 — Parallel Analysis (Tasks 1–6)

Run Tasks 1–6 concurrently. Each writes findings to `.tmp/review/`.

---

### Task 1: Backend Core Review (accounts + loans + config)

**Files to review:**
- `backend/apps/accounts/models.py`
- `backend/apps/accounts/views.py`
- `backend/apps/accounts/views_2fa.py`
- `backend/apps/accounts/serializers.py`
- `backend/apps/accounts/authentication.py`
- `backend/apps/accounts/permissions.py`
- `backend/apps/accounts/signals.py`
- `backend/apps/accounts/fields.py`
- `backend/apps/accounts/utils/encryption.py`
- `backend/apps/accounts/services/address_service.py`
- `backend/apps/accounts/services/kyc_service.py`
- `backend/apps/accounts/management/commands/data_retention_cleanup.py`
- `backend/apps/accounts/management/commands/rotate_encryption_key.py`
- `backend/apps/loans/models.py`
- `backend/apps/loans/views.py`
- `backend/apps/loans/serializers.py`
- `backend/apps/loans/permissions.py`
- `backend/apps/loans/filters.py`
- `backend/apps/loans/tasks.py`
- `backend/apps/loans/services/decision_review.py`
- `backend/apps/loans/services/fraud_detection.py`
- `backend/apps/loans/services/overturn_policy.py`
- `backend/apps/loans/management/commands/enforce_retention.py`
- `backend/config/settings/base.py`
- `backend/config/settings/production.py`
- `backend/config/middleware.py`
- `backend/config/ops_auth.py`
- `backend/config/urls.py`
- `backend/config/env_validation.py`

**Specific patterns to look for:**

*Correctness:*
- `LoanApplication` status transitions — are there missing guards that allow invalid state jumps?
- `DecisionReview` overturn logic — does maker-checker enforce that reviewer ≠ submitter?
- Encryption field round-trips — do encrypted fields decrypt correctly after a migration rotate?
- `data_retention_cleanup` — does it handle `deleted_at IS NULL` correctly?

*Security:*
- Any `serializer.save()` that doesn't set `user` from `request.user` (mass assignment risk)
- Password reset / 2FA endpoints — are brute-force rate limits applied?
- `ops_auth.py` — does the ops header check use constant-time comparison?
- `enforce_retention` management command — is it safe to run in production without dry-run flag?
- Any `request.data` value passed directly to a queryset filter without validation

*Efficiency:*
- Loan list views — are `select_related('applicant')` / `prefetch_related('decisions')` present?
- Any view that loops over a queryset and makes per-item DB calls

*Tests:*
- `test_register_name_validation.py` — does it cover the L26 name guard on profile update?
- Is there a test for the lockout bypass edge case (`failed_login_attempts` reset)?
- Is the `rotate_encryption_key` command tested?

*Operability:*
- `signals.py` — are signal failures logged or silently swallowed?
- Are Celery task failures in `loans/tasks.py` logged with enough context to diagnose?

- [ ] **Step 1: Read all files listed above**

Read each file. Take notes on every violation of the five lenses.

- [ ] **Step 2: Write findings to `.tmp/review/backend-core.md`**

Use the Finding Format above for each issue found. Include the file:line and a concrete fix description.

- [ ] **Step 3: Confirm file written**

```bash
cat .tmp/review/backend-core.md | head -50
```
Expected: findings in the structured format above.

---

### Task 2: ML Engine Review

**Files to review:**
- `backend/apps/ml_engine/services/predictor.py`
- `backend/apps/ml_engine/services/trainer.py`
- `backend/apps/ml_engine/services/data_generator.py`
- `backend/apps/ml_engine/services/data_generator_phases.py`
- `backend/apps/ml_engine/services/feature_prep.py`
- `backend/apps/ml_engine/services/feature_engineering.py`
- `backend/apps/ml_engine/services/feature_generator.py`
- `backend/apps/ml_engine/services/feature_selection.py`
- `backend/apps/ml_engine/services/prediction_features.py`
- `backend/apps/ml_engine/services/decision_assembly.py`
- `backend/apps/ml_engine/services/decision_explanation.py`
- `backend/apps/ml_engine/services/counterfactual_engine.py`
- `backend/apps/ml_engine/services/fairness_gate.py`
- `backend/apps/ml_engine/services/fairness_gate_mode.py`
- `backend/apps/ml_engine/services/promotion_gate_mode.py`
- `backend/apps/ml_engine/services/regression_gate.py`
- `backend/apps/ml_engine/services/calibration_validator.py`
- `backend/apps/ml_engine/services/drift_monitor.py`
- `backend/apps/ml_engine/services/shadow_scoring.py`
- `backend/apps/ml_engine/services/shap_attribution.py`
- `backend/apps/ml_engine/services/policy_overlay.py`
- `backend/apps/ml_engine/services/policy_recompute.py`
- `backend/apps/ml_engine/services/prediction_cache.py`
- `backend/apps/ml_engine/services/prediction_diagnostics.py`
- `backend/apps/ml_engine/services/underwriting_engine.py`
- `backend/apps/ml_engine/services/underwriting_helpers.py`
- `backend/apps/ml_engine/services/credit_policy.py`
- `backend/apps/ml_engine/services/mrm_dossier.py`
- `backend/apps/ml_engine/services/mrm_compliance.py`
- `backend/apps/ml_engine/services/model_card.py`
- `backend/apps/ml_engine/services/segmentation.py`
- `backend/apps/ml_engine/services/metrics.py`
- `backend/apps/ml_engine/services/adm_disclosure.py`
- `backend/apps/ml_engine/services/adverse_action.py`
- `backend/apps/ml_engine/tasks.py`
- `backend/apps/ml_engine/views.py`
- `backend/apps/ml_engine/models.py`

**Specific patterns to look for:**

*Correctness:*
- `data_generator.py` / `data_generator_phases.py` — any columns that leak post-outcome info into training features (e.g., `default_flag` derived from the label)?
- `predictor.py` — does it handle the case where no `ModelVersion.is_active=True` exists (raises, returns None, or silently uses stale model)?
- `feature_prep.py` — does the preprocessor fit on train only, or accidentally on the full dataset including test?
- `counterfactual_engine.py` — does it guard against infinite loops or convergence failure?
- `fairness_gate.py` — could a missing demographic group silently pass the gate?
- `policy_recompute.py` — are recomputed decisions written atomically?
- `regression_gate.py` — does it enforce the threshold correctly (strict `<` vs `<=`)?

*Security:*
- `mrm_dossier.py` — any file paths constructed from user-supplied input without sanitisation?
- `model_card.py` — any external URLs in model metadata that could enable SSRF?
- `views.py` — are all ML admin endpoints behind officer/admin role check?

*Efficiency:*
- `prediction_cache.py` — are cache keys collision-resistant (include model version + feature hash)?
- `shadow_scoring.py` — does it make redundant DB writes when shadow score matches primary?
- Any training task that loads the full dataset into memory when it could stream?

*Tests:*
- Is there a test verifying the `is_active` guard when no active model exists?
- Does `test_feature_prep.py` verify the scaler is NOT fit on test data?
- Is the `fairness_gate` tested with a group that has zero samples?

*Operability:*
- `trainer.py` — are training failures logged with the exception traceback?
- `drift_monitor.py` — if PSI computation fails for one feature, does it abort or skip and continue?

- [ ] **Step 1: Read all files listed above**

Read each file. Take notes on every violation of the five lenses.

- [ ] **Step 2: Write findings to `.tmp/review/ml-engine.md`**

Use the Finding Format above. Be especially thorough on data leakage — it is the highest-risk issue in this layer.

- [ ] **Step 3: Confirm file written**

```bash
cat .tmp/review/ml-engine.md | head -50
```

---

### Task 3: Email Engine Review

**Files to review:**
- `backend/apps/email_engine/services/email_generator.py`
- `backend/apps/email_engine/services/prompts.py`
- `backend/apps/email_engine/services/guardrails/engine.py`
- `backend/apps/email_engine/services/guardrails/patterns.py`
- `backend/apps/email_engine/services/html_renderer.py`
- `backend/apps/email_engine/services/template_fallback.py`
- `backend/apps/email_engine/services/sender.py`
- `backend/apps/email_engine/services/lifecycle.py`
- `backend/apps/email_engine/services/persistence.py`
- `backend/apps/email_engine/services/pricing.py`
- `backend/apps/email_engine/services/documentation.py`
- `backend/apps/email_engine/services/exceptions.py`
- `backend/apps/email_engine/tasks.py`
- `backend/apps/email_engine/views.py`
- `backend/apps/email_engine/models.py`

**Specific patterns to look for:**

*Correctness:*
- `email_generator.py` — does it handle Claude API timeout / rate-limit errors and fall back to template correctly?
- `guardrails/engine.py` — could a pattern match on the wrong field (e.g., matching subject when checking body)?
- `sender.py` — does it correctly set `sent_at` only on first delivery (not on redelivery / retry)?
- `lifecycle.py` — is `GeneratedEmail` status updated atomically, or could a crash leave it half-sent?
- `template_fallback.py` — does it produce compliant denial email content with no apology language?
- `persistence.py` — are emails correctly linked to their `LoanApplication` and `AgentRun`?

*Security:*
- `prompts.py` — is user-supplied data (loan purpose, applicant name) escaped before injection into Claude prompts to prevent prompt injection?
- `html_renderer.py` — are all user-supplied values HTML-escaped before insertion into email templates?
- `sender.py` — are SMTP credentials read from environment only, never from DB or request data?
- `views.py` — can a customer trigger email regeneration for another customer's application?

*Efficiency:*
- `pricing.py` — does it make a DB call per token count, or batch?
- Any email task that fetches the full application + decisions when it only needs a subset of fields?

*Tests:*
- `test_email_task_reliability.py` — does it test the double-send guard (calling deliver twice should not send twice)?
- Is there a test verifying template fallback when `EMAIL_USE_CLAUDE_API=False`?
- Is there a test verifying apology language is absent from denial templates?

*Operability:*
- `tasks.py` — are Claude API failures caught and logged with correlation IDs?
- Are guardrail violations logged at WARN level with the matched pattern?

- [ ] **Step 1: Read all files listed above**

Read each file. Take notes on every violation of the five lenses.

- [ ] **Step 2: Write findings to `.tmp/review/email-engine.md`**

Use the Finding Format above. Prompt injection is the priority security lens for this layer.

- [ ] **Step 3: Confirm file written**

```bash
cat .tmp/review/email-engine.md | head -50
```

---

### Task 4: Agents Review

**Files to review:**
- `backend/apps/agents/services/orchestrator.py`
- `backend/apps/agents/services/bias_detector.py`
- `backend/apps/agents/services/bias/core.py`
- `backend/apps/agents/services/bias/helpers.py`
- `backend/apps/agents/services/bias/marketing.py`
- `backend/apps/agents/services/bias/reviewer.py`
- `backend/apps/agents/services/bias/thresholds.py`
- `backend/apps/agents/services/bias/tools.py`
- `backend/apps/agents/services/next_best_offer.py`
- `backend/apps/agents/services/email_pipeline.py`
- `backend/apps/agents/services/marketing_agent.py`
- `backend/apps/agents/services/marketing_pipeline.py`
- `backend/apps/agents/services/human_review_handler.py`
- `backend/apps/agents/services/context_builder.py`
- `backend/apps/agents/services/deterministic_prescreen.py`
- `backend/apps/agents/services/api_budget.py`
- `backend/apps/agents/services/recommendation_engine.py`
- `backend/apps/agents/services/step_tracker.py`
- `backend/apps/agents/tasks.py`
- `backend/apps/agents/views.py`
- `backend/apps/agents/models.py`
- `backend/apps/agents/utils.py`
- `backend/apps/agents/management/commands/watchdog.py`

**Specific patterns to look for:**

*Correctness:*
- `orchestrator.py` — are step results written to `AgentRun` atomically? Could a mid-orchestration crash leave the run in a non-recoverable state?
- `bias_detector.py` / `bias/core.py` — does the bias fail-safe correctly escalate to human review when the Claude API is unavailable (vs. silently passing)?
- `next_best_offer.py` — is the NBO repayment calculation correct for unsecured personal loans (term cap applied)?
- `human_review_handler.py` — is the human review queue restricted to bias flags only, not conditional approvals?
- `api_budget.py` — does the budget reserve release correctly when a task is cancelled or errors?
- `step_tracker.py` — are step timestamps monotonically consistent (UUID ordering)?

*Security:*
- `context_builder.py` — is PII from the customer profile sanitised before being injected into Claude prompts?
- `marketing_agent.py` — can a marketing email be sent to an unsubscribed customer?
- `views.py` — are agent run results scoped to the requesting user's loans only?

*Efficiency:*
- `orchestrator.py` — does it make redundant Claude API calls for steps that could use cached results?
- `bias_detector.py` — does it load the full loan application + profile when it only needs a demographic subset?

*Tests:*
- `test_bias_failsafe.py` — does it test the case where the Claude API call raises a network error?
- Is there a test for the NBO term cap on unsecured personal loans?
- Is there a test verifying human review is NOT triggered for conditional approvals?

*Operability:*
- `watchdog.py` — does it correctly handle DB connection loss without crashing the container?
- `tasks.py` — are all Celery retries logged with the attempt number and exception?

- [ ] **Step 1: Read all files listed above**

Read each file. Take notes on every violation of the five lenses.

- [ ] **Step 2: Write findings to `.tmp/review/agents.md`**

Use the Finding Format above.

- [ ] **Step 3: Confirm file written**

```bash
cat .tmp/review/agents.md | head -50
```

---

### Task 5: Frontend Review

**Files to review:**
- `frontend/src/lib/api.ts`
- `frontend/src/lib/auth.ts`
- `frontend/src/lib/emailHtmlRenderer.ts`
- `frontend/src/lib/utils.ts`
- `frontend/src/lib/customerLabels.ts`
- `frontend/src/types/index.ts`
- `frontend/src/middleware.ts`
- `frontend/src/hooks/useAuth.tsx`
- `frontend/src/hooks/useApplications.ts`
- `frontend/src/hooks/useApplicationForm.ts`
- `frontend/src/hooks/useAgentStatus.ts`
- `frontend/src/hooks/usePipelineOrchestration.ts`
- `frontend/src/hooks/useDecisionReview.ts`
- `frontend/src/hooks/useHumanReview.ts`
- `frontend/src/hooks/useDashboardStats.ts`
- `frontend/src/hooks/useMetrics.ts`
- `frontend/src/hooks/useModelCard.ts`
- `frontend/src/hooks/useDriftReports.ts`
- `frontend/src/components/applications/ApplicationForm.tsx`
- `frontend/src/components/applications/ApplicationDetail.tsx`
- `frontend/src/components/applications/DecisionSection.tsx`
- `frontend/src/components/applications/PipelineControls.tsx`
- `frontend/src/components/applications/RepaymentCalculator.tsx`
- `frontend/src/components/applications/DenialExplanationPanel.tsx`
- `frontend/src/components/applications/DecisionReviewStatus.tsx`
- `frontend/src/components/emails/EmailPreview.tsx`
- `frontend/src/components/layout/DashboardLayout.tsx`
- `frontend/src/components/layout/Sidebar.tsx`
- `frontend/src/app/(auth)/login/page.tsx`
- `frontend/src/app/(auth)/register/page.tsx`
- `frontend/src/app/dashboard/applications/[id]/page.tsx`
- `frontend/src/app/dashboard/human-review/page.tsx`
- `frontend/src/app/dashboard/audit/page.tsx`
- `frontend/src/app/providers.tsx`
- `frontend/src/app/global-error.tsx`
- `frontend/tsconfig.json`
- `frontend/next.config.js`

**Specific patterns to look for:**

*Correctness:*
- `api.ts` — are all API error responses handled (4xx and 5xx), or does it only catch network errors?
- `useAuth.tsx` — does token refresh handle an expired refresh token correctly?
- `useAgentStatus.ts` — does polling stop correctly when the component unmounts?
- `RepaymentCalculator.tsx` — guard against division by zero when `term` or `rate` is 0?
- `ApplicationForm.tsx` — are required fields validated before submission?
- `emailHtmlRenderer.ts` — is HTML sanitised to prevent XSS if email content contains user-supplied data?
- `middleware.ts` — does it correctly protect all authenticated routes including `/apply`?

*Security:*
- `api.ts` — are JWT tokens stored in `httpOnly` cookies, or in `localStorage`/`sessionStorage` (XSS risk)?
- `emailHtmlRenderer.ts` — is user-supplied content properly escaped or sanitised before any HTML rendering?
- Any component rendering raw HTML from the API without sanitisation?
- `next.config.js` — are CSP headers configured correctly?

*Efficiency:*
- Any `useEffect` with a missing or incorrect dependency array causing redundant API calls?
- `usePipelineOrchestration.ts` — does polling use exponential backoff, or fixed interval?
- Any React Query query fetching more data than the component displays?

*Tests:*
- `useAgentStatus.test.tsx` — does it test polling teardown on unmount?
- `RepaymentCalculator.test.tsx` — does it test the zero-input edge case?
- `useAuth.test.tsx` — does it test refresh token expiry?

*Operability:*
- `global-error.tsx` — does it provide enough context for debugging?
- Are loading and error states handled in every data-fetching component?
- Does `ApplicationDetail.tsx` handle null/unavailable agent run data?

- [ ] **Step 1: Read all files listed above**

Read each file. Take notes on every violation of the five lenses.

- [ ] **Step 2: Write findings to `.tmp/review/frontend.md`**

Use the Finding Format above. Prioritise the security lens — raw HTML rendering without sanitisation is a HIGH finding.

- [ ] **Step 3: Confirm file written**

```bash
cat .tmp/review/frontend.md | head -50
```

---

### Task 6: Infra Review

**Files to review:**
- `docker-compose.yml`
- `docker-compose.monitoring.yml`
- `backend/requirements.txt`
- `frontend/package.json`
- `backend/config/celery.py`
- `backend/config/settings/base.py`
- `backend/config/settings/production.py`
- `backend/config/env_validation.py`
- `.github/workflows/build.yml`
- `.github/workflows/test.yml`
- `.github/workflows/lint.yml`
- `.github/workflows/security.yml`
- `.github/workflows/smoke-e2e.yml`
- `frontend/Dockerfile`

**Specific patterns to look for:**

*Correctness:*
- `docker-compose.yml` — are all `depends_on` conditions using `condition: service_healthy` where needed?
- `celery.py` — are the `ml`, `email`, and `agents` queues configured with correct concurrency and prefetch limits?
- `env_validation.py` — does it validate all required secrets on startup (fast-fail if `DJANGO_SECRET_KEY` or `ANTHROPIC_API_KEY` is missing)?
- `production.py` — is `DEBUG=False` enforced? Is `ALLOWED_HOSTS` locked down?
- CI workflows — do test jobs run migrations before executing tests?

*Security:*
- `docker-compose.yml` — are any service ports bound to `0.0.0.0` that should be `127.0.0.1`?
- `requirements.txt` — any known CVE-affected packages not yet bumped?
- `package.json` — any `npm audit` HIGH/CRITICAL vulnerabilities outstanding?
- `production.py` — are `SECURE_HSTS_SECONDS`, `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE` all set?
- Any secrets hardcoded in workflow yml files?

*Efficiency:*
- `celery.py` — are task acknowledgements `acks_late=True` for long-running ML tasks?
- Are Celery workers configured with `max_tasks_per_child` to prevent memory leaks in ML workers?

*Tests:*
- CI `test.yml` — does it run both backend pytest AND frontend vitest?
- Does the `smoke-e2e.yml` workflow verify the health endpoint after deploy?
- Are there missing CI checks (e.g., no mypy/ruff gate in the main test job)?

*Operability:*
- `docker-compose.yml` — do all services have `restart: unless-stopped` or equivalent?
- Are log levels configurable via environment variable?
- Does the monitoring compose file correctly scrape all service metric endpoints?

- [ ] **Step 1: Read all files listed above**

Read each file. Take notes on every violation of the five lenses.

- [ ] **Step 2: Write findings to `.tmp/review/infra.md`**

Use the Finding Format above.

- [ ] **Step 3: Confirm file written**

```bash
cat .tmp/review/infra.md | head -50
```

---

## Phase 2 — Triage (Task 7)

### Task 7: Merge and Triage All Findings

**Files:**
- Read: `.tmp/review/backend-core.md`, `.tmp/review/ml-engine.md`, `.tmp/review/email-engine.md`, `.tmp/review/agents.md`, `.tmp/review/frontend.md`, `.tmp/review/infra.md`
- Create: `.tmp/review/triage.md`

- [ ] **Step 1: Read all six findings files**

Read each file in full.

- [ ] **Step 2: Write triage document**

Create `.tmp/review/triage.md` with findings grouped as follows:

```markdown
# Triage: Full-Codebase Review

## CRITICAL
(Data loss, security breach, or complete service failure)

| # | Layer | File:line | Lens | Summary | Fix |
|---|---|---|---|---|---|
| C1 | ... | ... | ... | ... | ... |

## HIGH
(Bugs or vulnerabilities causing incorrect behaviour in production)

| # | Layer | File:line | Lens | Summary | Fix |
|---|---|---|---|---|---|
| H1 | ... | ... | ... | ... | ... |

## MEDIUM
(Code quality issues reducing reliability or maintainability)

| # | Layer | File:line | Lens | Summary | Fix |
|---|---|---|---|---|---|
| M1 | ... | ... | ... | ... | ... |

## LOW
(Style, dead code, minor cleanup)

| # | Layer | File:line | Lens | Summary | Fix |
|---|---|---|---|---|---|
| L1 | ... | ... | ... | ... | ... |
```

Collapse duplicates. If the same issue appears in multiple layers, merge into one row. Assign sequential IDs (C1, C2, H1, H2, M1, etc.) for use in commit messages.

- [ ] **Step 3: Count findings per tier**

```bash
grep -c "^| C" .tmp/review/triage.md || echo "0 CRITICAL"
grep -c "^| H" .tmp/review/triage.md || echo "0 HIGH"
grep -c "^| M" .tmp/review/triage.md || echo "0 MEDIUM"
grep -c "^| L" .tmp/review/triage.md || echo "0 LOW"
```

- [ ] **Step 4: Commit triage document**

```bash
git add .tmp/review/
git commit -m "chore(review): add parallel analysis findings and triage"
```

---

## Phase 3 — Layer-by-Layer Fixes (Tasks 8–13)

**Process for each fix task:**
1. Read `.tmp/review/triage.md`
2. Filter to the target severity + layer
3. For each finding: read the file at the given line (plus ±30 lines context), apply the minimal correct fix, run the relevant test(s)
4. Commit the cluster

**Commit message format:** `fix(<layer>): <what> — closes triage/<ID>`

---

### Task 8: Apply All CRITICAL Fixes (All Layers)

**Files:** Determined by the CRITICAL section of `.tmp/review/triage.md`.

- [ ] **Step 1: Read triage.md, extract all CRITICAL rows**

Work through each C-numbered finding in order.

- [ ] **Step 2: For each CRITICAL finding — read the target file at the reported line**

Read ±30 lines of context to understand the issue fully before touching anything.

- [ ] **Step 3: Apply the minimal correct fix**

Apply only what the finding describes. Do not refactor surrounding code. Do not add features.

Example fix patterns:

*Security bypass — add missing ownership check:*
```python
# Before
def my_view(request):
    obj = MyModel.objects.get(pk=request.data['id'])

# After
def my_view(request):
    obj = get_object_or_404(MyModel, pk=request.data['id'], user=request.user)
```

*Missing null guard crashing in production:*
```python
# Before
result = obj.related.value

# After
result = obj.related.value if obj.related_id else default_value
```

*Hardcoded secret:*
```python
# Before
API_KEY = "sk-ant-hardcoded..."

# After
API_KEY = os.environ["ANTHROPIC_API_KEY"]
```

- [ ] **Step 4: Run the relevant tests for each fix**

```bash
docker compose exec backend python -m pytest backend/apps/<app>/tests/ -x -q 2>&1 | tail -20
```

Expected: PASSED, no regressions introduced.

- [ ] **Step 5: Commit all CRITICAL fixes**

```bash
git add <changed files>
git commit -m "fix(security): address critical findings C1-CN from full-codebase review"
```

---

### Task 9: Apply HIGH Fixes — Backend Core

**Files:** Determined by the HIGH section of `.tmp/review/triage.md`, filtered to backend-core layer.

- [ ] **Step 1: Read triage.md HIGH section, filter to backend-core rows**

- [ ] **Step 2: For each finding — read the file at the reported line (±30 lines context)**

- [ ] **Step 3: Apply the minimal correct fix**

*N+1 query — add select_related:*
```python
# Before
applications = LoanApplication.objects.filter(user=user)
for app in applications:
    decision = app.loandecision_set.first()  # N extra queries

# After
applications = LoanApplication.objects.filter(
    user=user
).prefetch_related('loandecision_set')
```

*Missing error handling at system boundary:*
```python
# Before
result = external_service.call()

# After
try:
    result = external_service.call()
except ExternalServiceError as exc:
    logger.error("external_service failed: %s", exc, exc_info=True)
    raise ServiceUnavailableError("Service unavailable") from exc
```

*Unsafe queryset filter from user input:*
```python
# Before
qs = MyModel.objects.filter(**request.query_params)

# After
allowed = {'status': request.query_params.get('status')}
qs = MyModel.objects.filter(**{k: v for k, v in allowed.items() if v is not None})
```

- [ ] **Step 4: Run backend tests**

```bash
docker compose exec backend python -m pytest backend/apps/accounts/ backend/apps/loans/ -x -q 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add <changed files>
git commit -m "fix(accounts,loans): address high-severity findings from full-codebase review"
```

---

### Task 10: Apply HIGH Fixes — ML Engine + Email Engine + Agents

**Files:** Determined by the HIGH section of `.tmp/review/triage.md`, filtered to ml-engine, email-engine, agents layers.

- [ ] **Step 1: Read triage.md HIGH section, filter to ml-engine, email-engine, agents rows**

- [ ] **Step 2: For each finding — read file at reported line (±30 lines context)**

- [ ] **Step 3: Apply the minimal correct fix**

*Predictor guard when no active model:*
```python
# Before
model_version = ModelVersion.objects.get(is_active=True)

# After
model_version = ModelVersion.objects.filter(is_active=True).first()
if model_version is None:
    raise NoActiveModelError(
        "No active ModelVersion found. Train and activate a model first."
    )
```

*Feature leakage — remove post-outcome columns from feature list:*
```python
POST_OUTCOME_COLS = {'repayment_history', 'default_flag', 'outcome_label'}

# After — applied in data_generator_phases.py when building FEATURE_COLS
FEATURE_COLS = [c for c in ALL_COLS if c not in POST_OUTCOME_COLS]
```

*Prompt injection in email prompts — escape user values:*
```python
import html

safe_name = html.escape(str(applicant_name))
safe_purpose = html.escape(str(loan_purpose))
prompt = f"Write an email for {safe_name} who applied for {safe_purpose}"
```

*Bias fail-safe on API error — escalate instead of silently passing:*
```python
# Before
try:
    result = claude_client.call(bias_prompt)
except Exception:
    result = {"bias_detected": False}  # silently passes — wrong

# After
try:
    result = claude_client.call(bias_prompt)
except Exception as exc:
    logger.error("Bias detector call failed: %s", exc, exc_info=True)
    raise BiasDetectorUnavailableError("Bias check could not complete") from exc
```

- [ ] **Step 4: Run tests for all three layers**

```bash
docker compose exec backend python -m pytest backend/apps/ml_engine/ backend/apps/email_engine/ backend/apps/agents/ -x -q 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add <changed files>
git commit -m "fix(ml,email,agents): address high-severity findings from full-codebase review"
```

---

### Task 11: Apply HIGH Fixes — Frontend + Infra

**Files:** Determined by the HIGH section of `.tmp/review/triage.md`, filtered to frontend and infra layers.

- [ ] **Step 1: Read triage.md HIGH section, filter to frontend and infra rows**

- [ ] **Step 2: For each finding — read file at reported line (±30 lines context)**

- [ ] **Step 3: Apply the minimal correct fix**

*HTML rendering without sanitisation — use DOMPurify:*
```tsx
// Install if not present: npm install dompurify @types/dompurify
import DOMPurify from 'dompurify'

// Replace any unsanitised raw HTML render with:
const safeHtml = DOMPurify.sanitize(rawEmailContent)
// Then render safeHtml via the existing renderer
```

*Polling not stopped on unmount:*
```ts
// Before
useEffect(() => {
  const id = setInterval(refetch, 2000)
}, [])

// After
useEffect(() => {
  const id = setInterval(refetch, 2000)
  return () => clearInterval(id)
}, [refetch])
```

*Port bound to all interfaces in compose (should be localhost-only):*
```yaml
# Before
ports:
  - "5432:5432"

# After
ports:
  - "127.0.0.1:5432:5432"
```

*Missing acks_late on long-running Celery ML task:*
```python
# Before
@app.task(queue='ml')
def train_model_task(...):

# After
@app.task(queue='ml', acks_late=True)
def train_model_task(...):
```

- [ ] **Step 4: Run frontend tests and type-check**

```bash
cd frontend
npx vitest run 2>&1 | tail -20
npx tsc --noEmit 2>&1 | tail -20
```

Expected: vitest passes, tsc reports zero errors.

- [ ] **Step 5: Commit**

```bash
git add <changed files>
git commit -m "fix(frontend,infra): address high-severity findings from full-codebase review"
```

---

### Task 12: Apply MEDIUM Fixes — All Layers

**Files:** Determined by the MEDIUM section of `.tmp/review/triage.md`.

- [ ] **Step 1: Read triage.md MEDIUM section**

Work through each M-numbered finding in layer order: backend → ML → email → agents → frontend → infra.

- [ ] **Step 2: For each finding — read file at reported line (±30 lines context)**

- [ ] **Step 3: Apply the minimal correct fix**

*Missing test for a critical path — add to the relevant test file:*
```python
def test_predictor_raises_when_no_active_model(db):
    assert not ModelVersion.objects.filter(is_active=True).exists()
    with pytest.raises(NoActiveModelError):
        predict(sample_features())
```

*Silent exception — log it:*
```python
# Before
try:
    do_thing()
except Exception:
    pass

# After
try:
    do_thing()
except Exception as exc:
    logger.warning("do_thing failed, continuing: %s", exc)
```

*Missing select_related (MEDIUM performance):*
```python
# Before
emails = GeneratedEmail.objects.filter(loan_application=app)

# After
emails = GeneratedEmail.objects.filter(
    loan_application=app
).select_related('loan_application__user')
```

*TypeScript `any` — replace with real type:*
```ts
// Before
const data: any = response.data

// After
const data: LoanApplication = response.data as LoanApplication
```

- [ ] **Step 4: Run full test suites**

```bash
docker compose exec backend python -m pytest -x -q 2>&1 | tail -20
cd frontend && npx vitest run 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 5: Commit per layer cluster**

```bash
git add <backend changed files>
git commit -m "fix(backend): address medium findings from full-codebase review"

git add <frontend changed files>
git commit -m "fix(frontend): address medium findings from full-codebase review"
```

---

### Task 13: Apply LOW Fixes — All Layers

**Files:** Determined by the LOW section of `.tmp/review/triage.md`.

- [ ] **Step 1: Read triage.md LOW section**

Work through each L-numbered finding in layer order.

- [ ] **Step 2: Apply each LOW fix**

*Dead code — delete it entirely (do not leave commented blocks):*
```python
# Before — remove this entire block:
# def old_unused_function():
#     return None
```

*Unused import:*
```python
# Before
import numpy as np  # not used in this module

# After — remove the import line entirely
```

*Missing return type annotation:*
```python
# Before
def get_status(loan_id: int):

# After
def get_status(loan_id: int) -> str:
```

*TypeScript optional chain missing:*
```ts
// Before
const name = user.profile.name  // crashes if profile is null

// After
const name = user.profile?.name ?? 'Unknown'
```

- [ ] **Step 3: Run linters**

```bash
docker compose exec backend python -m ruff check backend/ 2>&1 | tail -20
cd frontend && npx eslint src/ 2>&1 | tail -20
```

Expected: no new lint errors.

- [ ] **Step 4: Run full test suites one final time**

```bash
docker compose exec backend python -m pytest -q 2>&1 | tail -20
cd frontend && npx vitest run 2>&1 | tail -20
cd frontend && npx tsc --noEmit 2>&1 | tail -20
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add <changed files>
git commit -m "chore(cleanup): apply low-severity cleanup from full-codebase review"
```

---

## Task 14: Final Verification

- [ ] **Step 1: Run the full backend test suite**

```bash
docker compose exec backend python -m pytest -q --tb=short 2>&1 | tail -30
```

Expected: all tests pass, no failures.

- [ ] **Step 2: Run the full frontend test suite and type-check**

```bash
cd frontend
npx vitest run 2>&1 | tail -20
npx tsc --noEmit 2>&1 | tail -10
```

Expected: all tests pass, zero TypeScript errors.

- [ ] **Step 3: Run ruff on backend**

```bash
docker compose exec backend python -m ruff check backend/ 2>&1 | tail -20
```

Expected: no errors.

- [ ] **Step 4: Spot-check the app in the browser**

Navigate to `http://localhost:3000`. Log in. Submit a loan application through the pipeline. Verify:
- Application status page loads correctly
- Decision section renders without errors
- No unexpected console errors

- [ ] **Step 5: Create release branch and PR**

```bash
git checkout -b fix/full-codebase-review-v1-11-1
git push origin fix/full-codebase-review-v1-11-1
gh pr create \
  --title "fix: full-codebase review and fix — v1.11.1" \
  --body "Systematic review across all 6 layers. Findings triaged in .tmp/review/triage.md. Fixes applied in CRITICAL→HIGH→MEDIUM→LOW order. All tests green."
```
