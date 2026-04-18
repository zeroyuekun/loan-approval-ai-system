# v1.10.2 — Bug / Security / Space Consolidation Design

**Status:** Approved
**Date:** 2026-04-19
**Target version:** 1.10.1 → 1.10.2
**Base branch:** `master` (tag `v1.10.1`, commit `4267040`)
**Predecessor:** v1.10.1 production hardening (6 atomic PRs, same methodology)

## Goal

Consolidate every residual bug, security hygiene issue, and disk-space / deadcode
concern surfaced during the post-v1.10.1 sweep into a single tagged hardening
release, shipped as an atomic PR stack in the v1.10.1 merge-order pattern.

## Scope

### In scope
1. Merge the three in-flight bug fix PRs already green on CI:
   - PR #103 — smoke_e2e.sh auth/profile/fixture fixes
   - PR #104 — watchdog `requests` → `httpx` (stops crashloop)
   - PR #105 — `CalibrationValidator` broken lazy-import fix
2. Seven new atomic PRs (`D1`..`D7`) covering newly-found bugs,
   defensive validators, security hygiene, deadcode removal, DX/space
   ergonomics, and the release bump.

### Out of scope (deferred to v1.10.3+)
- Issue #50, #51, #52, #53 — SLO instrumentation (new feature work, not bug fixes)
- Issue #58 — email availability probe guardrail wrap (non-trivial, needs own spec)
- Issue #59 — Fernet key rotation + GitHub Secrets move (CI-focused, separate spec)
- Issue #60 — bandit severity gate (CI policy change, separate spec)

### Explicit "close as stale" during D7
- Issue #56 — `DJANGO_SETTINGS_MODULE` default — **already present** in
  `backend/config/celery.py:8` (`os.environ.setdefault(...)`). Nothing to do.
- Issue #61 — `enforce_retention` regression test — the function was removed
  from the codebase; only stale `.coverage` / `.ruff_cache` references remain.

## Quality target
9.9/10 — matches the bar achieved by v1.10.1. Every PR must pass CI before
merge; the `mypy` gate on the 10 Arm C modules is preserved; live
`smoke_e2e.sh` must pass against the release tag.

---

## Architecture

Seven atomic PRs, each with its own feature branch, landed in order.
Each deliverable is self-contained: no PR depends on another PR's changes
beyond master being at the previous step. The last PR (D7) cuts the release.

```
master (v1.10.1)
 ├─ M1 PR #103  (smoke_e2e)
 ├─ M2 PR #104  (watchdog)
 ├─ M3 PR #105  (calibration)
 │
 ├─ D1 chore/v1-10-2-d1-utcnow             — Python 3.13 future-proofing
 ├─ D2 fix/v1-10-2-d2-seed-profile-scale   — demo data scale bug
 ├─ D3 fix/v1-10-2-d3-payment-pct-validator — defensive validator (#55)
 ├─ D4 fix/v1-10-2-d4-grafana-password     — security hygiene (#57)
 ├─ D5 chore/v1-10-2-d5-remove-dead-dice   — deadcode removal (#54 via removal)
 ├─ D6 chore/v1-10-2-d6-make-clean-soft    — DX/space ergonomics
 └─ D7 chore/v1-10-2-d7-release            — APP_VERSION bump + CHANGELOG + tag
       (also closes #56 #61 as stale)
```

---

## Deliverables

### M1 — Merge PR #103 (smoke_e2e.sh fixes)

Already open, CI green. User merges via GitHub UI or
`gh pr merge 103 --squash --delete-branch`.

**Files touched (existing PR):** `tools/smoke_e2e.sh`,
`tools/smoke_fixtures/smoke_applicant.json` (+54 / −19 lines)

**Gate:** All 13 CI checks green (verified: SUCCESS on every required check
2026-04-19).

---

### M2 — Merge PR #104 (watchdog crashloop fix)

Already open, CI green. One-line dep swap (`import requests` → `import httpx`)
plus exception-class rename.

