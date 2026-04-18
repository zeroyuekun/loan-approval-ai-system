# v1.10.1 — Production Hardening Pass

**Status:** Draft (awaiting user review)
**Date:** 2026-04-19
**Author:** Claude (brainstorming session with user delegation)
**Scope:** Project-wide hardening across docs, disk, dead code, linting, and smoke verification. Six atomic PRs.
**Supersedes:** none
**Target version:** v1.10.0 → v1.10.1

## 1. Goal

Make the project *robust, lean, and verifiably working* without regressing any shipped capability from v1.10.0 (XGBoost AU-lender parity, Arm C Phase 1 predictor split, v1.9.x realism/coverage work).

Concretely: remove the aspirational "live demo" scaffolding the user has decided not to pursue; reclaim ~1.3 GB of ephemeral disk; prune 130+ stale model artifacts; fix whatever a tight lint/type/security sweep surfaces; and prove correctness end-to-end with a scripted smoke test.

## 2. Non-negotiable principles

1. **Safe, reversible, tested.** Every change ships behind a CI-gated PR; every deletion is recoverable from git or regeneration; no destructive branch deletes without explicit per-action confirmation.
2. **No new features.** This is hardening, not expansion. Arm B (stress-engine) and Arm C Phase 2 (`trainer.py` / `data_generator.py` splits) stay queued.
3. **Quality bar holds.** The 500 LOC allowlist from `tools/file_size_allowlist.json` does not regress. No file currently at the cap grows; no new files join the allowlist.
4. **Every deliverable is mergeable in isolation.** If we stop after D1 we still have shipped value.
5. **User preferences carry over.**
   - No apology/disappointment language anywhere (email-engine, docs).
   - Bias review queue stays bias-only.
   - No placeholder "coming soon" scaffolding — scrap or ship complete.
   - Cost-conscious: free tooling first (`vulture`, `ts-prune`, `ruff`), no paid services.

## 3. Scope: 6 Deliverables

Recommended merge order **D1 → D2 → D3 → D4 → D5 → D6.** Each is an atomic PR. Only D4 (dead-code deletions) and D6 (smoke test) can surface follow-up fixes that feed back into later deliverables.

### D1. Strip "live demo" scaffolding

**Motivation:** User has decided not to deploy a hosted demo. The aspirational section in `workflows/deployment.md` lines 120–154 reads as a TODO nobody will execute — half-finished scaffolding.

**Changes:**

- **`workflows/deployment.md`** — Delete § "Cloud Deployment Options" (lines 120–154). Replace with a one-paragraph §"Scope note" explicitly stating this is a local-Docker-Compose portfolio project by design, with a pointer to `backend/docs/RUNBOOK.md` for operational procedures.
- **`README.md`** — Audit for any hosted-demo aspirational language. Line 202's "Good enough for a demo, not a fintech launch" is a factual scoping caveat and stays. Any other mentions of future-hosted-demo get removed.
- **`docs/engineering-journal.md`** + **`docs/interview-talking-points.md`** — Grep for demo-URL / hosted-demo references; excise.
- **`docs/DESIGN_JOURNEY.md`** — Same audit.
- **Remote branches** — Delete `origin/chore/demo-and-readme` (never merged; superseded by README work that already landed). Requires confirmation before destructive push.
- **Local branches** — Delete matching `chore/demo-and-readme`.

**Test gate:** `grep -rEi "hosted demo|demo url|live demo|fly\.io|render\.com|deploy.*demo" docs/ workflows/ README.md` returns zero matches.

**Commit message style:** `chore(docs): drop hosted-demo scaffolding — local-only portfolio scope`

### D2. Ephemeral-artifact discipline + `make clean` upgrade

**Motivation:** `.next/` (515 MB), `node_modules/` (717 MB), `__pycache__` (29 dirs / 303 files), `coverage/`, `playwright-report/`, `test-results/`, `tsconfig.tsbuildinfo` — none should ever show up in diffs; all should be easy to nuke.

**Current state (verified 2026-04-19):** `.gitignore` already covers `__pycache__/`, `.venv/`, `node_modules/`, `.next/`, `.pytest_cache/`, `htmlcov/`, `frontend/coverage/`, `frontend/playwright-report/`, `frontend/test-results/`, `*.tsbuildinfo`, `backend/ml_models/*.joblib`. Good foundation — this deliverable is polish, not rewrite.

