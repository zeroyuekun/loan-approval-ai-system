# CS50x Final Project Submission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the existing `loan-approval-ai-system` codebase into a sibling folder `C:\Users\Admin\loan-approval-ai-system-cs50` that is a CS50x final-project-ready submission bundle: curated source copy, CS50-compliant README, AI usage citations, and a 3-minute video script.

**Architecture:** One-shot copy of source (with strict excludes) into a sibling folder, plus three new CS50 documents (`README.md`, `AI_USAGE.md`, `VIDEO_SCRIPT.md`) on top, plus AI-citation comment headers on 8 key entry-point files. Fresh `git init` in the new folder. Submission runs from there via `submit50` (user-initiated, post-plan).

**Tech Stack:** PowerShell `robocopy` for tree copy with excludes, `Copy-Item` for individual files, plain markdown for new docs, comment header edits for citations.

**Source spec:** `docs/superpowers/specs/2026-05-14-cs50-final-project-design.md` (commit `245a1fe` on `feat/cs50-final-project`).

---

## Phase 1 — Scaffold + Copy

### Task 1: Create the sibling target folder

**Files:**
- Create: `C:\Users\Admin\loan-approval-ai-system-cs50\` (directory)

- [ ] **Step 1: Verify the target folder does NOT already exist**

Run:
```powershell
if (Test-Path "C:\Users\Admin\loan-approval-ai-system-cs50") { Write-Output "ALREADY-EXISTS-ABORT" } else { Write-Output "OK-MISSING" }
```
Expected: `OK-MISSING`. If `ALREADY-EXISTS-ABORT`, stop and ask the user — do not overwrite their work.

- [ ] **Step 2: Create the empty folder**

Run:
```powershell
New-Item -ItemType Directory -Path "C:\Users\Admin\loan-approval-ai-system-cs50" | Out-Null
Write-Output "created"
```
Expected: `created`.

- [ ] **Step 3: Verify**

Run:
```powershell
Test-Path "C:\Users\Admin\loan-approval-ai-system-cs50"
```
Expected: `True`.

**No commit yet** — git init happens after the copy is complete (Task 6).

---

### Task 2: Copy the `backend/` tree with excludes

**Files:**
- Copy from: `C:\Users\Admin\loan-approval-ai-system\backend\`
- Copy to: `C:\Users\Admin\loan-approval-ai-system-cs50\backend\`

- [ ] **Step 1: Run robocopy with directory and file excludes**

Run:
```powershell
robocopy "C:\Users\Admin\loan-approval-ai-system\backend" "C:\Users\Admin\loan-approval-ai-system-cs50\backend" /E /XD node_modules venv .venv __pycache__ .pytest_cache .mypy_cache staticfiles media .git models htmlcov .ruff_cache /XF *.pyc *.joblib *.db *.sqlite3 *.log .env
```
Expected: robocopy exits with code `<8` (success). Codes 0-7 are success in robocopy; only `>=8` is failure. Capture the exit code with `$LASTEXITCODE` if needed.

- [ ] **Step 2: Verify no excluded directories leaked**

Run:
```powershell
$leaks = @()
foreach ($dir in @('node_modules','venv','.venv','__pycache__','.pytest_cache','.mypy_cache','models','htmlcov','.git')) {
    $found = Get-ChildItem -Path "C:\Users\Admin\loan-approval-ai-system-cs50\backend" -Recurse -Directory -Filter $dir -ErrorAction SilentlyContinue
    if ($found) { $leaks += "$dir : $($found.Count) found" }
}
if ($leaks.Count -eq 0) { Write-Output "OK-no-leaks" } else { $leaks }
```
Expected: `OK-no-leaks`.

- [ ] **Step 3: Verify key files copied**

Run:
```powershell
foreach ($f in @('manage.py','config\settings\base.py','apps\ml_engine\services\predictor.py','apps\email_engine\services\email_generator.py','apps\agents\tasks.py','docs\MODEL_CARD.md')) {
    if (Test-Path "C:\Users\Admin\loan-approval-ai-system-cs50\backend\$f") { Write-Output "OK $f" } else { Write-Output "MISSING $f" }
}
```
Expected: all `OK` lines.

**No commit yet.**

---

### Task 3: Copy the `frontend/` tree with excludes

**Files:**
- Copy from: `C:\Users\Admin\loan-approval-ai-system\frontend\`
- Copy to: `C:\Users\Admin\loan-approval-ai-system-cs50\frontend\`

- [ ] **Step 1: Run robocopy**

Run:
```powershell
robocopy "C:\Users\Admin\loan-approval-ai-system\frontend" "C:\Users\Admin\loan-approval-ai-system-cs50\frontend" /E /XD node_modules .next dist coverage .git playwright-report test-results .turbo /XF *.log .env .env.local
```
Expected: exit code `<8`.

- [ ] **Step 2: Verify no excluded directories leaked**

Run:
```powershell
$leaks = @()
foreach ($dir in @('node_modules','.next','dist','coverage','playwright-report','.git')) {
    $found = Get-ChildItem -Path "C:\Users\Admin\loan-approval-ai-system-cs50\frontend" -Recurse -Directory -Filter $dir -ErrorAction SilentlyContinue
    if ($found) { $leaks += "$dir : $($found.Count) found" }
}
if ($leaks.Count -eq 0) { Write-Output "OK-no-leaks" } else { $leaks }
```
Expected: `OK-no-leaks`.

- [ ] **Step 3: Verify key files copied**

Run:
```powershell
foreach ($f in @('package.json','tsconfig.json','next.config.js','tailwind.config.js','src\app\page.tsx','src\app\dashboard\page.tsx')) {
    if (Test-Path "C:\Users\Admin\loan-approval-ai-system-cs50\frontend\$f") { Write-Output "OK $f" } else { Write-Output "MISSING $f" }
}
```
Expected: all `OK` lines.

**No commit yet.**

---

### Task 4: Copy `tools/`, `workflows/`, and the top-level `docs/` tree

**Files:**
- Copy from: `C:\Users\Admin\loan-approval-ai-system\{tools,workflows,docs}\`
- Copy to: `C:\Users\Admin\loan-approval-ai-system-cs50\{tools,workflows,docs}\`

- [ ] **Step 1: Copy tools**

Run:
```powershell
robocopy "C:\Users\Admin\loan-approval-ai-system\tools" "C:\Users\Admin\loan-approval-ai-system-cs50\tools" /E /XD __pycache__ .pytest_cache /XF *.pyc *.log
```
Expected: exit code `<8`.

- [ ] **Step 2: Copy workflows**

Run:
```powershell
robocopy "C:\Users\Admin\loan-approval-ai-system\workflows" "C:\Users\Admin\loan-approval-ai-system-cs50\workflows" /E /XD .git /XF *.log
```
Expected: exit code `<8`.

- [ ] **Step 3: Copy docs (selective — exclude internal planning + superpowers spec/plan dirs)**

Run:
```powershell
robocopy "C:\Users\Admin\loan-approval-ai-system\docs" "C:\Users\Admin\loan-approval-ai-system-cs50\docs" /E /XD .git superpowers /XF *.log
```
Expected: exit code `<8`.

Rationale for excluding `docs/superpowers/`: this is internal planning material (the spec and this plan itself) — graders don't need to see the meta-process documents.

- [ ] **Step 4: Verify key files copied**

Run:
```powershell
foreach ($f in @('tools\train_model.py','tools\evaluate_model.py','workflows','docs\runbooks\README.md','docs\DESIGN_JOURNEY.md')) {
    if (Test-Path "C:\Users\Admin\loan-approval-ai-system-cs50\$f") { Write-Output "OK $f" } else { Write-Output "MISSING $f" }
}
```
Expected: all `OK` lines.

**No commit yet.**

---

### Task 5: Copy root config files

**Files:**
- Copy from: `C:\Users\Admin\loan-approval-ai-system\{docker-compose.yml, .env.example, LICENSE, .gitignore}`
- Copy to: `C:\Users\Admin\loan-approval-ai-system-cs50\` (root)

- [ ] **Step 1: Copy each root file**

Run:
```powershell
$dest = "C:\Users\Admin\loan-approval-ai-system-cs50"
foreach ($f in @('docker-compose.yml','.env.example','LICENSE','.gitignore')) {
    $src = "C:\Users\Admin\loan-approval-ai-system\$f"
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination $dest -Force
        Write-Output "copied $f"
    } else {
        Write-Output "MISSING-SOURCE $f"
    }
}
```
Expected: 4 `copied` lines. If `LICENSE` is `MISSING-SOURCE`, that is acceptable — the project may not have one yet and we can skip; do not fabricate a license.

- [ ] **Step 2: Verify**

Run:
```powershell
foreach ($f in @('docker-compose.yml','.env.example','.gitignore')) {
    if (Test-Path "C:\Users\Admin\loan-approval-ai-system-cs50\$f") { Write-Output "OK $f" } else { Write-Output "MISSING $f" }
}
```
Expected: all 3 `OK`. (LICENSE may be optional.)

- [ ] **Step 3: Confirm `.env` (real secrets) is NOT present**

Run:
```powershell
if (Test-Path "C:\Users\Admin\loan-approval-ai-system-cs50\.env") {
    Write-Output "FAIL .env present — delete it now"
    Remove-Item "C:\Users\Admin\loan-approval-ai-system-cs50\.env" -Force
    Write-Output "deleted"
} else {
    Write-Output "OK no .env"
}
```
Expected: `OK no .env`. If anything else, abort and investigate.

**No commit yet.**

---

### Task 6: Initialize git in the new folder and make the first commit

**Files:**
- Create: `C:\Users\Admin\loan-approval-ai-system-cs50\.git\` (init)

- [ ] **Step 1: Run `git init` in the new folder**

Run:
```powershell
git -C "C:\Users\Admin\loan-approval-ai-system-cs50" init -b main 2>&1
```
Expected: `Initialized empty Git repository in ...`. If git refuses `-b main` (older git), drop the `-b main` flag — default branch is fine.

- [ ] **Step 2: Stage everything**

Run:
```powershell
git -C "C:\Users\Admin\loan-approval-ai-system-cs50" add .
```
Expected: silent success.

- [ ] **Step 3: Verify what's staged (sanity check — should be a lot, but should not include excluded artifacts)**

Run:
```powershell
git -C "C:\Users\Admin\loan-approval-ai-system-cs50" status --short | Measure-Object -Line | Select-Object -ExpandProperty Lines
```
Expected: a large number (likely 500-3000 entries). Spot-check a few with:
```powershell
git -C "C:\Users\Admin\loan-approval-ai-system-cs50" status --short | Select-Object -First 5
```

- [ ] **Step 4: Confirm no `.joblib`, `node_modules`, or `.env` is staged**

Run:
```powershell
$bad = git -C "C:\Users\Admin\loan-approval-ai-system-cs50" status --short | Select-String -Pattern "(node_modules|\.joblib|\bvenv\b|\.next/|__pycache__|^A\s+\.env$|^A\s+\.env)" -CaseSensitive:$false
if ($bad) { Write-Output "FAIL bad staged:"; $bad } else { Write-Output "OK clean stage" }
```
Expected: `OK clean stage`.

- [ ] **Step 5: Commit**

Run:
```powershell
git -C "C:\Users\Admin\loan-approval-ai-system-cs50" commit -m "chore: initial CS50x final project bundle (source copy)"
```
Expected: commit succeeds with stats.

---

## Phase 2 — Documentation

### Task 7: Write `README.md`

**Files:**
- Create: `C:\Users\Admin\loan-approval-ai-system-cs50\README.md`

CS50 requires the README to include Project Title, Video Demo URL, and Description. Target ~1050 words.

- [ ] **Step 1: Write the full README contents**

Write to `C:\Users\Admin\loan-approval-ai-system-cs50\README.md` exactly:

```markdown
# Loan Approval AI System

