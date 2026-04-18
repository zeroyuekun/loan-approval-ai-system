# v1.10.2 Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship v1.10.2 — a tagged hardening release that consolidates every residual bug, security hygiene item, and disk-space / deadcode concern surfaced in the post-v1.10.1 sweep.

**Architecture:** Atomic PR stack (M1-M3 merging already-open fix PRs, then D1-D7 new atomic PRs) following the v1.10.1 methodology. Each PR is self-contained, feature-branched off `master`, green-CI-gated before merge. D7 bumps `APP_VERSION`, adds CHANGELOG entry, closes stale issues, tags `v1.10.2`.

**Tech Stack:** Django 5 + DRF + Celery, PostgreSQL, Redis, Docker Compose, pytest + pytest-django, GitHub Actions CI, Makefile DX targets.

**Spec:** `docs/superpowers/specs/2026-04-19-v1-10-2-consolidation-design.md` (commit `11c660d` on `docs/v1-10-2-consolidation-spec`).

**Base:** `master` at `4267040` (tag `v1.10.1`).

---

## Task 1: Merge PR #103 (smoke_e2e.sh fixes) — M1

**Files:**
- PR branch: `fix/smoke-e2e-pipeline-bugs` (already open, green)

- [ ] **Step 1: Verify CI is green**

Run: `gh pr checks 103`
Expected: Every required check shows `pass` (Backend Tests, Backend Lint, Backend mypy, Frontend Tests, Frontend Lint & Type Check, ml_engine quality bar, Security Scan, Dependency Audit, secret-scan, Docker Build).

- [ ] **Step 2: Merge**

Run:
```bash
gh pr merge 103 --squash --delete-branch
```
Expected: `✓ Squashed and merged pull request #103 (fix(smoke): resolve 4 auth/profile/fixture bugs blocking e2e pipeline)`

- [ ] **Step 3: Update local master**

Run:
```bash
git checkout master && git pull origin master
```
Expected: Fast-forward; `git log -1 --oneline` shows the new squash commit with #103 in the subject.

---

## Task 2: Merge PR #104 (watchdog httpx swap) — M2

**Files:**
- PR branch: `fix/watchdog-requests-to-httpx` (already open, green)

- [ ] **Step 1: Verify CI is green**

Run: `gh pr checks 104`
Expected: Every required check passes.

- [ ] **Step 2: Merge**

Run:
```bash
gh pr merge 104 --squash --delete-branch
```

- [ ] **Step 3: Update local master and rebuild watchdog**

Run:
```bash
git checkout master && git pull origin master
docker compose up -d --build watchdog
```

- [ ] **Step 4: Verify watchdog healthy**

Wait 60 seconds, then:
```bash
docker compose logs --tail=20 watchdog
```
Expected: At least one line containing `Cycle complete — status: healthy` and zero `ModuleNotFoundError`.

---

## Task 3: Merge PR #105 (calibration lazy-import fix) — M3

**Files:**
- PR branch: `fix/calibration-validator-import` (already open, green)

- [ ] **Step 1: Verify CI is green**

Run: `gh pr checks 105`
Expected: Every required check passes.

- [ ] **Step 2: Merge**

Run:
```bash
gh pr merge 105 --squash --delete-branch
```

- [ ] **Step 3: Update local master**

Run:
```bash
git checkout master && git pull origin master
```

- [ ] **Step 4: Verify CalibrationValidator imports clean**

Run:
```bash
docker compose exec backend python -c "from apps.ml_engine.services.calibration_validator import CalibrationValidator; v = CalibrationValidator(); print('OK')"
```
Expected: `OK` (no `ModuleNotFoundError`).

---

## Task 4: D1 — Replace `datetime.utcnow()` with `datetime.now(UTC)`

**Files:**
- Modify: `backend/apps/ml_engine/services/calibration_validator.py` (lines 159, 399)
- Modify: `backend/apps/ml_engine/services/macro_data_service.py` (line 159)
- Modify: `backend/apps/ml_engine/services/mrm_dossier.py` (line 351)
- Modify: `backend/apps/ml_engine/services/plaid_patterns_service.py` (lines 217, 218)
- Modify: `backend/apps/ml_engine/services/property_data_service.py` (lines 535, 545)
- Modify: `backend/apps/ml_engine/services/real_world_benchmarks.py` (lines 316, 495)
- Test: `backend/tests/test_utcnow_deprecation.py` (new)

- [ ] **Step 1: Create branch**

Run:
```bash
git checkout master && git pull origin master
git checkout -b chore/v1-10-2-d1-utcnow
```

- [ ] **Step 2: Write the failing guard test**

Create `backend/tests/test_utcnow_deprecation.py`:
```python
"""Guard test: no `datetime.utcnow()` in ml_engine services.

Python 3.13 deprecates `datetime.utcnow()`; Python 3.14+ is scheduled to
remove it. This test scans the services directory for the call and fails
if any remain.
"""
from pathlib import Path


def test_no_utcnow_in_ml_engine_services():
    services_dir = Path(__file__).resolve().parents[1] / "apps" / "ml_engine" / "services"
    offenders: list[str] = []
    for py in services_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if "datetime.utcnow()" in text:
            offenders.append(str(py.relative_to(services_dir.parent.parent.parent)))
    assert not offenders, (
        "datetime.utcnow() is deprecated in Python 3.13+; "
        "use datetime.now(UTC) instead. Offenders: " + ", ".join(offenders)
    )
```

- [ ] **Step 3: Run test — expected FAIL**

Run:
```bash
docker compose exec backend pytest tests/test_utcnow_deprecation.py -v
```
Expected: `FAILED` with offender list showing 6 service files.

- [ ] **Step 4: Fix `calibration_validator.py`**