**Changes:**

- **`.gitignore` audit** — Add any missing entries surfaced by `git status --ignored` on a built tree. Current coverage is strong; likely additions: `frontend/.next/diagnostics/` (new in Next 15), Sentry source-map bundles (`frontend/sentry-*.bundle.js.map`) if any leak in. Do not add `.vite/` — already covered by `node_modules/` because it lives inside it.
- **`Makefile` `clean` target extension** — Current target only runs `docker compose down -v` + `__pycache__` nuke. Extend to:
  ```
  clean:              ## Nuke ephemerals (containers, caches, build output)
      docker compose down -v
      find backend -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
      find backend -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
      find . -name "*.pyc" -delete 2>/dev/null || true
      rm -rf frontend/.next frontend/coverage frontend/playwright-report frontend/test-results
      rm -rf backend/htmlcov backend/.coverage
      rm -f frontend/tsconfig.tsbuildinfo
      @echo "Clean complete. Re-run 'make build' then 'make dev' to restart."

  clean-deep:         ## clean + remove node_modules + .venv (forces reinstall)
      $(MAKE) clean
      rm -rf frontend/node_modules backend/.venv
      @echo "Deep-clean complete. Expect re-install before next run."
  ```
- **`make clean` smoke** — Post-clean, `du -sh .` drops ≥ 1.3 GB on a tree where `.next` + `coverage` + `__pycache__` all exist.
- **README `Testing` section** — One-line mention of `make clean` for the dev workflow.

**Test gate:** Running `make clean` on a freshly-built tree reduces disk usage by ≥ 1.3 GB and leaves no files that `git status` doesn't recognise as tracked.

### D3. `ml_models/` artifact prune + retention policy

**Motivation:** 152 MB in `backend/ml_models/` with ~140 joblib files. Only one is the active `ModelVersion.file_path`. The rest are training experiments from March 13 → April 18, plus 22× 5-byte test placeholder files (`test_*_v*.joblib`, `contract_test_model.joblib`, `list_test_model.joblib`). These are gitignored (good), but they still consume local disk and slow down `du`/backups.

**Changes:**

- **New file:** `backend/apps/ml_engine/management/commands/prune_model_artifacts.py` — management command with signature `--keep N --dry-run`. Logic:
  1. Load all `ModelVersion` rows; extract `file_path` basenames.
  2. Walk `backend/ml_models/*.joblib`.
  3. **Never delete:** `golden_metrics.json`, `contract_test_model.joblib` (used by contract tests), the file of any `is_active=True` ModelVersion, or the file of the most recent N `is_active=False` ModelVersions per-segment (rollback buffer). Default `N=1`.
  4. Delete everything else (only from filesystem; ModelVersion rows untouched unless explicit `--delete-orphaned-rows` flag).
  5. Output reclaimed bytes and list of kept files.
- **Test:** `test_prune_model_artifacts.py` — fixture sets up an `ml_models/` sandbox with 10 joblibs, 3 ModelVersion rows, verifies the correct 3 + golden_metrics + contract_test survive.
- **22 five-byte placeholder joblibs audit** — grep `backend/` for references to `test_*_v*.joblib`, `contract_test_model.joblib`, `list_test_model.joblib`. If any test imports them (not just references the filename in a fixture factory), keep. Otherwise delete. Expected: `contract_test_model.joblib` is referenced; the rest may be leftover from ModelVersion lifecycle tests and safe to remove — but only after verification.
- **Optional ongoing housekeeping:** document calling the command from the weekly Celery beat task in `backend/docs/RUNBOOK.md`. Do not schedule it yet (YAGNI until user asks).
- **No CI gate on `ml_models/` size** — `.joblib` files are gitignored, so CI checkouts never see them. Disk discipline here is a local-dev concern, not a CI concern. Document in `RUNBOOK.md` that a developer should run `python manage.py prune_model_artifacts --dry-run` after any training batch > 10 models.

**Test gate:** `du -sh backend/ml_models` post-prune ≤ 50 MB on the developer machine; all ML-engine regression tests stay green; the `prune_model_artifacts` unit test passes.

### D4. Dead-code sweep