> A production-realistic 3-level AI loan-approval system: ML predictions, LLM-generated emails, and an agentic orchestrator with fairness gates and model risk management.

#### Video Demo: `[YouTube unlisted URL — fill in after recording]`

#### Description:

This is my CS50x final project: a full-stack loan-approval system that demonstrates three levels of AI integration on top of a Django + Next.js web application. It was inspired by Sajjaad Khader's video *"The ONLY Coding Project That Will Get You Hired in 2026 (AI Cheatcode)"* featuring Marinella Proy, but extended substantially beyond the tutorial scope into a production-realistic system with model risk management, fairness gates, drift monitoring, and roughly 190 atomic pull requests of iteration. The project is built for an Australian retail-lending context: borrowers apply, a Random-Forest plus XGBoost ensemble predicts approval probability, an LLM generates a compliant approval or denial email with guardrails, and an agentic orchestrator chains bias detection and next-best-offer recommendations on denied applications.

##### The three levels

**Level 1 — ML predictions.** The `ml_engine` Django app generates synthetic Australian-lending data with realistic feature distributions (employment status, postcode, debt-to-income, asset position), trains a Random-Forest plus XGBoost ensemble on an 80 / 10 / 10 train / validation / test split, and serves predictions through a versioned `ModelVersion` registry. The trainer emits per-decile calibration tables, PSI-by-feature drift baselines, and a fairness audit (Approval-Odds Disparity) per model version. Inference happens through `backend/apps/ml_engine/services/predictor.py`, which loads the active model bundle from disk and returns a calibrated probability plus the top contributing features.