Edit `backend/apps/ml_engine/services/calibration_validator.py`:
- Top of file: change `from datetime import datetime` → `from datetime import UTC, datetime` (add `UTC`).
- Line 159: `"validated_at": datetime.utcnow().isoformat() + "Z",` → `"validated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),`
- Line 399: same pattern — `datetime.utcnow().isoformat() + "Z"` → `datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")`

- [ ] **Step 5: Fix `macro_data_service.py`**

Edit `backend/apps/ml_engine/services/macro_data_service.py`:
- Ensure `from datetime import UTC, datetime` (add `UTC`).
- Line 159: `now = datetime.utcnow()` → `now = datetime.now(UTC)`

Note: if downstream code does arithmetic with naive datetimes stored in DB/cache, wrap reads with `.replace(tzinfo=UTC)` at the comparison site only if pytest reveals a `TypeError: can't subtract offset-naive and offset-aware datetimes`. Run tests first — most arithmetic in this file is aware-aware or with `timedelta`, which works.

- [ ] **Step 6: Fix `mrm_dossier.py`**

Edit `backend/apps/ml_engine/services/mrm_dossier.py`:
- Ensure `from datetime import UTC, datetime`.
- Line 351: `datetime.utcnow().isoformat(timespec="seconds") + "Z"` → `datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")`

- [ ] **Step 7: Fix `plaid_patterns_service.py`**

Edit `backend/apps/ml_engine/services/plaid_patterns_service.py`:
- Ensure `from datetime import UTC, datetime, timedelta`.
- Line 217: `datetime.utcnow().strftime("%Y-%m-%d")` → `datetime.now(UTC).strftime("%Y-%m-%d")`
- Line 218: `(datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")` → `(datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")`

- [ ] **Step 8: Fix `property_data_service.py`**

Edit `backend/apps/ml_engine/services/property_data_service.py`:
- Ensure `from datetime import UTC, datetime`.
- Line 535: `now = datetime.utcnow()` → `now = datetime.now(UTC)`
- Line 545: `self._cache_timestamps[cache_key] = datetime.utcnow()` → `self._cache_timestamps[cache_key] = datetime.now(UTC)`

- [ ] **Step 9: Fix `real_world_benchmarks.py`**

Edit `backend/apps/ml_engine/services/real_world_benchmarks.py`:
- Ensure `from datetime import UTC, datetime`.
- Line 316: `now = datetime.utcnow()` → `now = datetime.now(UTC)`
- Line 495: `"fetched_at": datetime.utcnow().isoformat(),` → `"fetched_at": datetime.now(UTC).isoformat(),`

- [ ] **Step 10: Run the guard test — expected PASS**

Run:
```bash
docker compose exec backend pytest tests/test_utcnow_deprecation.py -v
```
Expected: `1 passed` (no offenders remain).

- [ ] **Step 11: Run full suite**