**Files touched (existing PR):** `backend/apps/agents/management/commands/watchdog.py`
(+3 / −3 lines)

**Gate:** `docker compose ps watchdog` shows healthy cycles after merge-and-rebuild
(`Cycle complete — status: healthy`).

---

### M3 — Merge PR #105 (calibration lazy-import fix)

Already open, CI green. One-line import-path correction
(`backend.apps.ml_engine...` → `apps.ml_engine...`).

**Files touched (existing PR):** `backend/apps/ml_engine/services/calibration_validator.py`
(+1 / −1 lines)

**Gate:** `CalibrationValidator()` no-arg construction succeeds in the running
backend container (verified live).

---

### D1 — Replace `datetime.utcnow()` with `datetime.now(UTC)`

**Why:** Python 3.13 emits `DeprecationWarning: datetime.datetime.utcnow() is
deprecated and scheduled for removal in a future version`. Ten call sites in
`apps/ml_engine/services/*` will break when removed.

**Files:**
- `backend/apps/ml_engine/services/calibration_validator.py` — lines 159, 399
- `backend/apps/ml_engine/services/macro_data_service.py` — line 159
- `backend/apps/ml_engine/services/mrm_dossier.py` — line 351
- `backend/apps/ml_engine/services/plaid_patterns_service.py` — lines 217, 218
- `backend/apps/ml_engine/services/property_data_service.py` — lines 535, 545
- `backend/apps/ml_engine/services/real_world_benchmarks.py` — lines 316, 495

**Change pattern:**
```python
# Before
from datetime import datetime
datetime.utcnow().isoformat() + "Z"

# After
from datetime import UTC, datetime
datetime.now(UTC).isoformat()  # already includes +00:00; drop manual "Z"
```

For call sites that do `.isoformat() + "Z"` and the consumer specifically wants
trailing `Z`, substitute:
```python
datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
```

**Gate:** Full pytest suite (1454 passed / 27 skipped baseline) runs with zero
new `utcnow`-related `DeprecationWarning` entries under the captured warnings
for the touched `apps.ml_engine.services.*` modules. Other unrelated third-party
deprecation warnings are acceptable.

---

### D2 — Fix `seed_profiles.py` 0-1 vs 0-100 scale bug

**Why:** `on_time_payment_pct` is a percentage field (0-100, model default 100.0)
but `seed_profiles.py:37` generates `round(random.uniform(0.75, 1.0), 4)` —
i.e. fractional values between 0.75 and 1.0. Silently corrupts demo data and,
after D3 adds the validator, will start failing the seed command outright.

**Files:**
- `backend/apps/accounts/management/commands/seed_profiles.py` — line 37

**Change:**
```python
# Before
profile.on_time_payment_pct = round(random.uniform(0.75, 1.0), 4)
# After
profile.on_time_payment_pct = round(random.uniform(75.0, 100.0), 2)
```

**Gate:** `python manage.py seed_profiles --count 5` writes rows with
`on_time_payment_pct` between 75 and 100 (verified by follow-up `python manage.py
shell -c "..."`).

---

### D3 — Add 0-100 validator for `on_time_payment_pct` (closes #55)

**Why:** Model field accepts any float. Garbage values (150%, -5%) propagate
to training. Defensive at two layers: Django model-level (via `validators=`)
and DRF serializer-level (explicit `MinValueValidator` / `MaxValueValidator`).

**Files:**
- `backend/apps/accounts/models.py` — line 228 (add `validators=`)
- `backend/apps/accounts/serializers.py` — apply in `CustomerProfileSerializer`
- `backend/tests/test_profile_validators.py` — **new** — 3 tests (valid, too high,
  negative) for both model `.full_clean()` and serializer

Auditing existing out-of-range rows is deferred. The validator only applies
on save / full_clean; old rows stay as-is. No data migration needed. If the
PO later wants remediation, that's a separate spec.

**Change:**
```python
# models.py
from django.core.validators import MaxValueValidator, MinValueValidator

on_time_payment_pct = models.FloatField(
    default=100.0,
    validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
    help_text="Percentage of on-time payments (0-100)",
)
```