**Level 2 — LLM email automation.** The `email_engine` app generates approval and denial emails through Anthropic's Claude API. Every email passes through a guardrail layer that strips apology language (a real Australian-lending compliance preference), runs URL allowlisting on any model-generated links, and HTML-escapes user data. A template-first mode keeps costs predictable; the Claude API mode is gated behind `EMAIL_USE_CLAUDE_API=true` and capped at a configurable daily spend.

**Level 3 — Agentic orchestrator.** The `agents` app runs a Celery task that chains: ML prediction, then email generation, then bias-detection scoring, then a next-best-offer recommendation on denials, then a human-review queue on bias flags. A single `AgentRun` record captures the whole trace.

##### Tech stack

- **Backend:** Python 3.11, Django 5, Django REST Framework, Celery + Redis (separate queues for ML / email / agents), PostgreSQL 16, scikit-learn, XGBoost, Anthropic Claude API.
- **Frontend:** TypeScript, React 18, Next.js (App Router), shadcn/ui, Tailwind CSS, TanStack Query with polling for async results.
- **Infrastructure:** Docker Compose orchestration (8 core containers plus 5 monitoring), Prometheus + Grafana for SLO dashboards, Sentry for error tracking.
- **Testing:** pytest with hypothesis, Vitest, Playwright snapshot tests, k6 for load testing, mypy on the Arm C extraction modules.

This stack covers CS50's core teachings — Python, SQL, HTML, CSS, JavaScript — and extends them into production realism.

##### What each major file does

- **`backend/manage.py`** — Django's standard CLI entry point.
- **`backend/config/settings/base.py`** — Core Django settings: installed apps, middleware, REST Framework config, Celery routing, model-version registry path. Split into `development.py` and `production.py` for env-specific overrides.
- **`backend/apps/accounts/`** — JWT-based authentication with three roles (admin / officer / customer), customer label maps extracted into a dedicated module.
- **`backend/apps/loans/`** — Loan application CRUD, dashboard stats, status workflow.
- **`backend/apps/ml_engine/`** — Data generation (`data_generator.py`), training pipeline, the prediction service (`services/predictor.py`), drift monitoring (PSI, decile analysis), MRM (Model Risk Management) dossier generator, fairness gates with `warn | block | off` modes.
- **`backend/apps/email_engine/`** — Email generation via Claude (`services/email_generator.py`), template fallback, Gmail-safe HTML renderer, persistence and lifecycle, URL allowlist (`_safe_url`), no-apology guardrail.
- **`backend/apps/agents/tasks.py`** — The orchestrator Celery task that chains prediction, email, bias check, next-best-offer, and human-review queue.
- **`frontend/src/app/page.tsx`** — Customer entry point.
- **`frontend/src/app/dashboard/`** — Officer dashboard, model-metrics page (with drift tiles, fairness banners, MRM dossier viewer), admin pages.
- **`tools/`** — Standalone Python scripts: `generate_synthetic_data.py`, `train_model.py`, `evaluate_model.py`, `compare_calibrations.py`, `test_claude_api.py`, `check_file_sizes.py`.
- **`workflows/`** — Markdown SOPs for the WAT (Workflows-Agents-Tools) framework the project follows.