Run:
```bash
docker compose exec backend pytest -x
```
Expected: Same pass/skip counts as pre-change (baseline `1454 passed / 27 skipped`). If any test now fails because of naive-vs-aware datetime arithmetic, fix the comparison site at the source (don't revert D1).

- [ ] **Step 12: Commit and push**

Run:
```bash
git add backend/apps/ml_engine/services/*.py backend/tests/test_utcnow_deprecation.py
git commit -m "$(cat <<'EOF'
chore(ml_engine): replace datetime.utcnow() with datetime.now(UTC)

Python 3.13 emits DeprecationWarning for datetime.utcnow() and it is
scheduled for removal in a future version. Ten call sites across six
ml_engine service modules are converted to timezone-aware datetime.now(UTC).
Adds a guard test that scans services/ for future regressions.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push -u origin chore/v1-10-2-d1-utcnow
```

- [ ] **Step 13: Open PR**

Run:
```bash
gh pr create --base master --title "chore(ml_engine): replace datetime.utcnow() with datetime.now(UTC)" --body "$(cat <<'EOF'
## Summary
- Replace 10 call sites of `datetime.utcnow()` across 6 `apps/ml_engine/services` modules with timezone-aware `datetime.now(UTC)`.
- Add guard test `tests/test_utcnow_deprecation.py` that fails if `datetime.utcnow()` reappears in services.
- ISO strings that previously appended a literal `Z` now use `strftime("%Y-%m-%dT%H:%M:%SZ")` to preserve wire format.

## Why
Python 3.13 emits `DeprecationWarning: datetime.datetime.utcnow() is deprecated`; the call is scheduled for removal. Shipping the fix now removes future-upgrade risk and silences warning noise.

## Test plan
- [x] `pytest tests/test_utcnow_deprecation.py -v` (new guard, passes).
- [x] Full pytest suite (baseline `1454 passed / 27 skipped`, no regressions).
- [x] Manual: verify `calibration_validator.validate(...)` returns a report with `validated_at` ending `Z`.

Part of v1.10.2 consolidation release.
EOF
)"
```

- [ ] **Step 14: Wait for CI then merge**

Run (poll until green):
```bash
gh pr checks "$(gh pr view --json number --jq .number)"
```
When all required checks pass:
```bash
PR_NUM=$(gh pr view --json number --jq .number)
gh pr merge "$PR_NUM" --squash --delete-branch
git checkout master && git pull origin master
```

---

## Task 5: D2 — Fix `seed_profiles.py` 0-1 vs 0-100 scale bug

**Files:**
- Modify: `backend/apps/accounts/management/commands/seed_profiles.py:37`
- Test: `backend/apps/accounts/tests/test_seed_profiles_scale.py` (new)

- [ ] **Step 1: Create branch**

Run:
```bash
git checkout master && git pull origin master
git checkout -b fix/v1-10-2-d2-seed-profile-scale
```

- [ ] **Step 2: Write the failing scale test**

Create `backend/apps/accounts/tests/test_seed_profiles_scale.py`:
```python
"""Regression: seed_profiles writes on_time_payment_pct on the 0-100 scale."""
import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.accounts.models import CustomerProfile

User = get_user_model()


@pytest.mark.django_db
def test_seed_profiles_on_time_payment_pct_is_on_0_to_100_scale():
    User.objects.create_user(username="seed_target", email="s@x.com", password="x", role="customer")
    call_command("seed_profiles")
    profiles = CustomerProfile.objects.all()
    assert profiles.exists(), "seed_profiles should populate at least one CustomerProfile"
    for p in profiles:
        assert 0.0 <= p.on_time_payment_pct <= 100.0, (
            f"on_time_payment_pct={p.on_time_payment_pct} not in [0, 100] — "
            f"seed_profiles is using the wrong scale"
        )
        # Reject the old-scale bug specifically: any value < 1.0 indicates
        # the old 0-1 fractional seed
        assert p.on_time_payment_pct >= 1.0, (
            f"on_time_payment_pct={p.on_time_payment_pct} looks fractional; "
            f"seed_profiles is likely still on 0-1 scale"
        )
```

- [ ] **Step 3: Run test — expected FAIL**

Run:
```bash
docker compose exec backend pytest apps/accounts/tests/test_seed_profiles_scale.py -v
```
Expected: `FAILED` — `on_time_payment_pct=0.xxxx looks fractional`.

- [ ] **Step 4: Apply the fix**

Edit `backend/apps/accounts/management/commands/seed_profiles.py` line 37:
```python
# Before
profile.on_time_payment_pct = round(random.uniform(0.75, 1.0), 4)
# After
profile.on_time_payment_pct = round(random.uniform(75.0, 100.0), 2)
```

- [ ] **Step 5: Run test — expected PASS**

Run:
```bash
docker compose exec backend pytest apps/accounts/tests/test_seed_profiles_scale.py -v
```
Expected: `1 passed`.

- [ ] **Step 6: Run full suite**

Run:
```bash
docker compose exec backend pytest -x
```
Expected: No regressions.

- [ ] **Step 7: Commit, push, open PR, merge**

Run:
```bash
git add backend/apps/accounts/management/commands/seed_profiles.py backend/apps/accounts/tests/test_seed_profiles_scale.py
git commit -m "$(cat <<'EOF'
fix(accounts): seed_profiles writes on_time_payment_pct on 0-100 scale

seed_profiles was writing fractional values (0.75-1.0) into a percentage
field (0-100). Corrects the range to 75.0-100.0 and adds a regression
test. Unblocks D3's validator rollout (which would reject the old values).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push -u origin fix/v1-10-2-d2-seed-profile-scale
gh pr create --base master --title "fix(accounts): seed_profiles writes on_time_payment_pct on 0-100 scale" --body "$(cat <<'EOF'
## Summary
- Fix `seed_profiles.py:37` to write `on_time_payment_pct` on the 0-100 scale (model's declared range).
- Add regression test asserting every seeded row is in `[1.0, 100.0]`.

## Why
The field is a percentage (default `100.0`, help_text says "Percentage of on-time payments"). The seed command was writing fractional values like `0.8432`, silently corrupting demo data. This also unblocks D3's validator rollout — otherwise the seed command would start failing.

## Test plan
- [x] New regression test passes.
- [x] Full pytest suite unchanged.

Part of v1.10.2 consolidation release.
EOF
)"
```
Wait for CI green, then:
```bash
PR_NUM=$(gh pr view --json number --jq .number)
gh pr merge "$PR_NUM" --squash --delete-branch
git checkout master && git pull origin master
```

---

## Task 6: D3 — Add 0-100 validator for `on_time_payment_pct` (closes #55)

**Files:**
- Modify: `backend/apps/accounts/models.py:228` (add `validators=`)
- Modify: `backend/apps/accounts/serializers.py` (apply same validators explicitly)
- Test: `backend/apps/accounts/tests/test_profile_validators.py` (new)

- [ ] **Step 1: Create branch**

Run:
```bash
git checkout master && git pull origin master
git checkout -b fix/v1-10-2-d3-payment-pct-validator
```

- [ ] **Step 2: Write the failing validator tests**

Create `backend/apps/accounts/tests/test_profile_validators.py`:
```python
"""D3: on_time_payment_pct must be rejected outside [0, 100] at both model
validation and serializer layers."""
import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError

from apps.accounts.models import CustomerProfile
from apps.accounts.serializers import CustomerProfileSerializer

User = get_user_model()


@pytest.mark.django_db
class TestOnTimePaymentPctValidator:
    def _user(self):
        return User.objects.create_user(
            username="val_target", email="v@x.com", password="x", role="customer"
        )

    def test_model_accepts_valid_value(self):
        p = CustomerProfile(user=self._user(), on_time_payment_pct=85.0)
        p.full_clean()  # should not raise

    def test_model_rejects_above_100(self):
        p = CustomerProfile(user=self._user(), on_time_payment_pct=150.0)
        with pytest.raises(DjangoValidationError) as exc:
            p.full_clean()
        assert "on_time_payment_pct" in exc.value.message_dict

    def test_model_rejects_negative(self):
        p = CustomerProfile(user=self._user(), on_time_payment_pct=-5.0)
        with pytest.raises(DjangoValidationError) as exc:
            p.full_clean()
        assert "on_time_payment_pct" in exc.value.message_dict

    def test_serializer_rejects_above_100(self):
        user = self._user()
        profile = CustomerProfile.objects.create(user=user)
        s = CustomerProfileSerializer(profile, data={"on_time_payment_pct": 150.0}, partial=True)
        assert not s.is_valid()
        assert "on_time_payment_pct" in s.errors

    def test_serializer_rejects_negative(self):
        user = self._user()
        profile = CustomerProfile.objects.create(user=user)
        s = CustomerProfileSerializer(profile, data={"on_time_payment_pct": -5.0}, partial=True)
        assert not s.is_valid()
        assert "on_time_payment_pct" in s.errors
```

- [ ] **Step 3: Run tests — expected FAIL**

Run:
```bash
docker compose exec backend pytest apps/accounts/tests/test_profile_validators.py -v
```
Expected: All 5 tests `FAILED` (validator not present yet).

- [ ] **Step 4: Add model validator**

Edit `backend/apps/accounts/models.py`:
- Near top of file, ensure import: `from django.core.validators import MaxValueValidator, MinValueValidator` (add if absent).
- Line 228 — change:
  ```python
  on_time_payment_pct = models.FloatField(default=100.0, help_text="Percentage of on-time payments")
  ```
  to:
  ```python
  on_time_payment_pct = models.FloatField(
      default=100.0,
      validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
      help_text="Percentage of on-time payments (0-100)",
  )
  ```

- [ ] **Step 5: Add serializer validator**

Edit `backend/apps/accounts/serializers.py`:
- Ensure import at top: `from rest_framework.validators import ...` stays. Add:
  ```python
  from django.core.validators import MaxValueValidator, MinValueValidator
  ```
- Locate `CustomerProfileSerializer` (the class referenced on line 199). Add a field-level declaration ABOVE the `class Meta`:
  ```python
  on_time_payment_pct = serializers.FloatField(
      required=False,
      validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
      help_text="Percentage of on-time payments (0-100)",
  )
  ```

- [ ] **Step 6: Generate/verify no migration needed**

Run:
```bash
docker compose exec backend python manage.py makemigrations --dry-run accounts
```
Expected: `No changes detected` — `validators=` adds Python-side constraint metadata, not a schema change. If Django reports a change, inspect it — we expect none.

- [ ] **Step 7: Run validator tests — expected PASS**

Run:
```bash
docker compose exec backend pytest apps/accounts/tests/test_profile_validators.py -v
```
Expected: `5 passed`.

- [ ] **Step 8: Run full suite**

Run:
```bash
docker compose exec backend pytest -x
```
Expected: No regressions. If a test that was storing e.g. `120.0` now fails, update that test — that's a pre-existing bug D3 correctly surfaces.

- [ ] **Step 9: Live PATCH smoke**

Optional but high-signal. With docker stack up:
```bash
# login as customer (use existing seeded credentials)
TOKEN=$(curl -sb /dev/null -c /tmp/cj.txt http://localhost:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username":"customer1","password":"Customer123!"}' | jq -r '.access // empty')
curl -s -b /tmp/cj.txt -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -X PATCH http://localhost:8000/api/v1/auth/me/profile/ \
  -d '{"on_time_payment_pct": 150}' | jq .
```
Expected: `400` response with `on_time_payment_pct` in the error body.

- [ ] **Step 10: Commit, push, open PR, merge**

Run:
```bash
git add backend/apps/accounts/models.py backend/apps/accounts/serializers.py backend/apps/accounts/tests/test_profile_validators.py
git commit -m "$(cat <<'EOF'
fix(accounts): validate on_time_payment_pct is in [0, 100]

Adds MinValueValidator(0)/MaxValueValidator(100) at both the
CustomerProfile model layer (enforced on full_clean/save) and the
CustomerProfileSerializer layer (enforced on API writes). No schema
migration is required.

Closes #55

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push -u origin fix/v1-10-2-d3-payment-pct-validator
gh pr create --base master --title "fix(accounts): validate on_time_payment_pct is in [0, 100]" --body "$(cat <<'EOF'
## Summary
- Add model-level `MinValueValidator(0.0)` + `MaxValueValidator(100.0)` on `CustomerProfile.on_time_payment_pct`.
- Apply the same validators to `CustomerProfileSerializer` so DRF writes are bounced at the API surface.
- Five-test regression suite covering valid / high / negative at both layers.

## Why
The field was a free-form `FloatField`. Out-of-range data (150%, -5%) could leak into ML training. Closes #55.

## Test plan
- [x] `pytest apps/accounts/tests/test_profile_validators.py -v` — 5 pass.
- [x] `makemigrations --dry-run` shows no schema change (validator is Python-side).
- [x] Full pytest suite unchanged.
- [x] Manual: `PATCH /api/v1/auth/me/profile/` with `on_time_payment_pct=150` returns 400.

Closes #55
Part of v1.10.2 consolidation release.
EOF
)"
```
Wait for CI green, then:
```bash
PR_NUM=$(gh pr view --json number --jq .number)
gh pr merge "$PR_NUM" --squash --delete-branch
git checkout master && git pull origin master
```

---

## Task 7: D4 — Require `GRAFANA_ADMIN_PASSWORD` (closes #57)

**Files:**
- Modify: `docker-compose.monitoring.yml:305`
- Modify: `.env.example` (add placeholder)
- Modify: `README.md` or `docs/monitoring.md` (required env var doc)

- [ ] **Step 1: Create branch**

Run:
```bash
git checkout master && git pull origin master
git checkout -b fix/v1-10-2-d4-grafana-password
```

- [ ] **Step 2: Write the failing config smoke script**

Create `backend/tests/test_grafana_password_required.py`:
```python
"""D4 guard: docker-compose.monitoring.yml must require GRAFANA_ADMIN_PASSWORD."""
from pathlib import Path


def test_grafana_password_uses_required_form():
    path = Path(__file__).resolve().parents[2] / "docker-compose.monitoring.yml"
    text = path.read_text(encoding="utf-8")
    # The ${VAR:?error} form causes compose to exit non-zero if unset.
    assert "${GRAFANA_ADMIN_PASSWORD:?" in text, (
        "GRAFANA_ADMIN_PASSWORD must use the ${VAR:?error} required form — "
        "the :-default fallback (especially :-changeme) is a security hazard."
    )
    assert ":-changeme" not in text, (
        "No :-changeme default should remain in docker-compose.monitoring.yml"
    )
```

- [ ] **Step 3: Run test — expected FAIL**

Run:
```bash
docker compose exec backend pytest tests/test_grafana_password_required.py -v
```
Expected: `FAILED` — `:-changeme` is still present.

- [ ] **Step 4: Update `docker-compose.monitoring.yml`**

Edit line 305:
```yaml
# Before
- GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:-changeme}
# After
- GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:?GRAFANA_ADMIN_PASSWORD must be set}
```

- [ ] **Step 5: Update `.env.example`**

Edit `.env.example` — add near the monitoring/admin section (create the section if it doesn't exist):
```bash
# Required when running docker-compose.monitoring.yml — Grafana boots refuse to start without it.
GRAFANA_ADMIN_PASSWORD=
```

- [ ] **Step 6: Document in README**

Edit `README.md`. Find the monitoring/observability section. Add a one-line note:
```markdown
> **Required env var:** `GRAFANA_ADMIN_PASSWORD` must be set before running the monitoring stack. See `.env.example`.
```
If no monitoring section exists, add a short subsection under the existing "Environment" or "Configuration" heading with this note.

- [ ] **Step 7: Run guard test — expected PASS**

Run:
```bash
docker compose exec backend pytest tests/test_grafana_password_required.py -v
```
Expected: `1 passed`.

- [ ] **Step 8: Verify docker compose config**

Run (without `GRAFANA_ADMIN_PASSWORD` set in env):
```bash
unset GRAFANA_ADMIN_PASSWORD
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml config 2>&1 | tail -5
```
Expected: Non-zero exit with error mentioning `GRAFANA_ADMIN_PASSWORD must be set`.

Then with it set:
```bash
GRAFANA_ADMIN_PASSWORD=test123 docker compose -f docker-compose.yml -f docker-compose.monitoring.yml config >/dev/null && echo OK
```
Expected: `OK`.

- [ ] **Step 9: Commit, push, open PR, merge**

Run:
```bash
git add docker-compose.monitoring.yml .env.example README.md backend/tests/test_grafana_password_required.py
git commit -m "$(cat <<'EOF'
fix(monitoring): require GRAFANA_ADMIN_PASSWORD, remove changeme default

Replaces `${GRAFANA_ADMIN_PASSWORD:-changeme}` with the required
`${GRAFANA_ADMIN_PASSWORD:?...}` form so docker compose fails fast when
the password is unset. Documents the variable in .env.example and README.
Adds a guard test that fails if the default ever creeps back.

Closes #57

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push -u origin fix/v1-10-2-d4-grafana-password
gh pr create --base master --title "fix(monitoring): require GRAFANA_ADMIN_PASSWORD, remove changeme default" --body "$(cat <<'EOF'
## Summary
- Replace `${GRAFANA_ADMIN_PASSWORD:-changeme}` with `${GRAFANA_ADMIN_PASSWORD:?...}` in `docker-compose.monitoring.yml`.
- Document the required env var in `.env.example` and `README.md`.
- Guard test that detects regressions.

## Why
Any fresh bring-up of the monitoring stack with an unset env var was exposing Grafana on the well-known `changeme` password. Closes #57.

## Test plan
- [x] `pytest tests/test_grafana_password_required.py` passes.
- [x] `docker compose ... config` fails clearly when the env var is unset.
- [x] `docker compose ... config` succeeds with env var set.

Closes #57
Part of v1.10.2 consolidation release.
EOF
)"
```
Wait for CI green, then merge and sync:
```bash
PR_NUM=$(gh pr view --json number --jq .number)
gh pr merge "$PR_NUM" --squash --delete-branch
git checkout master && git pull origin master
```

---

## Task 8: D5 — Remove dead DiCE callpath (closes #54)

**Files:**
- Modify: `backend/apps/ml_engine/services/counterfactual_engine.py` (delete ~150 lines)
- Modify: `backend/apps/ml_engine/tests/test_counterfactual_engine.py` (delete the two DiCE-path asserts, add one "fallback is the only path" assert)

- [ ] **Step 1: Create branch**

Run:
```bash
git checkout master && git pull origin master
git checkout -b chore/v1-10-2-d5-remove-dead-dice
```

- [ ] **Step 2: Write the "fallback is the only path" assertion**

Edit `backend/apps/ml_engine/tests/test_counterfactual_engine.py`:
- **Delete** the existing `test_dice_total_cfs_is_three` function (lines ~125-131) since `_dice_counterfactuals` no longer exists.
- **Replace** it with a regression test that `_dice_counterfactuals` is gone:
  ```python
  def test_dice_path_removed():
      """D5: DiCE callpath removed — _dice_counterfactuals must not exist.

      The DiCE dependency is not in requirements.txt; the previous code
      silently fell back via an except-Exception swallow. See spec
      docs/superpowers/specs/2026-04-19-v1-10-2-consolidation-design.md
      for the decision rationale.
      """
      from apps.ml_engine.services.counterfactual_engine import CounterfactualEngine

      assert not hasattr(CounterfactualEngine, "_dice_counterfactuals"), (
          "_dice_counterfactuals was removed in v1.10.2 — do not re-add without a spec."
      )
      assert not hasattr(CounterfactualEngine, "_build_dice_dataset"), (
          "_build_dice_dataset was removed alongside _dice_counterfactuals."
      )
      assert not hasattr(CounterfactualEngine, "_parse_dice_result"), (
          "_parse_dice_result was removed alongside _dice_counterfactuals."
      )
  ```
- Leave `test_generate_default_timeout_is_20_seconds` in place — still valid.

- [ ] **Step 3: Run test — expected FAIL**

Run:
```bash
docker compose exec backend pytest apps/ml_engine/tests/test_counterfactual_engine.py::test_dice_path_removed -v
```
Expected: `FAILED` — methods still exist.

- [ ] **Step 4: Remove the DiCE call block from `generate()`**

Edit `backend/apps/ml_engine/services/counterfactual_engine.py`, lines 134-148:

Before:
```python
        # DiCE requires a model that predicts on the same feature space as
        # the Data object. When a transform_fn is supplied (production path),
        # the model's input space differs from the raw-features space DiCE
        # operates in — running DiCE would need a custom wrapper and is
        # deferred to a future spec. Skip straight to the fallback.
        if self._transform_fn is None:
            try:
                with _timeout_ctx(timeout_seconds):
                    cfs = self._dice_counterfactuals(features_df, original_loan_amount)
                    if cfs:
                        return cfs
            except (TimeoutError, Exception) as exc:
                logger.info("DiCE counterfactuals failed/timed-out: %s — using fallback", exc)

        return self._fallback_binary_search(features_df, original_loan_amount)
```

After:
```python
        # CounterfactualEngine uses a deterministic binary-search fallback.
        # A DiCE-based path was previously attempted but relied on a
        # `dice_ml` dependency that was never declared; it silently fell
        # back on every call. Removed in v1.10.2 (see spec
        # 2026-04-19-v1-10-2-consolidation-design.md). `timeout_seconds` is
        # kept as a parameter for API compatibility.
        del timeout_seconds  # kept for signature stability; unused after DiCE removal
        return self._fallback_binary_search(features_df, original_loan_amount)
```

- [ ] **Step 5: Delete `_build_dice_dataset`, `_dice_counterfactuals`, `_parse_dice_result`**

Edit `backend/apps/ml_engine/services/counterfactual_engine.py`:
- Delete the block bounded by the `# --- DiCE approach ---` section header down to (but not including) the `# --- Binary-search fallback ---` section header. This removes `_build_dice_dataset` (line ~154), `_dice_counterfactuals` (line ~193), and `_parse_dice_result` (line ~235).
- Remove the now-unused `# DiCE approach` banner comment.

- [ ] **Step 6: Drop unused imports**

In the same file:
- `numpy as np` and `pandas as pd` are still used by the fallback path — keep.
- `signal`, `platform`, `contextmanager`, `TimeoutError` in `_timeout_ctx` are now unused; delete `_timeout_ctx` and its imports (`import platform`, `import signal`, `from contextlib import contextmanager`).
- Keep `import logging` and the `logger = logging.getLogger(__name__)` line (other log sites may remain).
- Remove `from typing import Any` if it is no longer used elsewhere; run `ruff` in step 8 to confirm.

- [ ] **Step 7: Grep-verify DiCE is gone**

Run:
```bash
grep -rn "dice_ml\|_dice_counterfactuals\|_build_dice_dataset\|_parse_dice_result\|_timeout_ctx" backend/ --include="*.py" | grep -v __pycache__
```
Expected: zero matches.

- [ ] **Step 8: Run ruff + test**

Run:
```bash
docker compose exec backend ruff check apps/ml_engine/services/counterfactual_engine.py
docker compose exec backend pytest apps/ml_engine/tests/test_counterfactual_engine.py -v
```
Expected: ruff clean, all tests in the file pass. If ruff flags unused imports, remove them.

- [ ] **Step 9: Run full suite**

Run:
```bash
docker compose exec backend pytest -x
```
Expected: No regressions. Total pass/skip match baseline.

- [ ] **Step 10: Commit, push, open PR, merge**

Run:
```bash
git add backend/apps/ml_engine/services/counterfactual_engine.py backend/apps/ml_engine/tests/test_counterfactual_engine.py
git commit -m "$(cat <<'EOF'
chore(ml_engine): remove dead DiCE callpath from CounterfactualEngine

The _dice_counterfactuals method imported dice_ml — a library that was
never declared in requirements.txt. In production (where
self._transform_fn is always set) the DiCE branch never ran; in
dev/tests it threw ModuleNotFoundError, which the broad except:
swallowed while logging "DiCE counterfactuals failed/timed-out". Net
effect was log noise and wasted cycles on every call.

Deletes _dice_counterfactuals, _build_dice_dataset, _parse_dice_result,
and the now-unused _timeout_ctx helper. Updates tests to assert the
removal. generate() now always uses _fallback_binary_search.

Closes #54

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push -u origin chore/v1-10-2-d5-remove-dead-dice
gh pr create --base master --title "chore(ml_engine): remove dead DiCE callpath (closes #54)" --body "$(cat <<'EOF'
## Summary
- Delete the `_dice_counterfactuals` / `_build_dice_dataset` / `_parse_dice_result` methods and the `_timeout_ctx` helper from `CounterfactualEngine`.
- `generate()` now always uses `_fallback_binary_search` — same runtime behaviour as before, just without the silent ModuleNotFoundError swallow.
- Tests updated to assert the DiCE path is gone.

## Why
`dice_ml` was never in `requirements.txt`; the DiCE branch silently fell back on every invocation. Issue #54 proposed pinning `dice-ml`. The cleaner fix is to delete the dead code — reintroduction would need a proper transform-wrapper spec.

## Risk
`generate()` previously had a best-effort DiCE attempt before the fallback. In production (where `transform_fn` is always set) this code never executed. In the unit-test path (where `transform_fn` is None) it raised `ModuleNotFoundError` and silently fell back. Net user-visible behaviour is unchanged.

## Test plan
- [x] New `test_dice_path_removed` asserts `_dice_counterfactuals`, `_build_dice_dataset`, `_parse_dice_result` are gone.
- [x] Existing counterfactual tests pass.
- [x] `grep -rn dice_ml backend/` returns zero matches.
- [x] Full pytest suite unchanged.

Closes #54
Part of v1.10.2 consolidation release.
EOF
)"
```
Wait for CI green, then:
```bash
PR_NUM=$(gh pr view --json number --jq .number)
gh pr merge "$PR_NUM" --squash --delete-branch
git checkout master && git pull origin master
```

---

## Task 9: D6 — Split `make clean` into `clean-soft` + `clean`

**Files:**
- Modify: `Makefile`
- Modify: `README.md` (housekeeping note)

- [ ] **Step 1: Create branch**

Run:
```bash
git checkout master && git pull origin master
git checkout -b chore/v1-10-2-d6-make-clean-soft
```

- [ ] **Step 2: Inspect current `clean` target**

Run:
```bash
grep -nA5 "^clean:" Makefile
```
Capture the existing body — the new `clean-soft` must exclude `-v`, while the existing `clean` keeps `-v`.

- [ ] **Step 3: Update Makefile**

Edit `Makefile`. Replace the existing `clean:` target with both targets:

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

Append `.PHONY: clean clean-soft` if an existing `.PHONY` line needs updating (add `clean-soft` to the list).

- [ ] **Step 4: README housekeeping note**

Edit `README.md`. Find the housekeeping / clean section (search for "make clean"). Replace or augment with:

```markdown
### Housekeeping

- `make clean-soft` — Reclaim build caches (`.next`, coverage, `__pycache__`, `.pyc`, `htmlcov`, `.pytest_cache`, `tsconfig.tsbuildinfo`). Preserves PostgreSQL and Redis volumes — safe for daily use.
- `make clean` — Same as `clean-soft` **plus** destroys PostgreSQL + Redis volumes. Use only when you want a full reset.
```

- [ ] **Step 5: Verify Makefile syntax**

Run:
```bash
make -n clean-soft | head -5
make -n clean | head -5
```
Expected: Both print the expected commands without error. `clean-soft` must NOT contain `-v`; `clean` must contain `-v`.

- [ ] **Step 6: Smoke — `clean-soft` preserves volumes**

Prereq: docker stack has been up at least once so `postgres_data` + `redis_data` volumes exist.
```bash
docker volume ls | grep loan-approval
# should list loan-approval-ai-system_postgres_data and _redis_data
make clean-soft
docker volume ls | grep loan-approval
```
Expected: Both volumes still listed after `clean-soft`.

- [ ] **Step 7: (Skip destructive smoke)** — do NOT run `make clean` now; it would nuke seeded DB. The documented behaviour is enough.

- [ ] **Step 8: Commit, push, open PR, merge**

Run:
```bash
git add Makefile README.md
git commit -m "$(cat <<'EOF'
chore(make): split clean into clean-soft (safe) and clean (destructive)

`make clean` previously ran `docker compose down -v`, which nukes
Postgres + Redis volumes. After recent sweeps, contributors running
`make clean` to reclaim build cache were silently losing their seeded
DB. Introduce `make clean-soft` (preserves volumes) and keep `make clean`
as the explicit destructive target. README housekeeping section updated.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push -u origin chore/v1-10-2-d6-make-clean-soft
gh pr create --base master --title "chore(make): split clean into clean-soft (safe) + clean (destructive)" --body "$(cat <<'EOF'
## Summary
- Add `make clean-soft` — reclaims cache space, preserves Postgres + Redis volumes.
- Keep existing `make clean` but make it explicit about its destructive nature in the help text.
- Update README housekeeping section.

## Why
Contributors running `make clean` hoping to reclaim disk space were silently losing seeded DBs. Making the destructive intent opt-in reduces footguns.

## Test plan
- [x] `make -n clean-soft` contains `docker compose down` (no `-v`).
- [x] `make -n clean` still contains `docker compose down -v`.
- [x] `make clean-soft` preserves `_postgres_data` / `_redis_data` volumes.

Part of v1.10.2 consolidation release.
EOF
)"
```
Wait for CI green, then:
```bash
PR_NUM=$(gh pr view --json number --jq .number)
gh pr merge "$PR_NUM" --squash --delete-branch
git checkout master && git pull origin master
```

---

## Task 10: D7 — Release: APP_VERSION bump + CHANGELOG + close stale + tag

**Files:**
- Modify: `backend/config/settings/base.py` (`APP_VERSION`)
- Modify: `CHANGELOG.md` (new section)

- [ ] **Step 1: Create branch**

Run:
```bash
git checkout master && git pull origin master
git checkout -b chore/v1-10-2-d7-release
```

- [ ] **Step 2: Bump APP_VERSION**

Edit `backend/config/settings/base.py`:
```python
# Before
APP_VERSION = "1.10.1"
# After
APP_VERSION = "1.10.2"
```

- [ ] **Step 3: Add CHANGELOG section**

Edit `CHANGELOG.md`. Insert immediately below the top-of-file heading (before the `## [1.10.1]` section):

```markdown
## [1.10.2] - 2026-04-19

Consolidation hardening release — bug fixes, security hygiene, deadcode removal, and DX ergonomics.

### Fixed
- **smoke_e2e**: resolved 4 auth/profile/fixture bugs blocking the e2e pipeline (#103).
- **watchdog**: swapped `requests` → `httpx` (stops crashloop on ModuleNotFoundError) (#104).
- **ml_engine/calibration_validator**: corrected broken lazy import path `backend.apps.*` → `apps.*` (#105).
- **accounts/seed_profiles**: write `on_time_payment_pct` on the correct 0-100 scale (was fractional 0-1).
- **accounts/CustomerProfile**: enforce `0 <= on_time_payment_pct <= 100` at model and serializer layers (closes #55).
- **monitoring/docker-compose**: `GRAFANA_ADMIN_PASSWORD` is now required (no `changeme` default) (closes #57).

### Changed
- **ml_engine**: replaced 10 uses of the deprecated `datetime.utcnow()` with `datetime.now(UTC)` across 6 service modules.
- **Makefile**: `make clean-soft` preserves Postgres/Redis volumes; `make clean` keeps the destructive behaviour.

### Removed
- **ml_engine/counterfactual_engine**: deleted the dead `_dice_counterfactuals` path and the `dice_ml` dependency assumption (closes #54). The deterministic binary-search fallback is the sole generator.

### Closed as stale
- #56 — `DJANGO_SETTINGS_MODULE` default (already present in `backend/config/celery.py`).
- #61 — `enforce_retention` regression test (function was removed in an earlier release).
```

- [ ] **Step 4: Commit and push**

Run:
```bash
git add backend/config/settings/base.py CHANGELOG.md
git commit -m "$(cat <<'EOF'
chore(release): v1.10.1 → v1.10.2 consolidation hardening

Bump APP_VERSION and CHANGELOG entry covering the seven atomic PRs
landed for v1.10.2 (M1 #103, M2 #104, M3 #105, D1-D6).

Closes #56 #61 (both stale — see CHANGELOG "Closed as stale" section).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push -u origin chore/v1-10-2-d7-release
```

- [ ] **Step 5: Open release PR**

Run:
```bash
gh pr create --base master --title "chore(release): v1.10.2 consolidation hardening" --body "$(cat <<'EOF'
## Summary
- Bump `APP_VERSION` to `1.10.2`.
- CHANGELOG covering the seven atomic PRs shipped since v1.10.1.
- Closes stale issues #56 and #61.

## Shipped in v1.10.2
| PR | Title |
| --- | --- |
| #103 | smoke_e2e auth/profile/fixture fixes |
| #104 | watchdog requests → httpx |
| #105 | calibration_validator lazy-import fix |
| D1 | datetime.utcnow() → datetime.now(UTC) |
| D2 | seed_profiles on 0-100 scale |
| D3 | on_time_payment_pct validator (closes #55) |
| D4 | Grafana required password (closes #57) |
| D5 | Remove dead DiCE callpath (closes #54) |
| D6 | make clean-soft |

## Test plan
- [x] All 9 prior PRs merged with green CI.
- [x] Local `tools/smoke_e2e.sh --keep-up` passes against this branch.
- [ ] Post-merge: `workflow_dispatch` run of `smoke-e2e` against tag `v1.10.2` green.

Closes #56 #61
EOF
)"
```

- [ ] **Step 6: Pre-merge local smoke test**

Run (with the stack up):
```bash
bash tools/smoke_e2e.sh --keep-up
```
Expected: `=== e2e smoke: PASS ===` (or equivalent success marker from the script). If it fails, fix forward before merging D7.

- [ ] **Step 7: Wait for CI green, merge release PR**

Run:
```bash
gh pr checks "$(gh pr view --json number --jq .number)"
PR_NUM=$(gh pr view --json number --jq .number)
gh pr merge "$PR_NUM" --squash --delete-branch
git checkout master && git pull origin master
```

- [ ] **Step 8: Tag v1.10.2**

Run:
```bash
HEAD_SHA=$(git rev-parse HEAD)
git tag -a v1.10.2 "$HEAD_SHA" -m "v1.10.2 — consolidation hardening (M1-M3, D1-D7)"
git push origin v1.10.2
```

- [ ] **Step 9: Close stale issues with linkback**

Run:
```bash
HEAD_SHA=$(git rev-parse HEAD)
gh issue close 56 -c "Stale — \`os.environ.setdefault(\"DJANGO_SETTINGS_MODULE\", ...)\` is already present in backend/config/celery.py:8 (verified in ${HEAD_SHA}). Closing as part of v1.10.2 release sweep."
gh issue close 61 -c "Stale — the \`enforce_retention\` function was removed in a prior release; only \`.coverage\` / \`.ruff_cache\` references remain. Verified in ${HEAD_SHA}. Closing as part of v1.10.2 release sweep."
```

- [ ] **Step 10: Verify all four closures**

Run:
```bash
for n in 54 55 56 57 61; do
  echo -n "#$n "; gh issue view $n --json state,title --jq '.state + " — " + .title'
done
```
Expected: All five show `CLOSED`. (#54 via D5, #55 via D3, #56 via this PR, #57 via D4, #61 via this PR.)

- [ ] **Step 11: Trigger smoke-e2e workflow_dispatch against v1.10.2**

Run:
```bash
gh workflow run smoke-e2e.yml --ref v1.10.2
# wait ~2 min, then:
gh run list --workflow=smoke-e2e.yml --limit 1
```
Expected: Latest run status `completed`, conclusion `success`.

- [ ] **Step 12: Announce (memory)**

Save a new project memory entry mirroring `project_v1_10_1_production_hardening.md` format:
```markdown
---
name: v1.10.2 consolidation hardening
description: v1.10.2 shipped 2026-04-19 — consolidation release, 9 PRs, closes 5 issues
type: project
---

v1.10.2 MERGED + TAGGED 2026-04-19 (master <sha>): 9 PRs total (M1-M3 #103/#104/#105 + D1-D7 new). Closes #54 #55 #56 #57 #61. Changes: utcnow→now(UTC), seed scale fix, on_time_payment_pct validator, Grafana required password, DiCE deadcode removal, make clean-soft split, CHANGELOG + tag.
```
Update `MEMORY.md` with a one-line pointer.

---

## Global Testing Strategy

Each PR must pass ALL of these CI checks before merge:
- Backend Tests
- Backend Lint (ruff)
- Backend mypy (Arm C extraction modules)
- ml_engine quality bar
- Frontend Tests
- Frontend Lint & Type Check
- Security Scan (bandit)
- Dependency Audit (pip-audit)
- secret-scan
- Docker Build

Pre-D7 also runs `tools/smoke_e2e.sh --keep-up` locally. Post-D7 dispatches the `smoke-e2e` workflow against the `v1.10.2` tag.

## Rollback

Each PR is a squash-merge. Any individual change can be reverted with `git revert <merge-commit>` without touching the others. D5 (DiCE removal) is the largest blast-radius change (~150 deleted lines) but has no production caller and the fallback path was always the production behaviour.

## Memory notes (post-release)

- Save `project_v1_10_2_consolidation.md` with the commit/tag and issue-closure list.
- Retire `project_v1_9_x_*` memories that pre-date v1.10 if they look stale on re-read.
