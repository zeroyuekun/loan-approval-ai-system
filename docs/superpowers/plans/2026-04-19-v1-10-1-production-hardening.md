# v1.10.1 Production Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship v1.10.1 — a six-PR production-hardening pass that strips aspirational hosted-demo scaffolding, reclaims ≥ 1.3 GB of ephemeral disk, prunes 130+ stale model artifacts, removes dead code surfaced by automated tooling, tightens lint/type/security gates, and proves the pipeline still works end-to-end.

**Architecture:** Six atomic PRs merged in spec-recommended order (D1 → D6). Each PR branches from `master`, ships one deliverable, and merges with `--delete-branch` before the next begins. Version bump and tag land together in D6.

**Tech Stack:** Django 5 + DRF + Celery, Next.js 15 + Vite/Vitest, XGBoost, Docker Compose, GitHub Actions, pre-commit, ruff, vulture, mypy, eslint, bandit, pip-audit, npm audit.

**Spec:** `docs/superpowers/specs/2026-04-19-v1-10-1-production-hardening-design.md`

**Base commit:** `master` at `5807fae` (Arm C Phase 1 predictor split merge).

**Environment notes:**
- Platform Windows + Git Bash; use forward slashes in all paths; use Unix shell syntax in commands.
- Docker Compose must be running for seed/smoke tasks. Use `docker compose` (not `docker-compose`).
- All file paths below are absolute-from-repo-root; run commands from repo root unless stated otherwise.

---

## File Map

### New files (8)

| Path | Purpose |
|---|---|
| `backend/apps/ml_engine/management/commands/prune_model_artifacts.py` | Management command: delete orphan `.joblib` files from `backend/ml_models/` with safety whitelist + dry-run |
| `backend/apps/ml_engine/tests/test_prune_model_artifacts.py` | Unit test for prune command covering whitelist, dry-run, active-model protection |
| `backend/.vulture-whitelist.py` | Whitelist of symbols vulture flags as unused but are actually loaded via Django/Celery reflection |
| `tools/smoke_e2e.sh` | End-to-end smoke script: up → register → apply → predict → email → decision → write result JSON |
| `tools/smoke_fixtures/smoke_applicant.json` | Deterministic applicant payload for the smoke script |
| `.github/workflows/smoke-e2e.yml` | GitHub Actions workflow running smoke script on workflow_dispatch |
| `docs/superpowers/specs/2026-04-19-v1-10-1-production-hardening-design.md` | (Already created) Spec this plan implements |
| `docs/superpowers/plans/2026-04-19-v1-10-1-production-hardening.md` | (This file) |

### Modified files

| Path | Change |
|---|---|
| `Makefile` | Extend `clean`, add `clean-deep`, `typecheck`, `security`, `verify`, `deadcode` targets |
| `workflows/deployment.md` | Drop § "Cloud Deployment Options" (lines 120–154), add § "Scope note" |
| `README.md` | Add `make clean` reference, add § "Verifying the build", excise any lingering hosted-demo language |
| `.gitignore` | Audit pass; add missing entries (`frontend/.next/diagnostics/`, any Sentry source-map artifacts) |
| `.pre-commit-config.yaml` | Add mypy backend hook, frontend eslint + tsc hooks |
| `.github/workflows/lint.yml` | Add mypy + bandit jobs |
| `.github/workflows/security.yml` | Add `pip-audit` + `npm audit` jobs if not present |
| `backend/config/settings/base.py` | `APP_VERSION = "1.10.1"` (in D6 only) |
| `backend/docs/RUNBOOK.md` | Document `prune_model_artifacts` invocation |
| `backend/requirements-dev.txt` | Add `vulture>=2.13`, `mypy>=1.13` |
| `docs/engineering-journal.md`, `docs/interview-talking-points.md`, `docs/DESIGN_JOURNEY.md` | Excise hosted-demo references |
| Backend + frontend source files surfaced by ruff/vulture/ts-prune | Per-PR scope, listed at execution time |

### Deleted (disk only — gitignored)

- ~130 stale `backend/ml_models/*.joblib` files from training experiments.
- 22 five-byte placeholder `.joblib` files — only after verifying none are referenced by tests.

### Deleted (git branches — confirmation required per branch)

Enumerated in Task D4.5.

---

## Phase D1 — Strip hosted-demo scaffolding

### Task D1.1 — Branch setup and hosted-demo audit

**Files:**
- Read-only: `workflows/deployment.md`, `README.md`, `docs/engineering-journal.md`, `docs/interview-talking-points.md`, `docs/DESIGN_JOURNEY.md`

- [ ] **Step 1: Sync master and branch**

```bash
git checkout master
git pull origin master
git checkout -b chore/v1-10-1-d1-demo-strip
```

Expected: branch `chore/v1-10-1-d1-demo-strip` at master's head (should be `5807fae` or newer).

- [ ] **Step 2: Collect every hosted-demo reference into a scratch file**

```bash
grep -rInE "hosted demo|demo url|live demo|fly\.io|render\.com|hetzner|deploy.*demo" \
  docs/ workflows/ README.md 2>/dev/null > .tmp/d1-audit.txt
cat .tmp/d1-audit.txt
```

Expected output includes at least these hits:
- `workflows/deployment.md:122` — "A hosted demo URL is the single highest-impact portfolio polish item"
- `workflows/deployment.md:126-130` — Fly.io / Render / Hetzner comparison table
- `workflows/deployment.md:152` — "Non-demo considerations (out of scope for portfolio)"
- Possibly: `docs/engineering-journal.md`, `docs/interview-talking-points.md` — references to "hosted demo" as polish item.

Keep `.tmp/d1-audit.txt` as the working checklist for Steps 3–5. It is gitignored.

### Task D1.2 — Strip `workflows/deployment.md` cloud-deployment section

**Files:**
- Modify: `workflows/deployment.md` (lines 120–154)

- [ ] **Step 1: Open the file and locate § Cloud Deployment Options**

Read `workflows/deployment.md` and confirm line numbers of § "Cloud Deployment Options" (≈ line 120) and the following § "Non-demo considerations" (≈ line 152). Lines may have shifted if the file was edited; re-anchor on heading text rather than line numbers.

- [ ] **Step 2: Replace the cloud-deployment section with a local-scope note**

Delete everything from the "## Cloud Deployment Options" heading through the end of the "### Non-demo considerations" paragraph. Replace with:

```markdown
## Scope: local-only portfolio project

This project is designed to run locally via Docker Compose. There is no hosted demo, and no cloud-deployment configuration is committed. That is a deliberate scoping choice — portfolio reviewers are expected to clone, `make dev`, and walk through the dashboards on `localhost`.

Operational procedures for a running local instance (rotating secrets, recovering from a stuck Celery queue, database backup, upgrading the model) live in `backend/docs/RUNBOOK.md`. Security and compliance baselines live in `backend/docs/SECURITY.md`.

If you need a cloud deployment of your own, the Docker Compose topology is portable to any container host (Fly.io, Render, Hetzner, Kubernetes, bare-metal) — but no specific host config is supported here.
```

- [ ] **Step 3: Verify no orphan tables / bullets / badges remain**

```bash
grep -nE "Fly\.io|Render|Hetzner|flyctl|render\.yaml|fly\.toml" workflows/deployment.md
```

Expected: no matches.

- [ ] **Step 4: Commit**

```bash
git add workflows/deployment.md
git commit -m "docs(deployment): drop hosted-demo scaffolding, add local-scope note"
```

### Task D1.3 — Sweep README + other docs

**Files:**
- Modify: `README.md`, `docs/engineering-journal.md`, `docs/interview-talking-points.md`, `docs/DESIGN_JOURNEY.md`

- [ ] **Step 1: Re-run the audit to see remaining hits**

```bash
grep -rInE "hosted demo|demo url|live demo|fly\.io|render\.com|hetzner|deploy.*demo" \
  docs/ workflows/ README.md
```

Expected: `workflows/deployment.md` is now clean. Remaining hits (if any) live in the other four files.

- [ ] **Step 2: Fix each remaining hit**

For each match, open the file, read the surrounding paragraph, and decide:
- If the sentence *promises* a hosted demo (e.g., "a demo is coming to fly.io") → delete the sentence.
- If the sentence *mentions hosted demo as a polish item in a journal entry* (e.g., "A11: shipping hosted demo to fly.io") → rewrite the entry to remove the promise, keep the journal narrative: "A11: scoped to local-only portfolio project; cloud-deployment deferred indefinitely."
- If the word "demo" is used in a non-hosted sense (e.g., "demo video", "the demo on localhost") → leave it.

- [ ] **Step 3: Verify audit returns zero matches**

```bash
grep -rInE "hosted demo|demo url|live demo|fly\.io|render\.com|hetzner|deploy.*demo" \
  docs/ workflows/ README.md
```