No data migration — `validators=` adds constraint metadata, not schema change.

**Gate:** New test file passes; existing tests unaffected; PATCH
`/api/v1/auth/me/profile/` with `on_time_payment_pct=150` returns 400.

---

### D4 — Require `GRAFANA_ADMIN_PASSWORD`, remove `changeme` default (closes #57)

**Why:** `docker-compose.monitoring.yml:305` currently defaults
`GF_SECURITY_ADMIN_PASSWORD` to `changeme`. Any fresh `docker-compose up -d
monitoring` exposes Grafana on a well-known password — a real-world exploitation
path if the host is ever exposed.

**Files:**
- `docker-compose.monitoring.yml` — line 305
- `.env.example` — add `GRAFANA_ADMIN_PASSWORD=` placeholder
- `README.md` — "required env vars" section

**Change:**
```yaml
# Before
- GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:-changeme}
# After
- GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:?GRAFANA_ADMIN_PASSWORD must be set}
```

The `${VAR:?error}` form causes `docker compose` to exit with a clear error
message if unset.

**Gate:** `docker compose -f docker-compose.monitoring.yml config` without the
env var exits non-zero with the error string; with it set, `config` prints clean
YAML; `docker compose up grafana` boots healthy when set.

---

### D5 — Remove dead `dice_ml` callpath from CounterfactualEngine (closes #54)

**Why:** `backend/apps/ml_engine/services/counterfactual_engine.py` has a
`_dice_counterfactuals` method that imports `dice_ml` — a library **not in
`backend/requirements.txt`**. The method is called from `generate()` only when
`self._transform_fn is None`. In production, `transform_fn` is always set (the
real prediction pipeline uses a transform wrapper); DiCE therefore never runs
for real users. When it does run in dev/tests, it raises
`ModuleNotFoundError`, which the `except Exception` block swallows, logging
`"DiCE counterfactuals failed/timed-out: ... — using fallback"`. Net effect:
log noise + wasted cycles on every call, zero upside.

Issue #54 proposes pinning `dice-ml>=0.11,<0.12`. Cleaner alternative: **delete
the dead path**. If DiCE is ever re-introduced, revive it under its own spec
with a real transform wrapper.

**Files:**
- `backend/apps/ml_engine/services/counterfactual_engine.py`:
  - Delete `_dice_counterfactuals` method (~50 lines)
  - Delete `_build_dice_dataset` method if only called by `_dice_counterfactuals`
  - Remove `if self._transform_fn is None: try: ... _dice_counterfactuals(...)`
    block in `generate()`
  - `generate()` now always uses `_fallback_binary_search`
- `backend/tests/test_counterfactual_*.py` — update any test asserting the DiCE
  path is attempted

**Change (summary):**
```python
# Before
def generate(self, features_df, original_loan_amount, timeout_seconds=20):
    prob = self._predict_prob(features_df)
    if prob >= self.threshold:
        return []
    if self._transform_fn is None:
        try:
            with _timeout_ctx(timeout_seconds):
                cfs = self._dice_counterfactuals(features_df, original_loan_amount)
                if cfs:
                    return cfs
        except (TimeoutError, Exception) as exc:
            logger.info("DiCE counterfactuals failed/timed-out: %s — using fallback", exc)
    return self._fallback_binary_search(features_df, original_loan_amount)

# After
def generate(self, features_df, original_loan_amount, timeout_seconds=20):
    prob = self._predict_prob(features_df)
    if prob >= self.threshold:
        return []
    return self._fallback_binary_search(features_df, original_loan_amount)
```

**Gate:** `grep -r "dice_ml" backend/` returns zero matches; `pytest
backend/tests/test_counterfactual*.py` passes; full `pytest` still green.

---

### D6 — Split `make clean` into `clean-soft` + `clean`

