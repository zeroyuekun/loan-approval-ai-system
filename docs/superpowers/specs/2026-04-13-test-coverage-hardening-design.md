# Test Coverage Hardening — Design Spec

**Date:** 2026-04-13
**Branch:** `chore/test-coverage-hardening` (off `master`)
**Sub-project:** 2 of 4 in the optimization program (review → **tests** → design → perf)
**Feeds from:** `docs/superpowers/reviews/2026-04-13-code-review-sweep.md`
**Status:** Approved for implementation planning

## Purpose

Turn the test suite into a trustworthy regression safety net before any refactoring lands (Sub-project 3) or performance work begins (Sub-project 4). Close the concrete gaps identified in the Sub-project 1 findings: unblock 205 local-failing tests, fix test assertions that can never fail, de-skip four legitimately useful tests, cover five service modules that currently have zero tests, add accessibility coverage across the frontend, and raise the CI coverage floor with risk-matched per-app thresholds.

## Success Criteria

- `pytest` runs locally with **0 errors, 0 failures** (from the current 783 pass / 205 error baseline).
- The four currently-skipped tests (weighted traffic splitting, PSI symmetry, categorical derived-features, orchestrate-task serialisation) pass deterministically over 20 consecutive local runs.
- Five previously-untested service modules have unit test files with meaningful, mutation-resistant assertions.
- `sender.py` has functional (not mocked) coverage using Django's `locmem` email backend.
- All frontend component tests that render a component include a `vitest-axe` assertion.
- CI coverage thresholds (per-app) pass in one green run.
- Branch has a clean commit history (one commit per discrete fix) and can be pushed/PR'd.

## Architecture

Four implementation phases executed sequentially. Each phase gates on the prior phase being green.

```
Phase A  Foundation             → unblock the suite
Phase B  Critical fixes         → fix broken assertions + de-skip + consolidation
Phase C  Coverage fill          → test the 5 untested service modules + sender.py
Phase D  Hygiene + raise floor  → axe, weak-assertion fixes, per-app thresholds
```

Every phase ends with `pytest` green before the next begins. Any phase that cannot reach green without compromising the spec causes a STOP and is escalated to the user.

## Scope — In and Out

**In scope:**
- `config/settings/test.py` creation + `pytest.ini` + coverage config
- XSS assertion fix
- De-skipping the 4 named flaky tests with proper seed-based fixes
- Removing module-level `skip_without_redis` in `test_api_contracts.py`
- Consolidating duplicate `skip_without_redis` helpers onto the `conftest` version
- Converting `test_guardrails.py` off `django.test.TestCase`
- Adding `test_email_sender.py` with `locmem` backend
- Unit tests for: `underwriting_engine.py`, `lifecycle.py`, `recommendation_engine.py`, `loan_performance_simulator.py`, `benchmark_resolver.py`
- Frontend axe assertions across all `__tests__/*.test.tsx` that render a component
- Strengthening weak assertions in `test_celery_integration.py`
- Celery fixture `task_eager_propagates: True`
- MSW `onUnhandledRequest: 'warn'`
- Wiring schemathesis test into CI (`RUN_CONTRACT_TESTS: "1"`)
- Raising coverage gate to per-app thresholds

**Out of scope:**
- Fixing the Critical/High source-code findings (soft-delete bypass, frontend standalone image, apology-language guardrail, etc.) — belongs to Sub-project 3
- Refactoring existing production code beyond what tests require
- Adding new features or behaviour
- Changing the ML engine's algorithms or calibration
- Touching Docker or deployment

## Coverage Threshold Policy

Per-app `fail_under` in `.coveragerc` (or `[tool.coverage]` in `pyproject.toml`):

| App | Target | Rationale |
|---|---:|---|
| `apps.ml_engine` | 85% | Credit decisioning; regulator-inspected |
| `apps.email_engine` | 85% | Guardrails + Claude API; compliance-critical |
| `apps.agents` | 80% | Orchestrator; complex but wrapped by the above |
| `apps.loans` | 80% | Loan CRUD + state machine; core workflow |
| `apps.accounts` | 75% | Auth + PII; already well-covered |
| `apps.common` | 70% | Utility code; lower blast radius |

No industry-standard fintech-specific threshold exists; these are defensible by risk tier, consistent with banking guidance of risk-based testing depth. The global `--cov-fail-under=60` in `ci.yml` is removed in favour of these per-app gates.