Expected: zero output.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/engineering-journal.md docs/interview-talking-points.md docs/DESIGN_JOURNEY.md
git commit -m "docs: excise remaining hosted-demo references across journals"
```

(Only `git add` files actually modified.)

### Task D1.4 — Delete `chore/demo-and-readme` branch refs

**Files:** none (git operations only)

- [ ] **Step 1: Check whether the branch is merged or contains unmerged work**

```bash
git log master..chore/demo-and-readme --oneline 2>&1 | head -20
git log --oneline origin/chore/demo-and-readme ^master 2>&1 | head -20
```

Expected: zero or a handful of commits. If commits exist and look substantive (not superseded by later master work), pause and flag to the user. If commits are superseded (e.g., README work already on master via v1.9.x / Arm A), proceed.

- [ ] **Step 2: Delete local branch**

```bash
git branch -D chore/demo-and-readme
```

Expected: `Deleted branch chore/demo-and-readme (was <sha>).`

- [ ] **Step 3: Delete remote branch (destructive — confirm with user before running)**

```bash
git push origin --delete chore/demo-and-readme
```

Expected: `- [deleted]         chore/demo-and-readme`.

**Stop and ask user for explicit approval before running Step 3.** This is the one action in D1 that touches shared state.

- [ ] **Step 4: Verify cleanup**

```bash
git branch -a | grep demo-and-readme
```

Expected: zero output.

### Task D1.5 — Open and merge D1 PR

- [ ] **Step 1: Push branch**

```bash
git push -u origin chore/v1-10-1-d1-demo-strip
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --base master --title "chore(v1.10.1 D1): strip hosted-demo scaffolding" --body "$(cat <<'EOF'
## Summary
- Drop `workflows/deployment.md` § "Cloud Deployment Options" — project is local-only portfolio by design.
- Sweep docs for remaining hosted-demo references.
- Delete stale `chore/demo-and-readme` branch.

## Test plan
- [ ] `grep -rEi "hosted demo|demo url|live demo|fly\.io|render\.com|hetzner" docs/ workflows/ README.md` returns zero matches.
- [ ] `workflows/deployment.md` still reads coherently end-to-end.
- [ ] CI green.

## Spec
`docs/superpowers/specs/2026-04-19-v1-10-1-production-hardening-design.md` §D1
EOF
)"
```

- [ ] **Step 3: Wait for CI + merge**

```bash
gh pr checks --watch
gh pr merge --merge --delete-branch
git checkout master && git pull
```

Expected: CI green; PR merged; local on master.

---

## Phase D2 — Ephemeral-artifact discipline + `make clean` upgrade

### Task D2.1 — Branch setup and `.gitignore` audit

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Sync and branch**

```bash
git checkout master && git pull origin master
git checkout -b chore/v1-10-1-d2-clean-target
```

- [ ] **Step 2: Build the frontend to surface any new ephemeral dirs**

```bash
cd frontend && npm run build && cd ..
```

Expected: build succeeds; `frontend/.next/` populated with artifacts including any new subdirs (e.g., `diagnostics/` in Next 15).

- [ ] **Step 3: List ignored files to cross-check `.gitignore` coverage**

```bash
git status --ignored --short 2>&1 | grep -E "^\!\!" | head -50
```

Expected: every line starts with `!!`; inspect for anything that *should* be tracked (shouldn't exist in an ignored list) or anything ephemeral that's *not* ignored yet.

- [ ] **Step 4: Add missing entries to `.gitignore`**

If the Next 15 build produced `frontend/.next/diagnostics/` (check with `ls frontend/.next/`), ensure the parent `.next/` entry already in `.gitignore` covers it (it does). If Sentry source-map bundles leak in (`frontend/sentry-*.bundle.js.map` — unusual, but check), add them.

Expected state: `.gitignore` contains all of these entries; add any missing ones under the existing "# Node" or "# Coverage" sections:

```
# Node
node_modules/
.next/
out/

# Coverage
.coverage
htmlcov/
.pytest_cache/
frontend/coverage/

# Playwright
frontend/playwright-report/
frontend/test-results/

# TypeScript
*.tsbuildinfo
```

If no changes were needed, skip the commit for this step.

- [ ] **Step 5: Commit (if changes)**

```bash
git diff .gitignore
# Only commit if there's output above
git add .gitignore
git commit -m "chore(gitignore): audit pass — cover Next 15 build artifacts"
```

### Task D2.2 — Extend `Makefile` `clean` + add `clean-deep`

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Read current clean target**

The current `clean` target (around line 61) reads:

```makefile
clean:                   ## Remove containers, volumes, and cached files
	docker compose down -v
	find backend -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
```

- [ ] **Step 2: Replace with extended target**

Replace the current `clean` target with:

```makefile
clean:              ## Nuke ephemerals (containers, caches, build output)
	docker compose down -v
	find backend -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find backend -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -not -path "*/node_modules/*" -delete 2>/dev/null || true
	rm -rf frontend/.next frontend/coverage frontend/playwright-report frontend/test-results
	rm -rf backend/htmlcov backend/.coverage backend/.pytest_cache
	rm -f frontend/tsconfig.tsbuildinfo
	@echo "Clean complete. Re-run 'make build' then 'make dev' to restart."

clean-deep:         ## clean + remove node_modules + .venv (forces reinstall)
	$(MAKE) clean
	rm -rf frontend/node_modules backend/.venv
	@echo "Deep-clean complete. Expect re-install before next run."
```

- [ ] **Step 3: Update `.PHONY` line at top of `Makefile`**

Current line 1:

```makefile
.PHONY: dev down build test lint seed train logs health clean
```

Replace with:

```makefile
.PHONY: dev down build test lint seed train logs health clean clean-deep typecheck security verify deadcode
```

(`typecheck`, `security`, `verify`, `deadcode` are reserved for D4 and D5; declared here so the Makefile stays consistent and a single diff covers the helper targets.)

- [ ] **Step 4: Test the `clean` target on a built tree**

Pre-clean size capture:

```bash
du -sh . 2>/dev/null | head -1
```

Run clean:

```bash
make clean
```

Expected: no errors; `frontend/.next`, `frontend/coverage`, `backend/htmlcov` (if any), `tsconfig.tsbuildinfo` removed; `__pycache__` dirs gone.

Post-clean size capture:

```bash
du -sh . 2>/dev/null | head -1
```

Expected: delta ≥ 500 MB (the user's machine had `.next` at 515 MB + coverage + pycache). If delta < 500 MB, re-build frontend first and retry.

- [ ] **Step 5: Test `clean-deep` (optional, destructive to local install)**

Only run this if you're willing to re-run `npm install` and `pip install` afterwards:

```bash
make clean-deep
du -sh . 2>/dev/null | head -1
```

Expected: additional ≥ 700 MB delta (node_modules). Restore with `cd frontend && npm install && cd .. && pip install -r backend/requirements.txt -r backend/requirements-dev.txt`.

**Skip this step if the working-tree state is needed for D3/D4/D5 verification.**

- [ ] **Step 6: Commit**

```bash
git add Makefile
git commit -m "chore(makefile): extend clean target + add clean-deep"
```

### Task D2.3 — README reference to `make clean`

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Locate the "## Testing" section (around line 191)**

- [ ] **Step 2: Add a one-liner after the tests section**

Insert after the Testing section a new section:

```markdown
## Housekeeping

Local development accumulates build artifacts, test caches, and trained model files. To reclaim disk:

```bash
make clean       # ephemerals (containers, .next, coverage, __pycache__, tsbuildinfo)
make clean-deep  # also removes node_modules and backend/.venv (forces reinstall)
```

To prune stale trained-model `.joblib` artifacts from `backend/ml_models/` (after many training iterations):

```bash
docker compose exec backend python manage.py prune_model_artifacts --dry-run  # preview
docker compose exec backend python manage.py prune_model_artifacts            # delete
```
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): document make clean and prune_model_artifacts"
```

### Task D2.4 — Open and merge D2 PR

- [ ] **Step 1: Push branch**

```bash
git push -u origin chore/v1-10-1-d2-clean-target
```

- [ ] **Step 2: Measure delta for the PR body**

Include in the PR body the before/after `du -sh .` numbers from Task D2.2 Step 4.

- [ ] **Step 3: Open PR**

```bash
gh pr create --base master --title "chore(v1.10.1 D2): extended make clean + gitignore audit" --body "$(cat <<'EOF'
## Summary
- Extend `make clean` target to nuke `.next`, coverage, playwright artifacts, pyc, tsbuildinfo.
- Add `make clean-deep` that also removes `node_modules` and `backend/.venv`.
- `.gitignore` audit pass for Next 15 build artifacts.
- README "Housekeeping" section documents new targets.

## Disk impact
- Before: `<before-value>`
- After `make clean`: `<after-value>`
- Delta: `<delta>` (target: ≥ 500 MB on a freshly-built tree)

## Test plan
- [ ] `make clean` runs without errors on a fresh clone after `make build`.
- [ ] `make clean-deep` additionally removes `node_modules` and `.venv`.
- [ ] CI green (no tracked file change affects CI behaviour).

## Spec
`docs/superpowers/specs/2026-04-19-v1-10-1-production-hardening-design.md` §D2
EOF
)"
```

- [ ] **Step 4: Wait + merge**

```bash
gh pr checks --watch
gh pr merge --merge --delete-branch
git checkout master && git pull
```

---

## Phase D3 — `ml_models/` artifact prune + retention policy

### Task D3.1 — Branch setup + failing test

**Files:**
- Create: `backend/apps/ml_engine/tests/test_prune_model_artifacts.py`

- [ ] **Step 1: Sync and branch**

```bash
git checkout master && git pull origin master
git checkout -b chore/v1-10-1-d3-prune-model-artifacts
```

- [ ] **Step 2: Write the failing test**

Create `backend/apps/ml_engine/tests/test_prune_model_artifacts.py` with:

```python
"""Unit tests for the prune_model_artifacts management command.

Covers safety whitelist (active ModelVersion, contract_test, golden_metrics),
dry-run mode, and active-model protection.
"""
from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command

from apps.ml_engine.models import ModelVersion

pytestmark = pytest.mark.django_db


@pytest.fixture
def models_dir(tmp_path, settings):
    """Sandbox ML_MODELS_DIR so the command operates on fresh fixtures."""
    settings.ML_MODELS_DIR = str(tmp_path)
    return tmp_path