##### Design choices and rationale

- **WAT framework (Workflows / Agents / Tools):** keeps probabilistic AI (workflows and agents) separate from deterministic execution (tools). Each Django service is a "tool" by design — testable, idempotent, no LLM calls hidden inside.
- **Service-layer pattern:** views are thin; business logic lives in `apps/<name>/services/`. Easier to unit-test, easier to reuse from Celery tasks.
- **Separate Celery queues** (`ml`, `email`, `agents`) so CPU-heavy ML work doesn't head-of-line-block IO-bound email and agent tasks.
- **Model versioning via `ModelVersion.is_active`:** model artifacts on disk, metadata in Postgres; switching algorithms is one database row update plus a reload.
- **Frontend polling for async results:** TanStack Query polls `/tasks/{id}/status/` every 2 seconds for Celery results instead of WebSockets — simpler, predictable, sufficient for a loan-decision UX.
- **Guardrails on every LLM output:** apology-language stripper, URL allowlist, HTML escape — defence-in-depth against compliance regressions.
- **Fairness gates default to `warn`, flip to `block` with one config change** — regulator-friendly, opt-in strictness.

##### Beyond the reference video

The reference video stops at next-best-offer plus bias detection. This project adds:

- **MRM dossiers** generated per `ModelVersion` capturing calibration, PSI baselines, fairness audit, decile analysis, and a compliance banner — designed against APRA CPS 230 model-risk guidance.
- **Fairness gates** (`warn | block | off`) blocking model promotion when Approval-Odds Disparity exceeds thresholds.
- **PSI drift monitoring** with per-feature decile analysis, exposed as drift tiles on the model-metrics dashboard.
- **Counterfactual explanations** for denied applications.
- **Production observability:** Grafana SLO dashboard, Sentry, Prometheus metrics, k6 load tests, smoke-end-to-end workflow on `workflow_dispatch`.
- **Roughly 190 atomic pull requests** of polish, adversarial code review responses, and senior-review iterations.

##### AI Usage Acknowledgement

This project was built with AI assistance, in honest compliance with CS50's policy on AI tools. I designed the system, made every architectural and product decision, did initial scaffolding, and integrated every change. I used **Claude Code (Anthropic)** as a pair-programming implementation accelerator and **Codex** as an adversarial code reviewer at key milestones. Each of the roughly 190 pull requests was reviewed and merged by me. Full attribution and a breakdown of *"what I did vs. what AI did"* is in `AI_USAGE.md` at the repo root, with inline citation comments on key entry-point files.

##### How to run locally

1. `cp .env.example .env` and fill in `ANTHROPIC_API_KEY` and Postgres credentials.
2. `docker compose up --build`
3. Visit `http://localhost:3000` (frontend) and `http://localhost:8000` (API).
```

- [ ] **Step 2: Verify word count is at least 750**

Run:
```powershell
$content = Get-Content "C:\Users\Admin\loan-approval-ai-system-cs50\README.md" -Raw
$wordCount = ($content -split '\s+' | Where-Object { $_ -ne '' }).Count
Write-Output "word count: $wordCount"
if ($wordCount -lt 750) { Write-Output "FAIL below threshold" } else { Write-Output "OK above threshold" }
```
Expected: word count around 900-1100; status `OK above threshold`.

**No commit yet** — commit after Task 9 with all three docs together.

---

### Task 8: Write `AI_USAGE.md`

**Files:**
- Create: `C:\Users\Admin\loan-approval-ai-system-cs50\AI_USAGE.md`

- [ ] **Step 1: Write the full AI_USAGE contents**

Write to `C:\Users\Admin\loan-approval-ai-system-cs50\AI_USAGE.md` exactly:

```markdown
# AI Usage Acknowledgement

This document fulfills the CS50x honor-code requirement to cite AI tool usage.

## Tools used

- **Claude Code (Anthropic)** — primary implementation assistant across backend, frontend, tests, and documentation. Specifically: Claude Opus 4.7 was used in pair-programming sessions throughout the project's lifecycle.
- **Codex (via Claude Code plugin)** — adversarial code reviewer invoked at key milestones (multiple PR review rounds on the codex-adversarial-response branches).

## My contribution

- **Project conception:** chose the domain (Australian retail lending), picked the 3-level reference structure, identified what to build beyond the tutorial.
- **Architecture decisions:** WAT framework, service-layer pattern, Celery queue topology, model-versioning strategy, fairness-gate three-mode design, MRM dossier scope.
- **Initial scaffolding** and project setup.
- **Requirements definition** for every feature — what guardrails to enforce, what compliance signals to emit, how strict gates should default.
- **Code review of every commit** — roughly 190 pull requests reviewed and merged. I caught regressions including the email apology-language regression, the lender-replica honesty issue, the drift-tile rendering bug, and the realism gaps in the synthetic data generator.
- **Multi-round adversarial review responses** — fielded Codex review feedback in stacked rounds and made the call on what to fix vs. defer.
- **Product / scope decisions** — when to ship a release tag, when to defer, what to add to MODEL_CARD, how to phrase regulator-facing language.
- **Production debugging** — diagnosed production-realism issues, walked the synthetic data through real audit catalogues, fixed the URL-allowlist defense-in-depth gap.