**Why:** Today `make clean` runs `docker compose down -v`, which nukes Postgres
+ Redis volumes. After the recent sweep, when a user runs `make clean` expecting
to reclaim build cache, they lose their seeded DB. This is a trap. Introduce a
`clean-soft` target that reclaims caches without touching volumes; keep `clean`
as-is for users who genuinely want a full wipe.

**Files:**
- `Makefile`

**Change:**
```makefile
clean-soft:              ## Reclaim cache space (DB + Redis volumes preserved)
	docker compose down
	find backend -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find backend -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -not -path "*/node_modules/*" -delete 2>/dev/null || true
	rm -rf frontend/.next frontend/coverage frontend/playwright-report frontend/test-results
	rm -rf backend/htmlcov backend/.coverage backend/.pytest_cache
	rm -f frontend/tsconfig.tsbuildinfo
	@echo "Soft clean complete. DB + Redis volumes preserved."

clean:                   ## Nuke ephemerals INCLUDING volumes (destructive!)
	docker compose down -v
	find backend -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find backend -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -not -path "*/node_modules/*" -delete 2>/dev/null || true
	rm -rf frontend/.next frontend/coverage frontend/playwright-report frontend/test-results
	rm -rf backend/htmlcov backend/.coverage backend/.pytest_cache
	rm -f frontend/tsconfig.tsbuildinfo
	@echo "Full clean complete. Volumes destroyed."
```

The `clean` body is effectively `clean-soft` steps plus `-v` on the compose
down. DRY is not introduced here (a single shared helper) because `make`
targets are executed independently and the body is short enough to keep
literal. If either list grows, refactor to a shared variable later.

README "Housekeeping" section gains a 2-line note on the distinction.

**Gate:** `make clean-soft` then `docker volume ls` still shows
`loan-approval-ai-system_postgres_data` + `_redis_data`; `make clean` removes
them.

---

### D7 — Release: APP_VERSION 1.10.1 → 1.10.2, CHANGELOG, close stale issues, tag

**Why:** Ship the release.

**Files:**
- `backend/config/settings/base.py` — `APP_VERSION = "1.10.2"`
- `CHANGELOG.md` — new `## [1.10.2] - 2026-04-19` section listing D1-D6

**Issue closure attribution:**
- D3's PR body: `Closes #55` (validator) — closes on merge
- D4's PR body: `Closes #57` (Grafana password) — closes on merge
- D5's PR body: `Closes #54` (DiCE pin) — closes on merge via deadcode removal
- D7's release PR body: `Closes #56 #61` (stale issues) — with a one-line
  comment on each before close linking the verifying commit

**Gate:**
- `tools/smoke_e2e.sh` passes against `v1.10.2` tag (local run + `workflow_dispatch`
  CI from Actions tab)
- `git tag v1.10.2 <commit>` + `git push origin v1.10.2`
- All four attributions above actually closed post-merge
  (`gh issue view <N> --json state`)

---

## Testing strategy

- **Per-PR:** every branch must pass all required CI checks before merge
  (Backend Tests, Backend Lint, Backend mypy, Frontend Tests, Frontend
  Lint & Type Check, ml_engine quality bar, Security Scan, Dependency
  Audit, secret-scan, Docker Build).
- **Pre-D7:** run `tools/smoke_e2e.sh --keep-up` locally from the
  soon-to-be-tagged commit; verify approval + email delivery still work.
- **Post-D7:** trigger `smoke-e2e` GitHub Actions workflow via workflow_dispatch
  against tag `v1.10.2`; confirm a green run before announcing the release.

## Risk / rollback

Each PR is a self-contained, small commit. If any PR later regresses, revert is
`git revert <merge-commit>` without touching the others. D5 (DiCE removal) is
the largest blast-radius change (~50 lines deleted) but is backed by the
existing fallback path and has no production caller.

## Memory notes (post-release)

- Save project memory entry mirroring `project_v1_10_1_production_hardening.md`
  format; key points: 7 PRs landed, tag `v1.10.2`, closes 4 issues (2 real, 2
  stale), ~10.5 GB disk reclaim already baked in from pre-sweep.