def _make_file(path: Path, size: int = 1024) -> Path:
    path.write_bytes(b"\0" * size)
    return path


def test_prune_keeps_active_and_recent_versions(models_dir: Path):
    """Active ModelVersion file + N most-recent inactive per segment are kept."""
    active = _make_file(models_dir / "xgb_active.joblib", 2048)
    keep_1 = _make_file(models_dir / "xgb_keep.joblib", 2048)
    stale_1 = _make_file(models_dir / "xgb_stale_1.joblib", 2048)
    stale_2 = _make_file(models_dir / "xgb_stale_2.joblib", 2048)
    _make_file(models_dir / "contract_test_model.joblib", 5)

    ModelVersion.objects.create(
        file_path=str(active),
        algorithm="xgboost",
        segment="unified",
        is_active=True,
        file_hash="a" * 64,
    )
    ModelVersion.objects.create(
        file_path=str(keep_1),
        algorithm="xgboost",
        segment="unified",
        is_active=False,
        file_hash="b" * 64,
    )
    ModelVersion.objects.create(
        file_path=str(stale_1),
        algorithm="xgboost",
        segment="unified",
        is_active=False,
        file_hash="c" * 64,
    )
    ModelVersion.objects.create(
        file_path=str(stale_2),
        algorithm="xgboost",
        segment="unified",
        is_active=False,
        file_hash="d" * 64,
    )

    out = StringIO()
    call_command("prune_model_artifacts", "--keep", "1", stdout=out)

    assert active.exists(), "active ModelVersion must never be deleted"
    assert keep_1.exists(), "most recent inactive kept for rollback"
    assert not stale_1.exists(), "older inactive pruned"
    assert not stale_2.exists(), "older inactive pruned"
    assert (models_dir / "contract_test_model.joblib").exists(), (
        "contract_test_model.joblib is always whitelisted"
    )


def test_prune_dry_run_deletes_nothing(models_dir: Path):
    """--dry-run reports what would be deleted but touches no files."""
    stale = _make_file(models_dir / "xgb_stale.joblib", 2048)
    ModelVersion.objects.create(
        file_path=str(stale),
        algorithm="xgboost",
        segment="unified",
        is_active=False,
        file_hash="e" * 64,
    )

    out = StringIO()
    call_command("prune_model_artifacts", "--dry-run", stdout=out)

    assert stale.exists(), "dry-run must not delete anything"
    assert "would delete" in out.getvalue().lower()


def test_prune_handles_orphan_files_with_no_modelversion_row(models_dir: Path):
    """A joblib with no ModelVersion row is safe to delete."""
    orphan = _make_file(models_dir / "xgb_orphan.joblib", 2048)

    call_command("prune_model_artifacts")

    assert not orphan.exists(), "orphan files (no DB row) are deleted"


def test_prune_protects_golden_metrics(models_dir: Path):
    """golden_metrics.json is a whitelist entry, not a .joblib, but the command
    must not touch non-.joblib files under any circumstance."""
    (models_dir / "golden_metrics.json").write_text('{"auc": 0.87}')
    _make_file(models_dir / "xgb_stale.joblib", 2048)

    call_command("prune_model_artifacts")

    assert (models_dir / "golden_metrics.json").exists()