## AI contribution

- **Implementation** of features from my designs.
- **Boilerplate generation** — Django models, serializers, frontend components, test scaffolding.
- **Test scaffolding** — pytest cases with hypothesis, Vitest snapshots, Playwright content tests.
- **Refactoring suggestions** — large file splits during the Arm C extraction work (predictor.py extracted from 1217 lines into 436 across 10 modules).
- **Error-trace analysis** assistance during debugging.

## How I directed AI

- **Feature-by-feature specifications** through brainstorming and planning phases.
- **Iterative pair-programming review** — every change came as a pull request that I reviewed before merge.
- **Regression catching** — I read diffs, ran the system, and flagged issues AI missed.
- **Gate-keeping ship decisions** — every release was my call.

## Honor-code compliance

- This document.
- A dedicated "AI Usage Acknowledgement" section in `README.md`.
- Inline citation comments on key entry-point files:
  - `backend/manage.py`
  - `backend/config/settings/base.py`
  - `backend/apps/ml_engine/services/predictor.py`
  - `backend/apps/email_engine/services/email_generator.py`
  - `backend/apps/agents/tasks.py`
  - `frontend/src/app/page.tsx`
  - `frontend/src/app/dashboard/page.tsx`
  - `tools/train_model.py`
- All AI-generated code reviewed by me before merge.

This usage pattern matches what CS50 explicitly permits: AI as *"amplifying, not supplanting"* my productivity.
```

- [ ] **Step 2: Verify file exists and is non-empty**

Run:
```powershell
$f = "C:\Users\Admin\loan-approval-ai-system-cs50\AI_USAGE.md"
if ((Test-Path $f) -and ((Get-Item $f).Length -gt 0)) { Write-Output "OK" } else { Write-Output "FAIL" }
```
Expected: `OK`.

---

### Task 9: Write `VIDEO_SCRIPT.md` and commit Phase 2 work

**Files:**
- Create: `C:\Users\Admin\loan-approval-ai-system-cs50\VIDEO_SCRIPT.md`

- [ ] **Step 1: Write the full VIDEO_SCRIPT contents**

Write to `C:\Users\Admin\loan-approval-ai-system-cs50\VIDEO_SCRIPT.md` exactly:

```markdown
# Video Script — CS50x Final Project (≤3 min)

> **Hard cap:** 180 seconds (CS50 rule). Aim for ~170 seconds including the opening.
> **Format:** YouTube unlisted upload. Screen recording with voiceover.

## Required opening (15 s)

Title card on screen showing:

```
Project Title:   Loan Approval AI System
Name:            [FILL IN — Neville Zeng or Eddie Zeng]
GitHub:          zeroyuekun
edX:             [FILL IN — your edX username]
City, Country:   [FILL IN — e.g., Sydney, Australia]
Date recorded:   [FILL IN — e.g., 2026-05-14]
```

**Voiceover:**
> "Hi, I'm [Name]. This is my CS50 final project: the Loan Approval AI System."

## The problem (20 s)

**Voiceover:**
> "Loan approval is high-stakes and slow when it's manual. The reference for this project — Sajjaad Khader's video on a 3-level loan-approval system — shows that automating prediction, communication, and decisioning is the kind of project that signals hireable AI skills. I extended that into a production-realistic system for Australian retail lending."

## Demo (90 s)

**Screen recording:**

1. **Submit application** (10 s) — officer dashboard, enter a borrower's details, submit.
2. **ML prediction renders** (15 s) — calibrated probability plus top contributing features.
3. **Email auto-generated** (20 s) — show the approval email preview, then a denied case showing the denial email with the next-best-offer.
4. **Orchestrator trace** (15 s) — flip to the `AgentRun` detail showing prediction → email → bias check → NBO → status.
5. **Model metrics dashboard** (30 s) — drift tiles, fairness banner (in `warn` mode), MRM dossier link, decile calibration table.

## Beyond the tutorial (30 s)

**Voiceover:**
> "Beyond the reference, this system has: model risk management dossiers generated per model version, fairness gates with warn / block / off modes, PSI-based drift monitoring with per-feature decile analysis, counterfactual explanations on denials, and full Docker orchestration with Prometheus and Grafana observability. The repo has roughly 190 pull requests of polish, adversarial code review responses, and senior-review iterations."

## AI Usage Acknowledgement (10 s)

**Voiceover:**
> "I used Claude as an implementation accelerator and Codex as an adversarial reviewer. Design, review, debugging, and every scope decision were mine. Detailed in AI_USAGE.md."

## Close (5 s)

**Voiceover:**
> "Source code at github.com/zeroyuekun/loan-approval-ai-system. Thanks for watching."

End card: GitHub URL on screen.

---

**Total runtime: ~170 s** — comfortably within the CS50 cap.

## Recording checklist before you press upload