**Motivation:** Workstream D already removed 610 lines of dead frontend components (v1.9.5 PR #83), and Arm C Phase 1 just tightened predictor.py. A targeted sweep with automated tools should now surface the remaining long tail without manual guessing.

**Changes:**

- **Backend — Python dead-code sweep:**
  - `ruff check --select F401,F811,F841` — unused imports, redefinitions, unused locals. Auto-fixable ones get `--fix`; non-fixable get manual review.
  - `vulture backend/apps --min-confidence 80` — unused functions/classes. Hand-review at confidence 80% (anything lower is noisy in Django). Create `backend/.vulture-whitelist.py` for intentional-but-unreferenced symbols (Django signals, management commands loaded via app config, Celery tasks, DRF serializer fields).
  - **Tool install:** add `vulture` to `backend/requirements-dev.txt` (or equivalent dev-deps file — audit which exists). Document invocation in `Makefile` under a new `deadcode` target.
  - Expected LOC savings: ≤ 200 lines. This is lower than the initial Workstream D sweep because most obvious candidates are gone.
- **Frontend — TypeScript dead-code sweep:**
  - `eslint --rule "no-unused-vars: error"` — confirm zero warnings.
  - `npx ts-prune --ignore ".test.tsx?$" --ignore "types/" --ignore "app/"` — lists unused exports outside of the Next.js app dir and tests. Review each finding; delete or annotate.
  - Check `frontend/src/components/` for orphan components (grep every export for any consumer — components with zero consumers get deleted).
- **Artifact dead-code:**
  - 22× five-byte placeholder joblibs — covered in D3.
  - Remaining local branches audit (see below).
- **Local branch audit** — present this list at PR time and delete the ones the user approves:
  - `chore/demo-and-readme` — already deleted in D1, listed here for consistency.
  - `chore/code-review-sweep`, `chore/foundations-and-ci-fixes`, `chore/test-coverage-hardening` — check whether `origin` still has them and whether those PRs merged. If merged, delete local.
  - `docs/coverage-phase-2-design`, `docs/experiments-and-model-card` — same audit.
  - `feat/au-lending-realism`, `feat/frontend-regulatory-surfaces`, `feat/gmsc-benchmark`, `feat/ml-validation`, `feat/rating-push-9-5` — same audit.
  - `dependabot/npm_and_yarn/frontend/next-ecosystem-fffcb21a30` — if superseded by PR #88, delete.
  - `workstream-c/accounts-views-split` — if merged, delete; if not merged, keep (user may resume).
  - `arm-b/production-stress-engine` — **KEEP** (queued follow-up work).
  - `feat/realism-hem-lmi-features` — if the D8 work already landed in v1.10.0 Arm A PR #94, delete.
- **Remote branch audit** — same cross-check; deletions require explicit confirmation before `git push --delete`.
- **Test gate:** full backend + frontend test suites stay green after every deletion.

**Commit style:** one commit per tool class — `refactor: remove unused backend imports (ruff F401)`, `refactor: remove unused frontend exports (ts-prune)`, `chore: delete N orphan branches`.

### D5. Robustness audit — lint, type, and security gates

**Motivation:** Shore up CI so the next human reviewer — or hiring manager — running a lint/type sweep sees zero findings. The current pre-commit config covers ruff + ruff-format + gitleaks + file-size-bar + generic hygiene, but frontend lint/type/mypy are not in the commit-time gate.

**Changes:**

- **`backend/apps` — type coverage push:**
  - `mypy backend/apps/ml_engine --strict-optional` — add missing `None`-handling.
  - Gradually enable `--disallow-untyped-defs` for the newly-extracted modules from Arm C Phase 1 (`prediction_cache.py`, `feature_prep.py`, `policy_overlay.py`, etc.) — they're small and already type-hinted in signatures.
  - Add `mypy` invocation to CI.
- **Frontend — lint + type:**
  - `cd frontend && npm run lint -- --max-warnings 0` — fix any surfaced warnings.
  - `cd frontend && npx tsc --noEmit` — confirm zero errors.
  - Add both to CI (they may already run — audit `.github/workflows/`).
- **Security sweep:**
  - `bandit -r backend/apps backend/config -lll` — high-severity findings only. Fix or `# nosec` with rationale comment.
  - `safety check --bare` against `backend/requirements.txt` — flag known CVEs.
  - `cd frontend && npm audit --audit-level=high --omit=dev` — address any high-severity deps.
  - `cd frontend && npm audit --audit-level=critical` — address any critical dev-deps.
- **`.pre-commit-config.yaml` upgrade:**
  - Add `mypy` hook for backend (`mirrors-mypy`, scoped to `^backend/apps/`).
  - Add frontend hooks: `eslint --max-warnings 0` and `tsc --noEmit` running via `pre-commit-eslint` or a local `language: system` hook.
  - Keep existing hooks untouched.
- **`Makefile` lint target extension** — add `typecheck`, `security`, and a `verify` target that runs lint + typecheck + security + all tests.

**Test gate:** `make verify` exits 0; `pre-commit run --all-files` exits 0; CI mypy + npm-audit jobs green.

### D6. End-to-end smoke verification

**Motivation:** Prove to the user (and to themselves in six months) that every layer — Django → Postgres → Redis → Celery → ML predictor → email engine → orchestrator — still talks to its neighbour correctly after D1–D5.

**Changes:**

- **New fixture:** `tools/smoke_fixtures/smoke_applicant.json` — deterministic applicant inputs that exercise the full pipeline without triggering a policy hard-fail or the decline tier. Designed to route through the `home_owner_occupier` segment with a clean approve outcome. Schema mirrors `LoanApplicationCreateSerializer` field names; values derived from existing test fixtures under `backend/tests/fixtures/`.
- **New script:** `tools/smoke_e2e.sh` — bash (Unix/Windows-Git-Bash compatible). Uses the actual endpoint paths verified during the implementation-plan authoring phase (paths below are the expected shape; confirm in the task plan):
  1. `docker compose up -d` and wait for `/api/v1/health/deep/` to return 200 (60s ceiling).
  2. Seed a fresh applicant via the register endpoint → capture JWT.
  3. Submit a loan application using `smoke_applicant.json`.
  4. Poll the application-detail endpoint until `status ∈ {approved, declined, referred}` (60s ceiling).
  5. Fetch the associated email record — verify exactly one email generated.
  6. Fetch the prediction record — verify PD, tier, reason codes present.
  7. Write `smoke_result.json` with `{ started_at, finished_at, p50_ms, p95_ms, status, model_version_id, email_subject_hash }`.
  8. `docker compose down` on teardown (optional `--keep-up` flag to leave running for manual inspection).
- **New GitHub Actions workflow:** `.github/workflows/smoke-e2e.yml` — runs the script on `workflow_dispatch` only (manual trigger). No cron schedule yet — cost-conscious default; can be added later when the signal is known to be stable. Uploads `smoke_result.json` as an artifact.
- **README update:** new `## Verifying the build` section pointing to `tools/smoke_e2e.sh` + the `smoke_result.json` schema.
- **PR body** — attach `smoke_result.json` inline as proof of a passing E2E run before merge.

**Test gate:** `tools/smoke_e2e.sh` exits 0 locally; `smoke_result.status == "success"`; p95 < 5000 ms (the real p95 on synthetic data is well under this — the bound is a sanity check, not a performance claim).

## 4. File map

**NEW (8 files):**
- `backend/apps/ml_engine/management/commands/prune_model_artifacts.py`
- `backend/apps/ml_engine/tests/test_prune_model_artifacts.py`
- `backend/.vulture-whitelist.py`
- `tools/smoke_e2e.sh`
- `tools/smoke_fixtures/smoke_applicant.json`
- `.github/workflows/smoke-e2e.yml`
- `docs/superpowers/specs/2026-04-19-v1-10-1-production-hardening-design.md` (this file)
- `docs/superpowers/plans/2026-04-19-v1-10-1-production-hardening.md` (produced by writing-plans)

**MODIFY:**
- `Makefile` — extended `clean` + new `clean-deep`, `typecheck`, `security`, `verify` targets
- `workflows/deployment.md` — drop hosted-demo section, replace with local-scope note
- `README.md` — add `make clean` reference; new "Verifying the build" subsection
- `docs/engineering-journal.md`, `docs/interview-talking-points.md`, `docs/DESIGN_JOURNEY.md` — excise hosted-demo references
- `.gitignore` — audit pass (add `.vite/`, cache subdirs if missing)
- `.pre-commit-config.yaml` — add mypy + frontend eslint/tsc hooks
- `.github/workflows/` — add mypy + npm-audit jobs if not present
- `backend/config/settings/base.py` — `APP_VERSION = "1.10.1"`
- Backend/frontend source files surfaced by D4 (ruff F401, vulture, ts-prune) — per-PR scope, listed in the implementation plan task-by-task

**DELETE:**
- ~130 stale `backend/ml_models/*.joblib` (gitignored; disk-only deletion)
- Orphan local + remote git branches (with per-deletion confirmation)
- Whatever D4 surfaces as unreferenced code

## 5. Testing strategy

- **Unit** — `test_prune_model_artifacts.py` (D3). Every other deliverable rides on existing test suites.
- **Regression** — `make verify` (introduced in D5) must exit 0 at the head of every deliverable PR. Covers ruff + mypy + eslint + tsc + bandit + npm-audit + backend pytest + frontend vitest.
- **E2E** — `tools/smoke_e2e.sh` (D6). Captures `smoke_result.json` attached to the D6 PR.
- **Disk** — `du -sh .` before and after `make clean`; expect ≥ 1.3 GB delta. Attached to D2 PR body.
- **Backup/recovery** — every branch deletion confirmed by the user; every file deletion verified to be either gitignored (joblibs) or recoverable from `git log` (dead code).

## 6. Rollout

1. Branch from master (`master` at `5807fae` post-Arm C Phase 1 merge).
2. One feature branch per deliverable (`chore/v1-10-1-d1-demo-strip`, `chore/v1-10-1-d2-clean-target`, …). Merged to master in D1 → D6 order.
3. Bump `APP_VERSION` to `1.10.1` in D6's PR (last deliverable, so the version string matches the shipped state).
4. Tag release on master after D6 merge: `v1.10.1`.
5. Close any follow-up items as GitHub issues rather than expanding scope mid-pass.

## 7. Risks & mitigations

- **Risk:** `prune_model_artifacts` deletes a joblib that a test still references.
  **Mitigation:** Dry-run first. Grep for each candidate basename across `backend/tests/` and `backend/apps/**/tests/` before deletion. Test covers the whitelist logic explicitly.
- **Risk:** A vulture or ts-prune "unused" finding is actually used via string-based reflection (Django URL reverse, management-command discovery, Celery task autodiscovery).
  **Mitigation:** `backend/.vulture-whitelist.py` + per-finding human review. No auto-delete below 100% confidence.
- **Risk:** Remote branch deletion is destructive to in-flight work on another developer's machine.
  **Mitigation:** Check `origin/HEAD` and open PRs before deleting any remote branch. Solo-dev project so low blast radius in practice, but the per-action confirmation stays.
- **Risk:** D5 tightens lint/type gates and reveals cascading failures that blow out the PR.
  **Mitigation:** Fix the top findings; for any finding that would require > 20 LOC of changes, file a follow-up issue and add a targeted `# noqa:` / `# type: ignore[code]` with a one-line rationale + issue link.
- **Risk:** `make clean` on Windows has path-separator quirks.
  **Mitigation:** Make targets use forward slashes throughout; `find`/`rm -rf` work under Git-Bash. Smoke-test on Windows before PR merge.
- **Risk:** `smoke_e2e.sh` flakes in CI due to Celery cold-start.
  **Mitigation:** Health-check loop with 60s ceiling; log timing breakdowns in `smoke_result.json`. One retry allowed before failure.

## 8. Success criteria

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

## 9. Explicitly out of scope

- **Arm B** (portfolio stress-engine uplift) — queued as a separate spec; branch already staged.
- **Arm C Phase 2** (`trainer.py` 1324 LOC and `data_generator.py` 1559 LOC splits) — queued; depends on capacity.
- **Flipping credit-policy overlay from shadow → enforce** — operational rollout decision, not a code change; user can trigger at any time via the existing shadow-mode flag.
- **Deploying a hosted demo** — explicitly de-scoped in D1 by user decision.
- **New ML-quality improvements** — model is at AUC 0.87–0.88 on synthetic + 0.8663 on GMSC real data (top-1% Kaggle); further tuning is diminishing returns per user's own call.

## 10. Open questions

None. User has delegated every design decision within this scope ("I will let you decide the choices you make for your recommendation just make the project quality first"). Proceed to implementation plan.