def test_prune_reports_bytes_reclaimed(models_dir: Path):
    """Command prints total bytes reclaimed for operator feedback."""
    _make_file(models_dir / "xgb_orphan.joblib", 10_000)

    out = StringIO()
    call_command("prune_model_artifacts", stdout=out)

    output = out.getvalue()
    assert "bytes reclaimed" in output.lower() or "bytes freed" in output.lower()
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
docker compose exec backend pytest apps/ml_engine/tests/test_prune_model_artifacts.py -v
```

Expected: fails with `django.core.management.base.CommandError: Unknown command: 'prune_model_artifacts'`.

### Task D3.2 — Implement the `prune_model_artifacts` command

**Files:**
- Create: `backend/apps/ml_engine/management/commands/prune_model_artifacts.py`

- [ ] **Step 1: Create the command file**

Create `backend/apps/ml_engine/management/commands/prune_model_artifacts.py`:

```python
"""Prune stale `.joblib` artifacts from `backend/ml_models/`.

Keeps: files referenced by any `is_active=True` ModelVersion, the N most
recent inactive versions per segment (default N=1), `contract_test_model.joblib`,
and any non-`.joblib` file (e.g. `golden_metrics.json`).

Deletes: every other `.joblib` file in `ML_MODELS_DIR`, including orphan
files with no ModelVersion row.

Usage:
    python manage.py prune_model_artifacts             # prune
    python manage.py prune_model_artifacts --dry-run   # preview
    python manage.py prune_model_artifacts --keep 2    # retain last 2 inactive per segment
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterable

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.ml_engine.models import ModelVersion

ALWAYS_KEEP = frozenset({"contract_test_model.joblib"})


class Command(BaseCommand):
    help = "Prune stale .joblib artifacts from ML_MODELS_DIR."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview deletions without touching disk.",
        )
        parser.add_argument(
            "--keep",
            type=int,
            default=1,
            help="Number of most-recent inactive ModelVersions per segment to retain (default: 1).",
        )

    def handle(self, *args, **opts):
        models_dir = Path(settings.ML_MODELS_DIR)
        if not models_dir.is_dir():
            raise CommandError(f"ML_MODELS_DIR not found: {models_dir}")

        dry_run: bool = opts["dry_run"]
        keep_n: int = max(0, int(opts["keep"]))

        keep_basenames = self._compute_whitelist(keep_n)
        self.stdout.write(f"Whitelist ({len(keep_basenames)} file(s)):")
        for name in sorted(keep_basenames):
            self.stdout.write(f"  KEEP  {name}")

        reclaimed = 0
        deleted = 0
        for joblib in sorted(models_dir.glob("*.joblib")):
            if joblib.name in keep_basenames:
                continue
            size = joblib.stat().st_size
            reclaimed += size
            deleted += 1
            verb = "would delete" if dry_run else "deleting"
            self.stdout.write(f"  {verb}  {joblib.name} ({size} bytes)")
            if not dry_run:
                joblib.unlink()

        mode = "(dry-run)" if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"Done {mode}: {deleted} file(s); {reclaimed} bytes reclaimed."
            )
        )

    def _compute_whitelist(self, keep_n: int) -> set[str]:
        keep: set[str] = set(ALWAYS_KEEP)

        for mv in ModelVersion.objects.filter(is_active=True):
            if mv.file_path:
                keep.add(Path(mv.file_path).name)

        per_segment: dict[str, list[ModelVersion]] = defaultdict(list)
        inactives: Iterable[ModelVersion] = (
            ModelVersion.objects.filter(is_active=False)
            .exclude(file_path="")
            .order_by("-created_at")
        )
        for mv in inactives:
            per_segment[getattr(mv, "segment", "unified")].append(mv)

        for segment, versions in per_segment.items():
            for mv in versions[:keep_n]:
                keep.add(Path(mv.file_path).name)

        return keep
```

- [ ] **Step 2: Run tests to confirm they pass**

```bash
docker compose exec backend pytest apps/ml_engine/tests/test_prune_model_artifacts.py -v
```

Expected: 5/5 pass.

- [ ] **Step 3: Run full ML-engine test suite to confirm no regressions**

```bash
docker compose exec backend pytest apps/ml_engine/ -v --tb=short
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add backend/apps/ml_engine/management/commands/prune_model_artifacts.py \
        backend/apps/ml_engine/tests/test_prune_model_artifacts.py
git commit -m "feat(ml): prune_model_artifacts command + retention whitelist"
```

### Task D3.3 — Audit placeholder joblibs + dry-run against real tree

**Files:** none (investigation only)

- [ ] **Step 1: List all joblibs in ml_models with sizes**

```bash
ls -la backend/ml_models/*.joblib | awk '{print $5, $9}' | sort -n
```

Expected: ~140 files. Many in the 5-byte range (placeholder fixtures); the rest are legitimate training artifacts 100KB–30MB.

- [ ] **Step 2: Search for references to 5-byte placeholder basenames**

```bash
for f in $(ls backend/ml_models/*.joblib | xargs -n1 basename); do
    size=$(stat -c '%s' "backend/ml_models/$f" 2>/dev/null || stat -f '%z' "backend/ml_models/$f")
    if [ "$size" -le 10 ]; then
        count=$(grep -rn "$f" backend/ 2>/dev/null | grep -v "^backend/ml_models/" | wc -l)
        echo "$f  size=$size  refs=$count"
    fi
done
```

Expected output shape:
```
contract_test_model.joblib  size=5  refs=<N>   # keep, whitelisted
test_active_v1.joblib       size=5  refs=0     # safe to delete
test_chall_v1.joblib        size=5  refs=0     # safe to delete
...
```

For any placeholder with `refs=0`, confirm it's not loaded via dynamic string concatenation (grep for `_v1.joblib`, `_v2.joblib` separately). If still zero references, the file is safe to delete. Record the list.

- [ ] **Step 3: Dry-run prune against real tree**

```bash
docker compose exec backend python manage.py prune_model_artifacts --dry-run
```

Expected: command prints the whitelist (1 active model + N recent inactive + `contract_test_model.joblib`) followed by "would delete" for every other joblib.

Confirm the whitelist contains your current active model basename.

### Task D3.4 — Execute the real prune

**Files:** none (disk operation)

- [ ] **Step 1: Capture pre-prune disk usage**

```bash
du -sh backend/ml_models
```

Expected: ≈152M (or whatever the local tree shows).

- [ ] **Step 2: Execute the prune**

```bash
docker compose exec backend python manage.py prune_model_artifacts
```

Expected: command prints deletion list, ends with "Done: N file(s); M bytes reclaimed."

- [ ] **Step 3: Capture post-prune disk usage**

```bash
du -sh backend/ml_models
```

Expected: ≤ 50M. Record the before/after numbers for the PR body.

- [ ] **Step 4: Manually delete zero-ref placeholder joblibs identified in Task D3.3**

For any `test_*_v*.joblib` with `refs=0` from Task D3.3 Step 2:

```bash
# Replace N with the actual filename list recorded in Task D3.3
rm backend/ml_models/test_active_v1.joblib \
   backend/ml_models/test_chall_v1.joblib
# ... and so on
```

This is a one-shot hygiene pass — the command handles this class of file going forward (orphan file with no ModelVersion row gets pruned automatically, confirmed by test `test_prune_handles_orphan_files_with_no_modelversion_row`). The manual step here catches ones that existed *before* the command existed.

- [ ] **Step 5: Verify ML-engine tests still green after disk changes**

```bash
docker compose exec backend pytest apps/ml_engine/ -v --tb=short
```

Expected: all green. (None of the tests depend on physical presence of pruned joblibs; the command's test creates its own fixtures in `tmp_path`.)

### Task D3.5 — Document in RUNBOOK

**Files:**
- Modify: `backend/docs/RUNBOOK.md`

- [ ] **Step 1: Locate the operational-procedures section in RUNBOOK.md**

Read `backend/docs/RUNBOOK.md` and find a heading like "## Operational Procedures" or "## Housekeeping". If neither exists, add one near the bottom before "## Appendix" (or the final section).

- [ ] **Step 2: Add a subsection for model-artifact pruning**

Append:

```markdown
### Pruning stale model artifacts

After a training batch (>10 models trained), prune `backend/ml_models/` to avoid unbounded disk growth:

```bash
# Preview deletions
docker compose exec backend python manage.py prune_model_artifacts --dry-run

# Execute
docker compose exec backend python manage.py prune_model_artifacts

# Retain 2 most-recent inactive versions per segment instead of 1
docker compose exec backend python manage.py prune_model_artifacts --keep 2
```

The command never deletes:
- The file of any `is_active=True` ModelVersion.
- The N most-recent inactive ModelVersions per segment (default N=1).
- `contract_test_model.joblib` (used by contract tests).
- Any non-`.joblib` file (e.g. `golden_metrics.json`).
```

- [ ] **Step 3: Commit**

```bash
git add backend/docs/RUNBOOK.md
git commit -m "docs(runbook): document prune_model_artifacts command"
```

### Task D3.6 — Open and merge D3 PR

- [ ] **Step 1: Push**

```bash
git push -u origin chore/v1-10-1-d3-prune-model-artifacts
```

- [ ] **Step 2: PR**

```bash
gh pr create --base master --title "chore(v1.10.1 D3): prune_model_artifacts command + retention policy" --body "$(cat <<'EOF'
## Summary
- New management command `python manage.py prune_model_artifacts [--dry-run] [--keep N]`.
- Whitelist: active ModelVersion file + N recent inactive per segment + `contract_test_model.joblib` + non-`.joblib` files.
- Orphan files (no ModelVersion row) are pruned.
- RUNBOOK documents invocation.

## Disk impact (local)
- Before: `<before>` MB
- After: `<after>` MB
- Delta: `<delta>` MB

## Test plan
- [x] Unit test covers whitelist, dry-run, orphan prune, non-joblib protection, bytes-reclaimed reporting.
- [x] Full ml_engine pytest suite green post-prune.
- [x] `--dry-run` output matches real prune target list.

## Spec
`docs/superpowers/specs/2026-04-19-v1-10-1-production-hardening-design.md` §D3
EOF
)"
```

- [ ] **Step 3: Merge**

```bash
gh pr checks --watch
gh pr merge --merge --delete-branch
git checkout master && git pull
```

---

## Phase D4 — Dead-code sweep

### Task D4.1 — Branch setup + add vulture dependency

**Files:**
- Modify: `backend/requirements-dev.txt`, `Makefile`

- [ ] **Step 1: Sync and branch**

```bash
git checkout master && git pull origin master
git checkout -b chore/v1-10-1-d4-dead-code-sweep
```

- [ ] **Step 2: Add vulture to dev requirements**

Edit `backend/requirements-dev.txt` and add after `ruff>=0.8.6`:

```
vulture>=2.13
```

- [ ] **Step 3: Add `deadcode` target to Makefile**

In `Makefile`, immediately after the `lint` target definition, add:

```makefile
deadcode:           ## Report unused code (ruff + vulture)
	cd backend && ruff check --select F401,F811,F841 . || true
	cd backend && vulture apps --min-confidence 80 --ignore-names "_*,test_*" \
		--exclude "*/migrations/*,*/tests/*" \
		.vulture-whitelist.py 2>/dev/null || cd backend && vulture apps --min-confidence 80 --ignore-names "_*,test_*" --exclude "*/migrations/*,*/tests/*"
```

(The fallback form handles the case where `.vulture-whitelist.py` doesn't exist yet — the first invocation will fail cleanly and the command will fall through to the version without the whitelist.)

- [ ] **Step 4: Rebuild backend container to pick up vulture**

```bash
docker compose build backend
docker compose up -d
```

- [ ] **Step 5: Verify vulture is installed**

```bash
docker compose exec backend vulture --version
```

Expected: prints version string.

- [ ] **Step 6: Commit**

```bash
git add backend/requirements-dev.txt Makefile
git commit -m "chore(deps): add vulture + make deadcode target"
```

### Task D4.2 — Ruff F401/F811/F841 sweep

**Files:** backend source files flagged by ruff

- [ ] **Step 1: Run the sweep**

```bash
cd backend && ruff check --select F401,F811,F841 apps/ config/ tests/ 2>&1 | tee ../.tmp/d4-ruff-findings.txt
cd ..
```

Expected: list of findings grouped by file, with rule codes.

- [ ] **Step 2: Autofix the safe ones**

```bash
cd backend && ruff check --select F401,F811,F841 --fix apps/ config/ tests/
cd ..
```

Expected: ruff fixes unused-import cases automatically. F841 (unused local variables) often cannot be autofixed because the value may have side effects — those need manual review.

- [ ] **Step 3: Review remaining findings**

```bash
cd backend && ruff check --select F401,F811,F841 apps/ config/ tests/
cd ..
```

For each remaining finding:
- If the finding is in `backend/apps/*/models.py` and references a typing import (e.g. `from typing import Optional` used only in a type comment), keep it — ruff can be noisy here. Add `# noqa: F401` with a one-line rationale.
- If the finding is in `__init__.py` for a re-export, add `# noqa: F401 — re-exported for <consumer>` with the consumer named.
- If the finding is a genuine unused local, delete the line.

- [ ] **Step 4: Run full backend test suite**

```bash
docker compose exec backend pytest -v --tb=short -x
```

Expected: all green. If anything fails, revert the last autofix and investigate — some test fixtures rely on side-effecting imports.

- [ ] **Step 5: Commit**

```bash
git add backend/
git commit -m "refactor(backend): remove unused imports and locals (ruff F401/F811/F841)"
```

### Task D4.3 — Vulture sweep + whitelist

**Files:**
- Create: `backend/.vulture-whitelist.py`
- Modify: backend source files flagged by vulture

- [ ] **Step 1: Run vulture against apps**

```bash
docker compose exec backend vulture apps --min-confidence 80 --exclude "*/migrations/*,*/tests/*" 2>&1 | tee .tmp/d4-vulture-findings.txt
```

Expected: findings grouped as `path:line: unused <kind> '<name>' (<confidence>% confidence)`.

- [ ] **Step 2: Classify each finding into three buckets**

For each vulture hit, decide:

1. **Genuine dead code** — no consumer anywhere; delete the function/method/variable.
2. **Reflection-loaded** — Django signals, management commands, Celery tasks, DRF serializer `Meta.fields`, admin `@admin.register`. Add to `backend/.vulture-whitelist.py`.
3. **Test-only but vulture missed the reference** — grep for the name in `backend/tests/`; if referenced, add to whitelist with reason "used in tests".

- [ ] **Step 3: Create the vulture whitelist**

Create `backend/.vulture-whitelist.py` with the classifications. Example shape:

```python
"""Vulture false-positive whitelist.