- [ ] Title-card placeholders filled in (Name, edX, City/Country, Date).
- [ ] Voiceover clean (no background noise).
- [ ] Screen recording in 1080p+.
- [ ] Total runtime ≤180 s.
- [ ] Upload to YouTube, set visibility to **Unlisted** (not Private — graders need to see it).
- [ ] Copy the YouTube URL into `README.md` (replace the placeholder).
```

- [ ] **Step 2: Verify file exists and is non-empty**

Run:
```powershell
$f = "C:\Users\Admin\loan-approval-ai-system-cs50\VIDEO_SCRIPT.md"
if ((Test-Path $f) -and ((Get-Item $f).Length -gt 0)) { Write-Output "OK" } else { Write-Output "FAIL" }
```
Expected: `OK`.

- [ ] **Step 3: Commit all three CS50 docs**

Run:
```powershell
git -C "C:\Users\Admin\loan-approval-ai-system-cs50" add README.md AI_USAGE.md VIDEO_SCRIPT.md
git -C "C:\Users\Admin\loan-approval-ai-system-cs50" commit -m "docs(cs50): README, AI_USAGE, VIDEO_SCRIPT for submission"
```
Expected: commit succeeds with 3 files changed.

---

## Phase 3 — Inline AI Citations

For each entry-point file, prepend a 3-line citation comment block. Use Python `#` syntax for `.py` files and `//` for `.ts`/`.tsx` files.

**Python citation block (paste at top of file, after any `#!shebang` if present):**

```python
# AI Usage: Significant portions of this file were implemented with AI assistance
# (Claude Code by Anthropic). Design, review, and integration by the author.
# Full attribution: AI_USAGE.md at repo root.
```

**TypeScript citation block (paste at the very top of the file):**

```typescript
// AI Usage: Significant portions of this file were implemented with AI assistance
// (Claude Code by Anthropic). Design, review, and integration by the author.
// Full attribution: AI_USAGE.md at repo root.
```

---

### Task 10: Add Python citations to 5 backend files

**Files:**
- Modify: `C:\Users\Admin\loan-approval-ai-system-cs50\backend\manage.py`
- Modify: `C:\Users\Admin\loan-approval-ai-system-cs50\backend\config\settings\base.py`
- Modify: `C:\Users\Admin\loan-approval-ai-system-cs50\backend\apps\ml_engine\services\predictor.py`
- Modify: `C:\Users\Admin\loan-approval-ai-system-cs50\backend\apps\email_engine\services\email_generator.py`
- Modify: `C:\Users\Admin\loan-approval-ai-system-cs50\backend\apps\agents\tasks.py`

- [ ] **Step 1: Read each file's current first line(s) to know if there's a shebang**

For each of the 5 files, read the first 3 lines. The Python citation block goes:
- AFTER a `#!/usr/bin/env python` shebang if one exists (line 2+)
- BEFORE everything else otherwise (line 1)

`manage.py` typically has `#!/usr/bin/env python` — citation goes on line 2 onwards.

The other 4 files (settings, services, tasks) typically have no shebang — citation goes at line 1.

- [ ] **Step 2: Add citation to `manage.py`**

Use the `Edit` tool to prepend the citation block. If `manage.py` starts with `#!/usr/bin/env python` (it does in Django defaults), insert the citation block immediately after the shebang line. Find the first occurrence of:

```python
#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
```

Replace with:

```python
#!/usr/bin/env python
# AI Usage: Significant portions of this file were implemented with AI assistance
# (Claude Code by Anthropic). Design, review, and integration by the author.
# Full attribution: AI_USAGE.md at repo root.
"""Django's command-line utility for administrative tasks."""
```

If the existing file does not match exactly (different docstring), adapt the unique-string match accordingly — but always keep the citation block in the same position (after shebang, before docstring/imports).

- [ ] **Step 3: Add citation to `config/settings/base.py`**

Read the first 3 lines first. Most Django settings files start with a docstring or imports. Prepend the citation block as new lines 1-3, pushing existing content down. Use the `Edit` tool to replace the first line of the file with:

```
# AI Usage: Significant portions of this file were implemented with AI assistance
# (Claude Code by Anthropic). Design, review, and integration by the author.
# Full attribution: AI_USAGE.md at repo root.
<original first line>
```