If a threshold is not achievable for an app in Phase D (e.g., `ml_engine` because artefacts can't be generated in CI), set the threshold at the highest realistic number with a comment naming the blocker, rather than lowering to hide the gap.

## Components

### New files

- `backend/config/settings/test.py` — extends `base.py`:
  - `DATABASES['default']` = SQLite in-memory
  - `CELERY_TASK_ALWAYS_EAGER = True`
  - `FIELD_ENCRYPTION_KEY` = deterministic 32-byte Fernet key for tests
  - `DJANGO_SECRET_KEY` = deterministic string for tests
  - `PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]` to speed tests
  - Migration-skip trick so SQLite setup is fast:
    ```python
    class _DisableMigrations:
        def __contains__(self, item): return True
        def __getitem__(self, item): return None
    MIGRATION_MODULES = _DisableMigrations()
    ```
- `backend/pytest.ini`:
  ```ini
  [pytest]
  DJANGO_SETTINGS_MODULE = config.settings.test
  addopts = --strict-markers --reuse-db --cov-config=.coveragerc
  markers =
      slow: marks tests as slow
  ```
- `backend/.coveragerc` — `fail_under` per app via `[coverage:report]` sections or split configs.
- `backend/tests/test_email_sender.py` — real sender path via `override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")`. Asserts: audit record created, subject matches template, recipient matches applicant email, HTML body is valid HTML.
- `backend/tests/test_underwriting_engine.py`, `test_lifecycle.py`, `test_recommendation_engine.py`, `test_loan_performance_simulator.py`, `test_benchmark_resolver.py` — unit tests for each service module. Target: function-level for primary APIs, edge cases (None inputs, empty collections, boundary values), failure modes (external service exceptions).
- `frontend/src/test/axe-helper.ts` — exports `expectNoAxeViolations(container: HTMLElement)` wrapping `vitest-axe`'s `toHaveNoViolations()`.

### Modified files

- `backend/tests/test_security.py:47, 51-53` — replace conditional `if response.status_code == 200:` with unconditional `assert status_code == 200`; split the XSS disjunction into two unconditional assertions.
- `backend/tests/conftest.py` — add `celery_config_eager` fixture; standardise the canonical `skip_without_redis` on `db=0`; change `task_eager_propagates: True`.
- `backend/tests/test_celery_integration.py:39-69` — strengthen `assert result is not None` to `assert result.state in ("SUCCESS", "FAILURE")` and `assert result.id is not None`. Remove skip at `:53`; fix flakiness via seeded Celery task patching.
- `backend/tests/test_champion_challenger.py:48` — remove skip; seed `random.Random` in the weighted-distribution test.
- `backend/tests/test_drift_monitor.py:50` — remove skip; tighten PSI symmetry tolerance using seeded RNG.
- `backend/tests/test_property_based_predictor.py:633` — remove skip; add `@settings(max_examples=50, derandomize=True)`.
- `backend/tests/test_api_contracts.py:30-31` — remove `pytestmark = skip_without_redis`. Delete the local helper function.
- `backend/tests/test_auth_security.py:16-30`, `test_cors_and_schema.py:8-23` — delete local `skip_without_redis` definitions; `from tests.conftest import skip_without_redis`.
- `backend/tests/test_guardrails.py` — convert `GuardrailTestCase(TestCase)` to plain `class TestGuardrails:`; replace `self.assertEqual`/`self.assertTrue` with bare `assert`.
- `frontend/src/test/setup.ts:20` — change `onUnhandledRequest: 'bypass'` to `'warn'`.
- `frontend/package.json` — add `vitest-axe` to `devDependencies`.
- `frontend/src/__tests__/**/*.test.tsx` — for every test that mounts a component (via `render()`), append `await expectNoAxeViolations(container)`. Tests that only assert functions or hooks without rendering are exempt.
- `.github/workflows/ci.yml` — add `RUN_CONTRACT_TESTS: "1"` to the `backend-test` job env block; remove the global `--cov-fail-under=60` (per-app thresholds in `.coveragerc` take over).

## Data Flow

The work order is sequential:

```
Phase A → Phase B → Phase C → Phase D
```

Within each phase, fixes are committed separately (one commit per discrete fix) to keep history reviewable. `pytest` must be green between commits. De-skipped tests require a **20-run determinism check** recorded in the commit message before the de-skip lands.

## Error Handling

- **Test settings import fails:** use a real 32-byte Fernet key, not a placeholder; check `env_validation.py` doesn't block tests (it is a no-op in DEBUG per the Medium finding).
- **A "flaky" test isn't fixable by seeding:** leave the skip with a specific reason + linked TODO, raise to user. No generic "flaky on CI" skips.
- **Coverage threshold unreachable for an app:** set to the highest realistic number, comment why, raise to user rather than hiding.
- **`vitest-axe` surfaces pre-existing violations:** fix trivial ones; for complex violations fail the assertion and flag for Sub-project 3. Do not silently exclude rules.
- **De-skip causes a new failure:** investigate as a real regression. No re-skipping.
- **Phase can't reach green:** STOP, report state, do not proceed.

## Validation / Quality Gates

- **Per-commit:** `pytest` green (backend) and `npm test` green (frontend).
- **De-skip commits:** 20 consecutive local runs green, recorded in commit message.
- **Assertion strength:** for each of the 5 new service test files, introduce a one-line bug in the service, confirm the test catches it, revert. Done once per module.
- **No over-mocking:** mocks only at external boundaries (Claude API, SMTP, Redis).
- **Coverage gate:** all per-app thresholds pass in one CI run after Phase D.
- **Axe gate:** full frontend test suite passes with axe assertions active; no silent `excludes`.
- **Final:** CI green on push; coverage report attached to the PR.

## Safety & Reversibility

- Dedicated branch off `master`, leaving `chore/code-review-sweep` (Sub-project 1) and `feat/rating-push-9-5` untouched.
- No source code outside tests/config is modified. No production-path logic changes.
- Each phase is independently revertable: if Phase C must be undone, Phase B's gains remain.
- No new dependencies in production paths (`vitest-axe` is a dev-only dep).
- No Docker/deploy changes.

## Out of Scope Reminders

Deferred to Sub-project 3 (design improvements): soft-delete bypass, frontend standalone image, apology-language guardrail, NCCP Act name, Celery graceful shutdown, Grafana password, circuit breaker consolidation, file-size refactors.

Deferred to Sub-project 4 (performance): `_api_available()` probe removal, dashboard stats cache TTL, `_conformal_interval` sort, N+1 audit.

## Next Step

After user sign-off on this spec, invoke the `superpowers:writing-plans` skill to produce a step-by-step implementation plan.