Vulture cannot see symbols loaded via Django/Celery/DRF reflection. Each
entry here is a symbol vulture flagged as unused but is actually invoked by
the framework. Review annually; delete entries when the underlying code moves.
"""

# Django signal receivers — connected via decorators / apps.ready()
from apps.ml_engine.signals import register_mrm_dossier_hook  # noqa: F401
from apps.loans.signals import emit_application_status_change  # noqa: F401

# Celery tasks — autodiscovered from tasks.py at worker startup
from apps.agents.tasks import run_orchestrator  # noqa: F401
from apps.email_engine.tasks import send_email_task  # noqa: F401
from apps.ml_engine.tasks import generate_mrm_dossier_task  # noqa: F401

# Management commands — autodiscovered from management/commands/
from apps.ml_engine.management.commands import prune_model_artifacts  # noqa: F401
# ... add additional Command imports only if vulture complains about them

# DRF serializer fields that appear unused because they're referenced via
# `Meta.fields = "__all__"` or similar. Populate as vulture flags them.
```

Populate with **only** the entries vulture actually flagged. Do not add speculative entries.

- [ ] **Step 4: Delete the genuinely-dead-code entries**

For each "bucket 1" finding from Step 2, open the file, delete the function/method/variable, and re-run the test suite to confirm no regressions.

```bash
docker compose exec backend pytest -v --tb=short -x
```

Expected: all green. If any test fails, the code wasn't actually dead — restore it and add to the whitelist instead.

- [ ] **Step 5: Re-run vulture with the whitelist**

```bash
docker compose exec backend vulture apps .vulture-whitelist.py --min-confidence 80 --exclude "*/migrations/*,*/tests/*"
```

Expected: zero output, OR only findings below 80% confidence that the team decides to accept.

- [ ] **Step 6: Commit**

```bash
git add backend/.vulture-whitelist.py backend/
git commit -m "refactor(backend): remove vulture-confirmed dead code + add whitelist"
```

### Task D4.4 — Frontend dead-code sweep (ts-prune + eslint)

**Files:** frontend source flagged by ts-prune / eslint

- [ ] **Step 1: Run ts-prune**

```bash
cd frontend && npx ts-prune --ignore "\\.test\\.tsx?$" --ignore "types/" --ignore "app/" 2>&1 | tee ../.tmp/d4-tsprune.txt
cd ..
```

Expected: list of `path:line - name` findings outside of Next.js `app/` dir (which is reflection-loaded) and tests.

- [ ] **Step 2: Review each finding**

For each hit:
- If it's a named export in `frontend/src/components/` with no consumer → delete the export (and the component if that was the only export).
- If it's a utility export in `frontend/src/lib/` or `frontend/src/hooks/` with no consumer → delete.
- If it's re-exported from an index file but unused via that path → delete the re-export.

- [ ] **Step 3: Run eslint to catch remaining unused vars**

```bash
cd frontend && npm run lint -- --rule "no-unused-vars: error" 2>&1 | tee ../.tmp/d4-eslint.txt
cd ..
```

Expected: zero errors after Step 2; fix any remaining ones by deletion.

- [ ] **Step 4: Run frontend test suite**

```bash
cd frontend && npm test -- --run 2>&1 | tail -30
cd ..
```

Expected: all tests green.

- [ ] **Step 5: Build to verify TypeScript still compiles**

```bash
cd frontend && npm run build 2>&1 | tail -20
cd ..
```

Expected: build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/
git commit -m "refactor(frontend): remove unused exports (ts-prune + eslint)"
```

### Task D4.5 — Branch audit

**Files:** none (git operations)

- [ ] **Step 1: List local branches with merged status**

```bash
git branch --merged master | grep -v "^\*" | grep -v "master"
```

Expected: branches already merged into master — safe to delete.

- [ ] **Step 2: List local branches NOT merged into master**

```bash
git branch --no-merged master
```

These are the tricky ones. For each branch in the list, run:

```bash
git log master..<branch-name> --oneline | head -10
git log --oneline -1 <branch-name>   # last commit date
```

- [ ] **Step 3: Classify each branch**

Build a table — paste into the PR body later:

| Branch | Last commit | Status | Action |
|---|---|---|---|
| `arm-b/production-stress-engine` | recent | queued follow-up | **KEEP** |
| `feat/rating-push-9-5` | old | superseded by later releases | DELETE (with user confirmation) |
| `chore/code-review-sweep` | | check if merged as PR | |
| `chore/foundations-and-ci-fixes` | | check if merged as PR | |
| `chore/test-coverage-hardening` | | check if merged as PR | |
| `dependabot/npm_and_yarn/frontend/next-ecosystem-fffcb21a30` | | check if superseded by PR #88 | |
| `docs/coverage-phase-2-design` | | check if merged | |
| `docs/experiments-and-model-card` | | check if merged | |
| `feat/au-lending-realism` | | check if merged | |
| `feat/frontend-regulatory-surfaces` | | check if merged | |
| `feat/gmsc-benchmark` | | check if merged | |
| `feat/ml-validation` | | check if merged | |
| `feat/realism-hem-lmi-features` | | superseded by Arm A PR #94 | DELETE (if fully merged) |
| `workstream-c/accounts-views-split` | | check if merged | |

- [ ] **Step 4: Check remote counterparts**

```bash
git branch -r | grep -v "HEAD\|master"
```

Build a parallel table of remote branches. Any remote-only branch with no local counterpart and a fully-merged state is a deletion candidate.

- [ ] **Step 5: Paste the classification table below and stop for user confirmation**

**CRITICAL: Branch deletion is destructive. Stop here and paste the classification table. Wait for user to mark which branches to delete. Do not proceed to Step 6 until the user has confirmed the deletion list.**

- [ ] **Step 6: Execute approved deletions**

For each user-approved local-branch deletion:

```bash
git branch -D <branch-name>
```

For each user-approved remote-branch deletion:

```bash
git push origin --delete <branch-name>
```

- [ ] **Step 7: Verify final state**

```bash
git branch -a
```

Should contain only: `master`, `chore/v1-10-1-d4-dead-code-sweep` (current), `arm-b/production-stress-engine`, and any legitimately-in-flight work the user identified as keep.

### Task D4.6 — Open and merge D4 PR

- [ ] **Step 1: Push**

```bash
git push -u origin chore/v1-10-1-d4-dead-code-sweep
```

- [ ] **Step 2: PR**

```bash
gh pr create --base master --title "chore(v1.10.1 D4): dead-code sweep (ruff + vulture + ts-prune)" --body "$(cat <<'EOF'
## Summary
- Add `vulture>=2.13` to dev requirements, new `make deadcode` target.
- Ruff F401/F811/F841 autofix + manual review → N lines removed.
- Vulture sweep with `backend/.vulture-whitelist.py` capturing framework-reflection symbols → M lines removed.
- ts-prune frontend sweep → P exports removed.
- Branch audit: <list of deleted branches> (user-approved).

## Test plan
- [x] Full backend pytest green.
- [x] Full frontend test suite green.
- [x] `npm run build` succeeds.
- [x] `make deadcode` exits 0 with whitelist applied.

## Spec
`docs/superpowers/specs/2026-04-19-v1-10-1-production-hardening-design.md` §D4
EOF
)"
```

- [ ] **Step 3: Merge**

```bash
gh pr checks --watch
gh pr merge --merge --delete-branch
git checkout master && git pull
```

---

## Phase D5 — Robustness audit (lint + type + security gates)

### Task D5.1 — Branch setup + add mypy dependency

**Files:**
- Modify: `backend/requirements-dev.txt`

- [ ] **Step 1: Sync and branch**

```bash
git checkout master && git pull origin master
git checkout -b chore/v1-10-1-d5-robustness-audit
```

- [ ] **Step 2: Add mypy + django-stubs**

Edit `backend/requirements-dev.txt`:

```
vulture>=2.13
mypy>=1.13
django-stubs[compatible-mypy]>=5.1
```

- [ ] **Step 3: Rebuild backend**

```bash
docker compose build backend
docker compose up -d
docker compose exec backend mypy --version
```

Expected: prints mypy version.

- [ ] **Step 4: Create `mypy.ini` at backend root**

Create `backend/mypy.ini`:

```ini
[mypy]
python_version = 3.12
plugins = mypy_django_plugin.main
strict_optional = True
warn_unused_ignores = True
ignore_missing_imports = True
check_untyped_defs = True
no_implicit_optional = True
show_error_codes = True

[mypy.plugins.django-stubs]
django_settings_module = config.settings.dev

# Relax where codebase isn't yet typed
[mypy-apps.ml_engine.services.data_generator]
disallow_untyped_defs = False

[mypy-apps.ml_engine.services.trainer]
disallow_untyped_defs = False

[mypy-apps.agents.*]
check_untyped_defs = False
```

(Adjust the `[mypy-apps.*]` sections based on which large, untyped modules surface too many findings to fix in this PR. The goal is "tight gates on the Arm C Phase 1 extraction modules which are already mostly typed" — not "retype every legacy file".)

- [ ] **Step 5: Run mypy on Arm C Phase 1 extraction modules**

```bash
docker compose exec backend mypy \
    apps/ml_engine/services/feature_prep.py \
    apps/ml_engine/services/prediction_cache.py \
    apps/ml_engine/services/policy_overlay.py \
    apps/ml_engine/services/policy_recompute.py \
    apps/ml_engine/services/prediction_diagnostics.py \
    apps/ml_engine/services/prediction_explanations.py \
    apps/ml_engine/services/prediction_features.py \
    apps/ml_engine/services/shadow_scoring.py \
    apps/ml_engine/services/shap_attribution.py \
    apps/ml_engine/services/decision_assembly.py
```

Expected: zero errors (these modules were extracted with clean types in Arm C Phase 1). If any errors surface, fix them before proceeding.

- [ ] **Step 6: Commit**

```bash
git add backend/requirements-dev.txt backend/mypy.ini
git commit -m "chore(deps): add mypy + django-stubs + mypy.ini"
```

### Task D5.2 — Add mypy to pre-commit + CI

**Files:**
- Modify: `.pre-commit-config.yaml`, `.github/workflows/lint.yml`

- [ ] **Step 1: Extend `.pre-commit-config.yaml`**

After the existing ruff-format hook block, add:

```yaml
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.13.0
    hooks:
      - id: mypy
        files: ^backend/apps/ml_engine/services/(feature_prep|prediction_cache|policy_overlay|policy_recompute|prediction_diagnostics|prediction_explanations|prediction_features|shadow_scoring|shap_attribution|decision_assembly)\.py$
        additional_dependencies:
          - django-stubs[compatible-mypy]
          - types-requests
        args: ["--config-file=backend/mypy.ini"]
```

(The file-regex scopes mypy to the 10 Arm C Phase 1 extraction modules. Expand later as more files get typed; do not widen to all of `apps/` in this PR.)

- [ ] **Step 2: Add mypy job to `.github/workflows/lint.yml`**

Open `.github/workflows/lint.yml` and add after the existing ruff job:

```yaml
  mypy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install deps
        run: |
          pip install -r backend/requirements.txt
          pip install -r backend/requirements-dev.txt
      - name: mypy (Arm C Phase 1 extraction modules)
        run: |
          cd backend
          mypy --config-file mypy.ini \
            apps/ml_engine/services/feature_prep.py \
            apps/ml_engine/services/prediction_cache.py \
            apps/ml_engine/services/policy_overlay.py \
            apps/ml_engine/services/policy_recompute.py \
            apps/ml_engine/services/prediction_diagnostics.py \
            apps/ml_engine/services/prediction_explanations.py \
            apps/ml_engine/services/prediction_features.py \
            apps/ml_engine/services/shadow_scoring.py \
            apps/ml_engine/services/shap_attribution.py \
            apps/ml_engine/services/decision_assembly.py
```

- [ ] **Step 3: Test pre-commit hooks locally**

```bash
pre-commit run mypy --all-files
```

Expected: passes (may take 30–60s on first run as mypy caches).

- [ ] **Step 4: Commit**

```bash
git add .pre-commit-config.yaml .github/workflows/lint.yml
git commit -m "ci: add mypy pre-commit + CI job scoped to predictor extraction modules"
```

### Task D5.3 — Frontend eslint/tsc zero-warnings gate

**Files:**
- Modify: `.pre-commit-config.yaml`, `.github/workflows/lint.yml`, `frontend/package.json`

- [ ] **Step 1: Run frontend lint strict**

```bash
cd frontend && npm run lint -- --max-warnings 0 2>&1 | tail -30
cd ..
```

Expected: if any warnings surface, this fails. Fix each one (often an unused import or a `<img>` tag where a `<Image>` component is expected in Next.js) before proceeding.

- [ ] **Step 2: Run tsc strict**

```bash
cd frontend && npx tsc --noEmit 2>&1 | tail -30
cd ..
```

Expected: zero errors. Fix any that appear (usually a missing type or a nullable that isn't being narrowed).

- [ ] **Step 3: Update `frontend/package.json` scripts**

Add or update:

```json
"scripts": {
    ...
    "lint": "next lint",
    "lint:strict": "next lint --max-warnings 0",
    "typecheck": "tsc --noEmit"
}
```

- [ ] **Step 4: Add frontend hooks to `.pre-commit-config.yaml`**

After the mypy hook block, add:

```yaml
  - repo: local
    hooks:
      - id: frontend-lint
        name: frontend eslint (--max-warnings 0)
        entry: bash -c "cd frontend && npm run lint:strict"
        language: system
        files: ^frontend/src/.*\.(ts|tsx|js|jsx)$
        pass_filenames: false

      - id: frontend-typecheck
        name: frontend tsc --noEmit
        entry: bash -c "cd frontend && npm run typecheck"
        language: system
        files: ^frontend/.*\.(ts|tsx)$
        pass_filenames: false
```

- [ ] **Step 5: Extend `.github/workflows/lint.yml`**

Add after the mypy job:

```yaml
  frontend-lint-strict:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - run: cd frontend && npm ci
      - run: cd frontend && npm run lint:strict
      - run: cd frontend && npm run typecheck
```

- [ ] **Step 6: Commit**

```bash
git add .pre-commit-config.yaml .github/workflows/lint.yml frontend/package.json frontend/
git commit -m "ci: frontend eslint --max-warnings 0 + tsc --noEmit gates"
```

### Task D5.4 — Security sweep (bandit + pip-audit + npm audit)

**Files:**
- Modify: `Makefile`, `.github/workflows/security.yml`

- [ ] **Step 1: Run bandit locally**

```bash
docker compose exec backend bandit -r apps/ config/ -lll -f json -o /tmp/bandit.json || true
docker compose exec backend bandit -r apps/ config/ -lll
```

Expected: output lists any high-severity findings. For each, either fix the underlying issue or annotate with `# nosec <code>` and a one-line rationale comment.

- [ ] **Step 2: Run pip-audit**

```bash
docker compose exec backend pip-audit --strict --requirement /app/requirements.txt
```

Expected: zero vulnerabilities. If any surface, upgrade the flagged package in `backend/requirements.txt` to the lowest fixed version and re-run.

- [ ] **Step 3: Run npm audit (runtime deps only)**

```bash
cd frontend && npm audit --audit-level=high --omit=dev
cd ..
```

Expected: zero high-severity findings. Upgrade or `npm audit fix` if anything surfaces.

- [ ] **Step 4: Add `security` and `typecheck` and `verify` targets to Makefile**

After the `deadcode` target (added in D4), add:

```makefile
typecheck:          ## Type-check backend (mypy) and frontend (tsc)
	docker compose exec backend mypy --config-file mypy.ini \
		apps/ml_engine/services/feature_prep.py \
		apps/ml_engine/services/prediction_cache.py \
		apps/ml_engine/services/policy_overlay.py \
		apps/ml_engine/services/policy_recompute.py \
		apps/ml_engine/services/prediction_diagnostics.py \
		apps/ml_engine/services/prediction_explanations.py \
		apps/ml_engine/services/prediction_features.py \
		apps/ml_engine/services/shadow_scoring.py \
		apps/ml_engine/services/shap_attribution.py \
		apps/ml_engine/services/decision_assembly.py
	cd frontend && npm run typecheck

security:           ## Security scans (bandit + pip-audit + npm audit)
	docker compose exec backend bandit -r apps/ config/ -lll
	docker compose exec backend pip-audit --strict --requirement /app/requirements.txt
	cd frontend && npm audit --audit-level=high --omit=dev

verify:             ## Full verification gate: lint + typecheck + security + tests
	$(MAKE) lint
	$(MAKE) typecheck
	$(MAKE) security
	docker compose exec backend pytest -x --tb=short
	cd frontend && npm test -- --run
```

- [ ] **Step 5: Extend `.github/workflows/security.yml`**

Read the current file. If `bandit`, `pip-audit`, and `npm audit` aren't already present as jobs, add them. If they are present, verify thresholds match (`-lll` for bandit = high severity only, `--audit-level=high` for npm, `--strict` for pip-audit).

- [ ] **Step 6: Run `make verify` locally to confirm it exits 0**

```bash
make verify
```

Expected: lint + typecheck + security + backend pytest + frontend vitest all pass. If anything fails, fix the failure before proceeding.

- [ ] **Step 7: Commit**

```bash
git add Makefile .github/workflows/security.yml backend/
git commit -m "ci: security sweep (bandit/pip-audit/npm-audit) + make verify target"
```

### Task D5.5 — Open and merge D5 PR

- [ ] **Step 1: Push**

```bash
git push -u origin chore/v1-10-1-d5-robustness-audit
```

- [ ] **Step 2: PR**

```bash
gh pr create --base master --title "chore(v1.10.1 D5): robustness audit — mypy + eslint + tsc + security" --body "$(cat <<'EOF'
## Summary
- `mypy.ini` + mypy pre-commit + CI job scoped to the 10 Arm C Phase 1 extraction modules.
- Frontend `npm run lint:strict` (--max-warnings 0) + `npm run typecheck` (tsc --noEmit) gates in pre-commit + CI.
- `Makefile`: new `typecheck`, `security`, `verify` targets.
- Security sweep (bandit -lll + pip-audit --strict + npm audit --audit-level=high) added to CI.

## Test plan
- [x] `pre-commit run --all-files` exits 0.
- [x] `make verify` exits 0.
- [x] All existing CI jobs stay green; mypy + frontend-lint-strict + security jobs added and green.

## Spec
`docs/superpowers/specs/2026-04-19-v1-10-1-production-hardening-design.md` §D5
EOF
)"
```

- [ ] **Step 3: Merge**

```bash
gh pr checks --watch
gh pr merge --merge --delete-branch
git checkout master && git pull
```

---

## Phase D6 — End-to-end smoke verification + version bump

### Task D6.1 — Branch setup + smoke fixture

**Files:**
- Create: `tools/smoke_fixtures/smoke_applicant.json`

- [ ] **Step 1: Sync and branch**

```bash
git checkout master && git pull origin master
git checkout -b chore/v1-10-1-d6-smoke-and-release
```

- [ ] **Step 2: Inspect the current LoanApplication serializer to get field names**

```bash
grep -A 50 "class LoanApplicationCreateSerializer\|class LoanApplicationSerializer" backend/apps/loans/serializers.py | head -80
```

Record the required fields (`loan_amount`, `loan_term_months`, `purpose`, etc.).

- [ ] **Step 3: Create the fixture**

Create `tools/smoke_fixtures/smoke_applicant.json`:

```json
{
  "user": {
    "email": "smoke-{{RANDOM}}@example.test",
    "password": "smoke-password-123",
    "first_name": "Smoke",
    "last_name": "Test"
  },
  "application": {
    "loan_amount": 350000,
    "loan_term_months": 360,
    "purpose": "home",
    "annual_income": 140000,
    "employment_length": 60,
    "employment_type": "full_time",
    "credit_score": 780,
    "has_cosigner": 0,
    "has_hecs": 0,
    "has_bankruptcy": 0,
    "number_of_dependants": 0,
    "property_value": 450000,
    "deposit_amount": 100000,
    "monthly_expenses": 4500,
    "existing_credit_card_limit": 20000,
    "state": "NSW"
  }
}
```

(Field names match the existing `LoanApplicationCreateSerializer`. If any of the listed fields are not in the serializer — verify with the grep output from Step 2 — remove them; if any required fields are missing, add them. The goal is a deterministic payload that routes through `home_owner_occupier` segment cleanly and produces an `approved` outcome.)

- [ ] **Step 4: Commit**

```bash
git add tools/smoke_fixtures/smoke_applicant.json
git commit -m "test(smoke): deterministic applicant fixture for E2E smoke script"
```

### Task D6.2 — Write the smoke script

**Files:**
- Create: `tools/smoke_e2e.sh`

- [ ] **Step 1: Create the script**

Create `tools/smoke_e2e.sh` (made executable in the next step):

```bash
#!/usr/bin/env bash
# End-to-end smoke verification for the loan approval pipeline.
#
# Up the docker stack, register a customer, submit an application,
# wait for the orchestrator pipeline to produce a decision + email,
# then write a machine-readable result file.
#
# Usage:
#   tools/smoke_e2e.sh              # full cycle + teardown
#   tools/smoke_e2e.sh --keep-up    # leave stack running for manual inspection

set -euo pipefail

KEEP_UP=false
if [[ "${1:-}" == "--keep-up" ]]; then
  KEEP_UP=true
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIXTURE="${REPO_ROOT}/tools/smoke_fixtures/smoke_applicant.json"
RESULT_FILE="${REPO_ROOT}/.tmp/smoke_result.json"
API_BASE="http://localhost:8000/api/v1"

mkdir -p "${REPO_ROOT}/.tmp"

started_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
start_ms=$(date +%s%3N)

cleanup() {
  if [[ "${KEEP_UP}" == "false" ]]; then
    echo "[smoke] Tearing down docker compose stack..."
    (cd "${REPO_ROOT}" && docker compose down) || true
  else
    echo "[smoke] --keep-up specified; leaving stack running."
  fi
}
trap cleanup EXIT

write_result() {
  local status="$1"
  local reason="$2"
  local model_version="${3:-}"
  local email_hash="${4:-}"
  local end_ms
  end_ms=$(date +%s%3N)
  local duration=$((end_ms - start_ms))

  cat > "${RESULT_FILE}" <<JSON
{
  "started_at": "${started_at}",
  "finished_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "duration_ms": ${duration},
  "status": "${status}",
  "reason": "${reason}",
  "model_version_id": "${model_version}",
  "email_subject_hash": "${email_hash}"
}
JSON

  echo "[smoke] Result written to ${RESULT_FILE}"
  cat "${RESULT_FILE}"
}

echo "[smoke] Starting docker compose..."
(cd "${REPO_ROOT}" && docker compose up -d)

echo "[smoke] Waiting for /api/v1/health/ to return 200..."
for i in {1..30}; do
  if curl -fsS "${API_BASE}/health/" > /dev/null 2>&1; then
    echo "[smoke] Backend healthy after ${i}s."
    break
  fi
  if [[ "${i}" == "30" ]]; then
    write_result "failure" "backend-healthcheck-timeout"
    exit 1
  fi
  sleep 1
done

random=$(tr -dc 'a-z0-9' < /dev/urandom | head -c 8 || echo "smoke$(date +%s)")
email=$(jq -r ".user.email" "${FIXTURE}" | sed "s/{{RANDOM}}/${random}/")
password=$(jq -r ".user.password" "${FIXTURE}")
first_name=$(jq -r ".user.first_name" "${FIXTURE}")
last_name=$(jq -r ".user.last_name" "${FIXTURE}")

echo "[smoke] Registering customer ${email}..."
register_response=$(curl -fsS -X POST "${API_BASE}/accounts/register/" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"${email}\",\"password\":\"${password}\",\"first_name\":\"${first_name}\",\"last_name\":\"${last_name}\",\"role\":\"customer\"}" \
  || (write_result "failure" "register-failed"; exit 1))

echo "[smoke] Logging in..."
login_response=$(curl -fsS -X POST "${API_BASE}/accounts/login/" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"${email}\",\"password\":\"${password}\"}" \
  || (write_result "failure" "login-failed"; exit 1))
access_token=$(echo "${login_response}" | jq -r ".access // empty")
if [[ -z "${access_token}" ]]; then
  write_result "failure" "no-access-token-returned"
  exit 1
fi

echo "[smoke] Submitting loan application..."
application_payload=$(jq -c ".application" "${FIXTURE}")
application_response=$(curl -fsS -X POST "${API_BASE}/loans/" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${access_token}" \
  -d "${application_payload}" \
  || (write_result "failure" "application-submit-failed"; exit 1))
application_id=$(echo "${application_response}" | jq -r ".id // .uuid // empty")
if [[ -z "${application_id}" ]]; then
  write_result "failure" "no-application-id-returned"
  exit 1
fi
echo "[smoke] Application ${application_id} submitted."

echo "[smoke] Triggering orchestrator..."
curl -fsS -X POST "${API_BASE}/agents/orchestrate/${application_id}/" \
  -H "Authorization: Bearer ${access_token}" > /dev/null \
  || (write_result "failure" "orchestrate-trigger-failed"; exit 1)

echo "[smoke] Polling for terminal decision (60s ceiling)..."
decision=""
for i in {1..60}; do
  app_detail=$(curl -fsS "${API_BASE}/loans/${application_id}/" \
    -H "Authorization: Bearer ${access_token}")
  decision=$(echo "${app_detail}" | jq -r ".status // empty")
  if [[ "${decision}" == "approved" || "${decision}" == "declined" || "${decision}" == "referred" ]]; then
    echo "[smoke] Terminal decision reached after ${i}s: ${decision}"
    break
  fi
  sleep 1
done

if [[ -z "${decision}" || ( "${decision}" != "approved" && "${decision}" != "declined" && "${decision}" != "referred" ) ]]; then
  write_result "failure" "no-terminal-decision-in-60s"
  exit 1
fi

model_version=$(echo "${app_detail}" | jq -r ".model_version_id // .ml_prediction.model_version // empty")

echo "[smoke] Fetching associated email..."
email_detail=$(curl -fsS "${API_BASE}/emails/${application_id}/" \
  -H "Authorization: Bearer ${access_token}") || true
email_subject=$(echo "${email_detail}" | jq -r ".subject // empty")
email_hash=""
if [[ -n "${email_subject}" ]]; then
  email_hash=$(printf "%s" "${email_subject}" | sha256sum | cut -c1-16)
fi

if [[ -z "${email_hash}" ]]; then
  write_result "failure" "no-email-generated"
  exit 1
fi

write_result "success" "ok" "${model_version}" "${email_hash}"
echo "[smoke] SUCCESS."
```

- [ ] **Step 2: Make executable**

```bash
chmod +x tools/smoke_e2e.sh
```

- [ ] **Step 3: Commit**

```bash
git add tools/smoke_e2e.sh
git commit -m "test(smoke): end-to-end script (register → apply → orchestrate → decision → email)"
```

### Task D6.3 — Run the smoke script locally

**Files:** none (verification only)

- [ ] **Step 1: Ensure stack is running with a seeded model**

```bash
docker compose up -d
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py generate_data --count 500
docker compose exec backend python manage.py train_model --algorithm xgb
```

(500 rows is enough to train a model; don't waste time on 10k.)

- [ ] **Step 2: Run the smoke script**

```bash
tools/smoke_e2e.sh
```

Expected: each `[smoke]` phase logs its progress; final output is `[smoke] SUCCESS.` and `.tmp/smoke_result.json` with `"status": "success"`.

- [ ] **Step 3: Inspect the result file**

```bash
cat .tmp/smoke_result.json
```

Verify:
- `status` is `"success"`.
- `model_version_id` is non-empty.
- `email_subject_hash` is non-empty.
- `duration_ms` is reasonable (< 120000 = 2 min).

- [ ] **Step 4: If the script fails, debug with `--keep-up`**

```bash
tools/smoke_e2e.sh --keep-up
# Inspect logs:
docker compose logs backend | tail -50
docker compose logs celery_worker_ml | tail -30
```

Fix the fixture, script, or backend code until the smoke test produces `"status": "success"`. Common failures and fixes:

| Symptom | Likely cause | Fix |
|---|---|---|
| `register-failed` | Email already exists from a prior run | Use the `{{RANDOM}}` template; confirm the substitution ran |
| `no-access-token-returned` | Login returns JWT under a different key (`token` / `access_token` / `jwt`) | Adjust the `jq` filter in the script |
| `application-submit-failed` | Serializer rejects a field | `docker compose logs backend` shows 400 body; remove the offending field from `smoke_applicant.json` |
| `orchestrate-trigger-failed` | Endpoint shape different from `/api/v1/agents/orchestrate/<id>/` | Adjust to match `backend/apps/agents/urls.py` |
| `no-terminal-decision-in-60s` | Celery worker not processing | Check `docker compose logs celery_worker_ml` |
| `no-email-generated` | Email endpoint returns 404 (no email row yet) | The orchestrator may dispatch the email asynchronously — extend the polling loop to wait for email availability |

- [ ] **Step 5: Capture the green result for the PR**

```bash
cat .tmp/smoke_result.json | tee smoke-result-d6.json
```

(Copy the JSON into the PR body later.)

### Task D6.4 — GitHub Actions workflow

**Files:**
- Create: `.github/workflows/smoke-e2e.yml`

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/smoke-e2e.yml`:

```yaml
name: smoke-e2e

on:
  workflow_dispatch:

jobs:
  smoke:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4

      - name: Install jq
        run: sudo apt-get update && sudo apt-get install -y jq

      - name: Create .env from example
        run: |
          cp .env.example .env
          # Override any secrets needed for smoke run
          {
            echo "DJANGO_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')"
            echo "FIELD_ENCRYPTION_KEY=$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
          } >> .env

      - name: Build + up
        run: docker compose up -d

      - name: Migrate + seed minimal dataset
        run: |
          docker compose exec -T backend python manage.py migrate
          docker compose exec -T backend python manage.py generate_data --count 500
          docker compose exec -T backend python manage.py train_model --algorithm xgb

      - name: Run smoke script
        run: tools/smoke_e2e.sh --keep-up

      - name: Print backend + celery logs on failure
        if: failure()
        run: |
          docker compose logs backend | tail -200
          docker compose logs celery_worker_ml | tail -100

      - name: Upload smoke result
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: smoke-result
          path: .tmp/smoke_result.json
          if-no-files-found: warn

      - name: Teardown
        if: always()
        run: docker compose down -v
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/smoke-e2e.yml
git commit -m "ci: smoke-e2e workflow (workflow_dispatch only)"
```

### Task D6.5 — README verification section

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add "Verifying the build" section**

After the "## Testing" section in `README.md`, insert:

```markdown
## Verifying the build

An end-to-end smoke script exercises the full pipeline (register → apply → orchestrate → decision → email) against a locally-running stack:

```bash
docker compose up -d
make seed                                   # generate data + train model
tools/smoke_e2e.sh                          # full cycle + teardown
tools/smoke_e2e.sh --keep-up                # leave stack up for manual inspection
```

Result is written to `.tmp/smoke_result.json`:

```json
{
  "started_at": "2026-04-19T12:34:56Z",
  "finished_at": "2026-04-19T12:35:42Z",
  "duration_ms": 46123,
  "status": "success",
  "reason": "ok",
  "model_version_id": "<uuid>",
  "email_subject_hash": "<sha256-prefix>"
}
```

The same script is available as a manually-triggered GitHub Actions job under `smoke-e2e` — see `.github/workflows/smoke-e2e.yml`. The workflow is `workflow_dispatch`-only; there is no nightly cron by design (cost-conscious default; add a cron once the signal is known stable).
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): document smoke_e2e.sh + smoke result schema"
```

### Task D6.6 — Version bump to 1.10.1

**Files:**
- Modify: `backend/config/settings/base.py`

- [ ] **Step 1: Edit the version constant**

Open `backend/config/settings/base.py`, locate `APP_VERSION = "1.10.0"`, change to:

```python
APP_VERSION = "1.10.1"
```

- [ ] **Step 2: Verify frontend consumes the same version (optional)**

```bash
grep -rn "1\.10\.0" frontend/src/ package.json backend/config/ | head -10
```

If any other file mirrors `APP_VERSION` (e.g., `frontend/package.json` version field, a config constant), update it to `1.10.1` as well.

- [ ] **Step 3: Commit**

```bash
git add backend/config/settings/base.py
# plus any other files updated in Step 2
git commit -m "chore(release): bump APP_VERSION 1.10.0 → 1.10.1"
```

### Task D6.7 — Open PR, merge, tag, release

- [ ] **Step 1: Push**

```bash
git push -u origin chore/v1-10-1-d6-smoke-and-release
```

- [ ] **Step 2: PR**

```bash
gh pr create --base master --title "chore(v1.10.1 D6): smoke-e2e script + version bump to 1.10.1" --body "$(cat <<'EOF'
## Summary
- New `tools/smoke_e2e.sh` + deterministic applicant fixture (`tools/smoke_fixtures/smoke_applicant.json`).
- New `.github/workflows/smoke-e2e.yml` — workflow_dispatch-only smoke job.
- `README.md` § "Verifying the build" documents invocation + result schema.
- `APP_VERSION` bumped to `1.10.1`.

## Smoke result (local)
```json
<paste .tmp/smoke_result.json contents here>
```

## Test plan
- [x] `tools/smoke_e2e.sh` exits 0 locally against a fresh stack.
- [x] `smoke_result.status == "success"` with a non-empty `model_version_id` and `email_subject_hash`.
- [x] GitHub Actions `smoke-e2e` workflow runs green on manual dispatch.

## Spec
`docs/superpowers/specs/2026-04-19-v1-10-1-production-hardening-design.md` §D6
EOF
)"
```

- [ ] **Step 3: Trigger smoke-e2e CI job from the PR**

```bash
gh workflow run smoke-e2e.yml --ref chore/v1-10-1-d6-smoke-and-release
gh run watch
```

Expected: workflow run green; smoke-result artifact uploaded.

- [ ] **Step 4: Merge**

```bash
gh pr checks --watch
gh pr merge --merge --delete-branch
git checkout master && git pull
```

- [ ] **Step 5: Tag v1.10.1**

```bash
git tag -a v1.10.1 -m "v1.10.1 — Production hardening pass

D1: Strip hosted-demo scaffolding
D2: make clean + make clean-deep
D3: prune_model_artifacts command
D4: Dead-code sweep (ruff + vulture + ts-prune)
D5: mypy + eslint-strict + tsc + bandit + pip-audit + npm-audit
D6: End-to-end smoke script + v1.10.1 tag

Spec: docs/superpowers/specs/2026-04-19-v1-10-1-production-hardening-design.md
"
git push origin v1.10.1
```

- [ ] **Step 6: Create GitHub release**

```bash
gh release create v1.10.1 --title "v1.10.1 — Production hardening pass" --notes "$(cat <<'EOF'
Six-PR production hardening pass. No new features; every shipped v1.10.0 capability preserved.

## Highlights
- **Disk:** ≥ 1.3 GB reclaimed via extended `make clean` + `ml_models/` prune.
- **Code hygiene:** ruff F401/F811/F841 + vulture sweep + ts-prune; lint/type/security gates tightened in CI.
- **Correctness:** end-to-end smoke script proves the pipeline wires up; `tools/smoke_e2e.sh` is runnable locally and in CI (workflow_dispatch).
- **Scope:** aspirational hosted-demo content removed from docs; project is explicitly local-only by design.

## Merged PRs
- D1 chore(v1.10.1 D1): strip hosted-demo scaffolding
- D2 chore(v1.10.1 D2): extended make clean + gitignore audit
- D3 chore(v1.10.1 D3): prune_model_artifacts command + retention policy
- D4 chore(v1.10.1 D4): dead-code sweep (ruff + vulture + ts-prune)
- D5 chore(v1.10.1 D5): robustness audit — mypy + eslint + tsc + security
- D6 chore(v1.10.1 D6): smoke-e2e script + version bump

## Spec / Plan
- Spec: `docs/superpowers/specs/2026-04-19-v1-10-1-production-hardening-design.md`
- Plan: `docs/superpowers/plans/2026-04-19-v1-10-1-production-hardening.md`
EOF
)"
```

---

## Post-merge verification

- [ ] **Step 1: Confirm clean state**

```bash
git checkout master && git pull
git tag | grep v1.10.1
git log --oneline -10
```

Expected: `v1.10.1` present; last 6 merge commits correspond to D1–D6.

- [ ] **Step 2: Run full `make verify` one more time**

```bash
make verify
```

Expected: exits 0.

- [ ] **Step 3: Run one more smoke**

```bash
tools/smoke_e2e.sh
```

Expected: `.tmp/smoke_result.json` shows `"status": "success"`.

- [ ] **Step 4: Update memory**

Ask the user if they want to record the v1.10.1 ship in auto-memory (new file `project_v1_10_1_production_hardening.md` + one-line entry in `MEMORY.md`).

---

## Test gates (quick-reference summary)

| Phase | Primary gate | Secondary gate |
|---|---|---|
| D1 | `grep -rEi "hosted demo\|demo url\|fly\.io\|render\.com\|hetzner" docs/ workflows/ README.md` returns zero matches | CI green |
| D2 | `du -sh .` delta ≥ 500 MB after `make clean` on a built tree | CI green |
| D3 | `du -sh backend/ml_models` ≤ 50 MB post-prune; `test_prune_model_artifacts.py` passes | Full `ml_engine/` pytest suite green |
| D4 | `make deadcode` exits 0; `vulture apps --min-confidence 80` with whitelist returns zero output | Full backend + frontend test suites green |
| D5 | `make verify` exits 0; `pre-commit run --all-files` exits 0 | mypy + frontend-lint-strict + security CI jobs green |
| D6 | `tools/smoke_e2e.sh` exits 0; `smoke_result.status == "success"` | `smoke-e2e` workflow green on `workflow_dispatch` |

## Success criteria (from spec §8)

- [ ] `grep -rEi "hosted demo|demo url|live demo|fly\.io|render\.com" docs/ workflows/ README.md` returns zero matches.
- [ ] `du -sh .` drops ≥ 1.3 GB after `make clean` on a built tree.
- [ ] `du -sh backend/ml_models` ≤ 50 MB post-prune.
- [ ] `make verify` exits 0; `pre-commit run --all-files` exits 0.
- [ ] `tools/smoke_e2e.sh` exits 0; `smoke_result.status == "success"`.
- [ ] `backend/config/settings/base.py` → `APP_VERSION = "1.10.1"`.
- [ ] All existing tests green at the head of every deliverable PR.
- [ ] File-size allowlist (`tools/file_size_allowlist.json`) unchanged or tightened — never loosened.
- [ ] No new branches remain after D4 audit besides `master`, `arm-b/production-stress-engine`, and any in-flight work.
- [ ] Release tagged `v1.10.1`.