Where `<original first line>` is whatever the first line actually contains (read it first, then construct the Edit's `new_string` to include the citation plus the original).

- [ ] **Step 4: Add citation to `predictor.py`**

Same pattern as Step 3.

- [ ] **Step 5: Add citation to `email_generator.py`**

Same pattern as Step 3.

- [ ] **Step 6: Add citation to `agents/tasks.py`**

Same pattern as Step 3.

- [ ] **Step 7: Verify each Python file still parses (no syntax breakage)**

Run from a Python-available environment:
```powershell
foreach ($f in @(
    'backend\manage.py',
    'backend\config\settings\base.py',
    'backend\apps\ml_engine\services\predictor.py',
    'backend\apps\email_engine\services\email_generator.py',
    'backend\apps\agents\tasks.py'
)) {
    $full = "C:\Users\Admin\loan-approval-ai-system-cs50\$f"
    $r = python -c "import ast, sys; ast.parse(open(r'$full', encoding='utf-8').read()); print('OK')" 2>&1
    Write-Output "$f : $r"
}
```
Expected: all 5 lines end in `OK`.

If Python isn't on PATH, alternative: use `py -c "..."` or skip this check and rely on the final smoke-test in Phase 4.

---

### Task 11: Add TypeScript citations to 2 frontend files

**Files:**
- Modify: `C:\Users\Admin\loan-approval-ai-system-cs50\frontend\src\app\page.tsx`
- Modify: `C:\Users\Admin\loan-approval-ai-system-cs50\frontend\src\app\dashboard\page.tsx`

- [ ] **Step 1: Read `frontend/src/app/page.tsx` first 3 lines**

Use the `Read` tool with `offset: 1, limit: 3`. The TypeScript citation block goes at line 1 (no shebangs in TSX).

- [ ] **Step 2: Prepend citation to `page.tsx`**

Use the `Edit` tool. Match the first line of the file as `old_string`, and prepend the TS citation block in `new_string`.

```typescript
// AI Usage: Significant portions of this file were implemented with AI assistance
// (Claude Code by Anthropic). Design, review, and integration by the author.
// Full attribution: AI_USAGE.md at repo root.
<original first line>
```

- [ ] **Step 3: Prepend citation to `frontend/src/app/dashboard/page.tsx`**

Same pattern. The dashboard `page.tsx` typically starts with `"use client";` or a `import` statement — insert the citation block above it.

- [ ] **Step 4: Verify TSX files still parse (syntax check)**

Quick check — confirm the citation comment is on lines 1-3 and the original content starts on line 4:

```powershell
foreach ($f in @('frontend\src\app\page.tsx','frontend\src\app\dashboard\page.tsx')) {
    $lines = Get-Content "C:\Users\Admin\loan-approval-ai-system-cs50\$f" -TotalCount 5
    Write-Output "--- $f ---"
    $lines
}
```
Expected: each file shows the 3-line `// AI Usage:` block followed by original content.

---

### Task 12: Add citation to one representative `tools/` script

**Files:**
- Modify: `C:\Users\Admin\loan-approval-ai-system-cs50\tools\train_model.py`

This is the representative script per the spec. The other tools scripts are AI-assisted too, but per the spec we tag one as the sample plus rely on `AI_USAGE.md` to cover the rest pragmatically.

- [ ] **Step 1: Read `tools/train_model.py` first 3 lines**

Use the `Read` tool.

- [ ] **Step 2: Prepend Python citation block**

Use the `Edit` tool with the Python citation block, same pattern as Task 10.

- [ ] **Step 3: Verify the file still parses**

```powershell
python -c "import ast; ast.parse(open(r'C:\Users\Admin\loan-approval-ai-system-cs50\tools\train_model.py', encoding='utf-8').read()); print('OK')"
```
Expected: `OK`.

---

### Task 13: Commit all citations

- [ ] **Step 1: Stage and commit**

Run:
```powershell
git -C "C:\Users\Admin\loan-approval-ai-system-cs50" add backend frontend tools
git -C "C:\Users\Admin\loan-approval-ai-system-cs50" status --short
```
Expected: ~8 modified files listed.

- [ ] **Step 2: Commit**

Run:
```powershell
git -C "C:\Users\Admin\loan-approval-ai-system-cs50" commit -m "chore(cs50): AI usage citation headers on key entry-point files"
```
Expected: commit succeeds.

---

## Phase 4 — Verification

### Task 14: Verify README word count meets CS50 threshold

- [ ] **Step 1: Run word count again as final check**

Run:
```powershell
$content = Get-Content "C:\Users\Admin\loan-approval-ai-system-cs50\README.md" -Raw
$wordCount = ($content -split '\s+' | Where-Object { $_ -ne '' }).Count
Write-Output "Final README word count: $wordCount"
if ($wordCount -ge 750) { Write-Output "OK ≥750 threshold" } else { Write-Output "FAIL below 750" }
```
Expected: word count 900-1100; status `OK ≥750 threshold`.

- [ ] **Step 2: Confirm README contains the CS50-required headers**

Run:
```powershell
$content = Get-Content "C:\Users\Admin\loan-approval-ai-system-cs50\README.md" -Raw
$ok = $true
foreach ($h in @('# Loan Approval AI System','Video Demo','Description')) {
    if ($content -notmatch [regex]::Escape($h)) { Write-Output "FAIL missing: $h"; $ok = $false }
}
if ($ok) { Write-Output "OK all CS50 sections present" }
```
Expected: `OK all CS50 sections present`.

---

### Task 15: Secret scan and leaked-artifact check

- [ ] **Step 1: Confirm `.env` is not present in the bundle**

Run:
```powershell
$envFiles = Get-ChildItem -Path "C:\Users\Admin\loan-approval-ai-system-cs50" -Recurse -Force -Filter ".env" -File -ErrorAction SilentlyContinue
if ($envFiles) { Write-Output "FAIL .env files found:"; $envFiles.FullName } else { Write-Output "OK no .env" }
```
Expected: `OK no .env`.

- [ ] **Step 2: Scan `.env.example` for live-looking secrets**

Run:
```powershell
$bad = Select-String -Path "C:\Users\Admin\loan-approval-ai-system-cs50\.env.example" -Pattern "sk-[A-Za-z0-9]{20,}", "pk_live_", "AKIA[0-9A-Z]{16}", "-----BEGIN" -ErrorAction SilentlyContinue
if ($bad) { Write-Output "FAIL suspected secrets:"; $bad } else { Write-Output "OK .env.example clean" }
```
Expected: `OK .env.example clean`. If FAIL, redact the offending values to placeholders like `your-key-here` before continuing.

- [ ] **Step 3: Confirm no leaked excluded directories anywhere**

Run:
```powershell
$leaks = @()
foreach ($dir in @('node_modules','venv','.venv','__pycache__','.next','.pytest_cache','models')) {
    $found = Get-ChildItem -Path "C:\Users\Admin\loan-approval-ai-system-cs50" -Recurse -Directory -Filter $dir -ErrorAction SilentlyContinue
    if ($found) { $leaks += "$dir : $($found.Count)" }
}
if ($leaks.Count -eq 0) { Write-Output "OK no leaks" } else { Write-Output "FAIL leaks:"; $leaks }
```
Expected: `OK no leaks`.

- [ ] **Step 4: Confirm no `.joblib` or `.pyc` files leaked**

Run:
```powershell
$bad = Get-ChildItem -Path "C:\Users\Admin\loan-approval-ai-system-cs50" -Recurse -Include "*.joblib","*.pyc" -File -ErrorAction SilentlyContinue
if ($bad) { Write-Output "FAIL bad files:"; $bad.FullName | Select-Object -First 10 } else { Write-Output "OK no bad files" }
```
Expected: `OK no bad files`.

---

### Task 16: (Optional) Docker smoke test

This is optional. Skip if Docker isn't running locally or if time is tight.

- [ ] **Step 1: Check Docker is running**

Run:
```powershell
docker --version 2>&1; docker info 2>&1 | Select-Object -First 5
```
Expected: docker version printed and `Containers:` line visible. If Docker isn't running, skip this task and mark it complete without running compose.

- [ ] **Step 2: Bring the stack up (in detached mode, time-limited)**

Only run if Step 1 succeeded:
```powershell
$dest = "C:\Users\Admin\loan-approval-ai-system-cs50"
Copy-Item "$dest\.env.example" "$dest\.env" -Force
# Note: .env now exists but isn't committed (gitignore should handle this)
docker compose -f "$dest\docker-compose.yml" up -d --build
```
Expected: containers come up. Allow ~60 s.

- [ ] **Step 3: Hit the API health endpoint**

Run:
```powershell
Start-Sleep -Seconds 30
try { (Invoke-WebRequest -Uri "http://localhost:8000/api/health/" -TimeoutSec 10).StatusCode } catch { "FAIL: $_" }
```
Expected: `200` or close. If `FAIL`, investigate but do not block the submission — the static bundle still ships.

- [ ] **Step 4: Tear down**

Run:
```powershell
docker compose -f "$dest\docker-compose.yml" down
Remove-Item "$dest\.env" -Force -ErrorAction SilentlyContinue
```
Expected: containers stopped, `.env` removed so it doesn't get accidentally committed.

---

### Task 17: Final status summary

- [ ] **Step 1: Print final git log of the new repo**

Run:
```powershell
git -C "C:\Users\Admin\loan-approval-ai-system-cs50" log --oneline
```
Expected: 3 commits — initial bundle, CS50 docs, citation headers.

- [ ] **Step 2: Print final directory size and file count**

Run:
```powershell
$root = "C:\Users\Admin\loan-approval-ai-system-cs50"
$fileCount = (Get-ChildItem -Path $root -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notmatch '\\\.git\\' }).Count
$size = (Get-ChildItem -Path $root -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notmatch '\\\.git\\' } | Measure-Object -Property Length -Sum).Sum
Write-Output "files (excluding .git): $fileCount"
Write-Output "size (MB, excluding .git): $([math]::Round($size/1MB,1))"
```
Expected: somewhere in the range of 200-2000 files and 5-50 MB. If much larger, investigate what leaked.

- [ ] **Step 3: Print the user-action checklist**

This isn't code — surface it to the user as the handoff. Print:

```
SUBMISSION READINESS — USER TODO:
  [ ] Fill placeholders in VIDEO_SCRIPT.md (Name, edX username, City/Country, Date)
  [ ] Record the video (≤180 s) following VIDEO_SCRIPT.md
  [ ] Upload to YouTube as UNLISTED
  [ ] Paste the YouTube URL into README.md, replacing the placeholder
  [ ] Fill the CS50 submission form: https://forms.cs50.io/65ba090e-aba1-41de-a8f3-13f7701f399b
  [ ] cd to C:\Users\Admin\loan-approval-ai-system-cs50 and run: submit50 cs50/problems/2026/x/project
  [ ] Visit https://cs50.me/cs50x to confirm completion
  Deadline: 2026-12-31T23:59 UTC
```

---

## Self-Review (Plan Checklist)

After writing this plan, I verified:

- **Spec coverage:** Each of the 4 spec phases maps to a phase here (Scaffold+Copy → Phase 1; Documentation → Phase 2; Inline Citations → Phase 3; Verification → Phase 4). The 7-item acceptance criteria in the spec each map to at least one task here.
- **Placeholder scan:** No TBD/TODO/implement-later markers. The README/AI_USAGE/VIDEO_SCRIPT contents are fully embedded. The few `[FILL IN]` markers in VIDEO_SCRIPT.md are intentional user-data placeholders (Name, edX username, City/Country, Date) and are explicitly listed in the final user-todo step.
- **Type consistency:** File paths, file names, and command snippets are consistent across tasks. PowerShell syntax is used throughout. The citation comment block templates (Python `#`, TypeScript `//`) are defined once at the start of Phase 3 and reused.
- **Path verification:** Paths for `predictor.py`, `email_generator.py`, `tasks.py`, `settings/base.py`, `manage.py`, `page.tsx`, `dashboard/page.tsx`, `train_model.py` were verified to exist in the source tree before writing the plan.

---

## Out of scope

- Recording the video (user's task).
- Filing the CS50 form (user's task).
- Running `submit50` (user's task).
- Pushing the new folder to public GitHub (optional, post-submission).
- Touching the uncommitted `frontend/tsconfig.json` change on `feat/codex-adversarial-response` (separate workstream).
- Modifying the original `loan-approval-ai-system` repo.
