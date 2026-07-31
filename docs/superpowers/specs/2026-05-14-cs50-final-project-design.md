# CS50x Final Project Submission — Design Spec

**Date:** 2026-05-14
**Status:** Draft — pending user review
**Author:** Neville/Eddie Zeng (GitHub `zeroyuekun`)
**Topic:** Package the Loan Approval AI System for CS50x final project submission

---

## Context

The Loan Approval AI System (`zeroyuekun/loan-approval-ai-system`, currently at master `5c5bc39` with PR #183 in flight) is a working full-stack project. It implements a 3-level system inspired by Sajjaad Khader's YouTube video "The ONLY Coding Project That Will Get You Hired in 2026 (AI Cheatcode)" featuring Marinella Proy:

1. **Level 1 — ML model:** Random Forest + Gradient Boosting (the project also has XGBoost) on loan data with 80/10/10 train/val/test split.
2. **Level 2 — LLM email:** Approval/denial email generation with guardrails against hallucination and bias.
3. **Level 3 — Agentic AI:** Bias-detection agent + Next-Best-Offer (NBO) agent on denial emails.

The project has extended substantially beyond the tutorial: MRM compliance dossiers, fairness gates with `warn|block|off` modes, drift monitoring (PSI + decile analysis), counterfactual explanations (Track C), full observability (Prometheus + Grafana), Docker orchestration, ~190 PRs of polish and adversarial review responses.

The user intends to submit this for CS50x final project. CS50's policy permits AI-assisted work provided (a) the "essence" is the student's own work and (b) AI tools are cited. The user's contribution — architecture decisions, initial scaffolding, ~190 PRs of review/iteration, production debugging, scope management — qualifies. This spec defines how to package the submission honestly and compliantly.

**Deadline:** 2026-12-31T23:59:00+00:00 (per CS50x 2026).

---

## Goals

1. Produce a sibling folder `C:\Users\Admin\loan-approval-ai-system-cs50` containing a curated, self-contained, `submit50`-ready bundle.
2. Include a CS50-compliant `README.md` (~750-1000 words) with all required sections.
3. Include `AI_USAGE.md` formally citing AI tools used — satisfies CS50's "cite any use of such tools" requirement.
4. Include `VIDEO_SCRIPT.md` providing a ≤3-minute storyboard with the required CS50 opening details.
5. Add brief AI-citation comment headers to ~5-10 key entry-point files (manage.py, settings, main views/services).
6. Honestly frame the user's contribution as design + scaffolding + integration + review + debugging — with AI as an implementation accelerator. No fabricated claims of skeleton code beyond what is generally true.
7. The submission must be `submit50`-ready when the user records the video and fills placeholders.

---

## Non-Goals

- Re-implementing the project from scratch.
- Stripping features for "simplicity" — the full scope is the submission's strength.
- Adding AI-citation comments to every file (overkill; CS50 grades pragmatically).
- Modifying the original `loan-approval-ai-system` repo (this is a separate folder; original stays as-is).
- Recording the video (user's responsibility post-spec).
- Running `submit50` or filing the CS50 form (user does this when ready).
- Touching the uncommitted `frontend/tsconfig.json` change on the current branch (separate scope).

---

## Approach

**Selected: Option A — Curated self-contained copy** (chosen 2026-05-14 by user).

A new sibling folder at `C:\Users\Admin\loan-approval-ai-system-cs50` containing a curated copy of source code (excluding build artifacts, secrets, and large binaries) with fresh CS50-compliant documentation on top. Fresh `git init` for clean history. `submit50` runs from this folder.

Rejected alternatives:
- **Option B (doc-only bundle)** — risks looking thin if grader doesn't follow GitHub link.
- **Option C (slim demo subset)** — hides exactly what makes the project exceed problem-set scope.

---

## Folder Structure

Target: `C:\Users\Admin\loan-approval-ai-system-cs50\` (sibling, not nested).

```
loan-approval-ai-system-cs50/
├── README.md                    # CS50-compliant, ~750-1000 words
├── AI_USAGE.md                  # Tool citations + workflow
├── VIDEO_SCRIPT.md              # 3-min storyboard + opening details
├── LICENSE                      # Copied from source (if exists; else MIT default)
├── .env.example                 # Sanitized config sample
├── .gitignore                   # Standard Python/Node ignores
├── docker-compose.yml           # Copied from source
├── backend/                     # Django + DRF + Celery
│   ├── manage.py                # WITH AI citation header
│   ├── config/                  # Django settings (settings/base.py with header)
│   ├── apps/                    # accounts, loans, ml_engine, email_engine, agents
│   ├── docs/MODEL_CARD.md       # ML model card (key reference doc)
│   ├── requirements/            # pip requirements files
│   └── Dockerfile
├── frontend/                    # Next.js + shadcn/ui
│   ├── src/                     # Source (page.tsx, dashboard, components)
│   ├── public/
│   ├── package.json
│   ├── tsconfig.json
│   ├── next.config.js
│   ├── tailwind.config.js
│   └── Dockerfile
├── tools/                       # Standalone Python scripts (WAT layer 3)
├── workflows/                   # Markdown SOPs (WAT layer 1)
└── docs/                        # Curated: runbooks/, DESIGN_JOURNEY.md, slo.md
```

---

## File Copy Rules

**Include:**
- `backend/**` excluding `__pycache__/`, `.pytest_cache/`, `*.pyc`, `venv/`, `.venv/`, `staticfiles/`, `media/`, `ml_engine/models/*.joblib`, `*.db`, `*.sqlite3`
- `frontend/{src,public}/**` plus root config files (`package.json`, `tsconfig.json`, `next.config.js`, `tailwind.config.js`, `postcss.config.js`, `.eslintrc*`, `Dockerfile`) — exclude `node_modules/`, `.next/`, `dist/`, `coverage/`
- `tools/**` (Python sources only; exclude `__pycache__/`)
- `workflows/**` (markdown SOPs — useful for graders to see the WAT framework)
- `backend/docs/MODEL_CARD.md` and `docs/{runbooks/, DESIGN_JOURNEY.md, engineering-journal.md, slo.md}`
- `docker-compose.yml`, all `Dockerfile`s
- `.env.example`, `.gitignore`, `LICENSE` if present

**Exclude:**
- `.git/`, `.planning/`, `.tmp/`
- `node_modules/`, all `venv/`, `.venv/`, `__pycache__/`, `.pytest_cache/`
- `ml_engine/models/*.joblib` and other large binaries
- `.env` (real secrets)
- `loadtests/` (not core to the 3-level story; will reference in README)
- Build outputs: `frontend/.next/`, `frontend/dist/`, `backend/staticfiles/`
- The original `README.md` (replaced by the new CS50 one)

The copy will be performed by a one-shot script (PowerShell `Copy-Item -Exclude`, or `robocopy` with `/XD` flags). Implementation detail for the plan phase.

---

## README.md Structure (~1000 words target)

CS50's required sections (verbatim from policy): **Project Title, Video Demo URL, Description**. We expand the Description into multiple subsections to comfortably exceed 750 words.

1. **# Loan Approval AI System** — title with one-line tagline
2. **#### Video Demo:** `[YouTube URL — fill in after recording]`
3. **#### Description:**
   - **What it is (~120w)** — A 3-level loan approval system: ML predictions, LLM-generated emails, agentic orchestrator. Inspired by Sajjaad Khader's "The ONLY Coding Project That Will Get You Hired in 2026" featuring Marinella Proy; extended significantly into a production-realistic system.
   - **The three levels (~200w)** — Level 1: Random Forest + XGBoost ensemble with 80/10/10 split. Level 2: Claude API generates approval/denial emails with guardrails. Level 3: Celery-based orchestrator chains prediction → email → bias detection → next-best-offer.
   - **Tech stack (~100w)** — Python (Django + DRF, Celery, Redis, scikit-learn, XGBoost), PostgreSQL, JavaScript/TypeScript (React 18, Next.js App Router, shadcn/ui, Tailwind, TanStack Query), HTML/CSS, Docker Compose, Prometheus/Grafana for observability. Hits CS50's core teachings (Python, SQL, web fundamentals, JS, HTML/CSS) and goes beyond.
   - **What each major file does (~250w)** — Walk through:
     - `backend/manage.py` — Django entry point
     - `backend/config/settings/` — base + dev/prod splits, env-driven config
     - `backend/apps/accounts/` — JWT auth, role-based access (admin/officer/customer)
     - `backend/apps/loans/` — application CRUD, status management, dashboards
     - `backend/apps/ml_engine/` — data generation, training pipeline, prediction service, drift monitoring (`services/predictor.py` is the core inference module)
     - `backend/apps/email_engine/` — Claude API integration with guardrails (`services/generator.py`)
     - `backend/apps/agents/` — bias detection, NBO recommender, orchestrator Celery task
     - `frontend/src/app/` — Next.js routes: customer dashboard, officer dashboard, admin metrics
     - `tools/` — standalone scripts (data generators, smoke tests, MRM dossier generator)
     - `workflows/` — markdown SOPs for the WAT (Workflows/Agents/Tools) framework
   - **Design choices and rationale (~150w)** — WAT framework (probabilistic AI for reasoning, deterministic code for execution); service layer pattern (thin views → services → external APIs); separate Celery queues by workload (ML/email/agents); model versioning via `ModelVersion.is_active` flag; frontend polling for async results; guardrails on every LLM output; fairness gates with `warn|block|off` modes for regulator-friendly defaults; MRM (Model Risk Management) compliance dossiers per Australian APRA CPS 230 guidance.
   - **Beyond the tutorial (~120w)** — The YouTube video stops at NBO + bias detection. This project adds: MRM compliance dossiers generated per model version, fairness gates blocking promotion when AOD exceeds thresholds, PSI-based drift monitoring with per-feature decile analysis, counterfactual explanations (Track C), comprehensive observability (Grafana SLO dashboard, Sentry, Prometheus), full Docker orchestration, ~190 PRs of polish and adversarial code review responses.
   - **AI Usage Acknowledgement (~80w)** — Explicit citation: I designed the system, did initial scaffolding, set requirements, and made every product/scope/architecture decision. I used Claude (Anthropic's coding assistant) to accelerate implementation, with Codex used as an adversarial code reviewer. Every change was reviewed and integrated by me. Full citation: `AI_USAGE.md`. This usage complies with CS50's honor code regarding AI tools.
   - **How to run locally (~30w)** — `cp .env.example .env`, fill in keys, `docker compose up`, visit `localhost:3000` (frontend) and `localhost:8000` (API).

**Total estimated: ~1050 words** — comfortably above the 750-word CS50 threshold.

---

## AI_USAGE.md Structure

- **Tools used:**
  - Claude Code (Anthropic) — primary implementation assistant across backend, frontend, tests
  - Codex (OpenAI via Claude Code plugin) — adversarial code reviewer at key milestones
- **My contribution:**
  - Project conception, domain choice (Australian lending), goal selection
  - Initial scaffolding and project setup
  - Architecture decisions: WAT framework, service layer pattern, queue topology, model versioning approach
  - Requirements definition for every feature
  - Code review of every commit (~190 PRs reviewed and merged)
  - Production debugging: drift tile regression, lender-replica honesty fix, email apology-language regression catch, fairness gate defaults
  - Scope/product decisions: when to ship, what to defer, MRM compliance scope, regulator-friendly defaults
  - Integration of feedback from multi-round adversarial code reviews
- **AI contribution:**
  - Implementation of features from my designs and specs
  - Boilerplate generation (Django models, serializers, frontend components)
  - Test scaffolding (pytest, Vitest, Playwright)
  - Refactoring suggestions
  - Error trace analysis and debugging assistance
- **How I directed AI:**
  - Feature-by-feature specifications via brainstorming + planning phases
  - Iterative pair-programming style review
  - Regression catching across PRs
  - Final gate-keeping on every ship decision
- **Honor code compliance:** This document + inline citations on key entry-point files (see `backend/manage.py`, `backend/config/settings/base.py`, etc.). All AI-generated code was reviewed before merge.

---

## VIDEO_SCRIPT.md Structure

A 3-minute storyboard (CS50 hard cap = 180s):

- **Opening (15s)** — Title card displaying:
  - Project Title: Loan Approval AI System
  - Name: `[Neville Zeng or Eddie Zeng — pick preferred]`
  - GitHub: `zeroyuekun`
  - edX: `[FILL IN]`
  - City, Country: `[FILL IN, e.g., Sydney, Australia]`
  - Date Recorded: `[FILL IN]`
  - Voiceover: "Hi, I'm [Name], this is my CS50 final project: Loan Approval AI System."
- **The problem (20s)** — Loan approval is high-stakes and slow when manual. The 3-level approach automates prediction, communication, and decisioning while keeping a human in the loop on fairness.
- **Demo (90s)** — Screen recording:
  - Officer submits new application → ML prediction renders
  - Email auto-generated, preview shown
  - Orchestrator runs (bias check → NBO if denied)
  - Dashboard updates with the decision
  - Model metrics page showing drift tiles, fairness gates, MRM dossier
- **Beyond tutorial (30s)** — Quick callout: MRM compliance dossiers, fairness gates with warn/block/off modes, drift monitoring, ~190 PRs of production hardening.
- **AI usage acknowledgement (10s)** — "I used Claude as an implementation accelerator; design, review, debugging, and scope decisions were mine. Detailed in AI_USAGE.md."
- **Close (15s)** — "Source: github.com/zeroyuekun/loan-approval-ai-system. Thanks for watching."

**Total: ~180s** — at the CS50 hard cap.

---

## Inline AI Citations (Code Comments)

Add a 3-4 line citation block to the top of these files:

| File | Language | Purpose |
|---|---|---|
| `backend/manage.py` | Python | Django entry point |
| `backend/config/settings/base.py` | Python | Settings core |
| `backend/apps/ml_engine/services/predictor.py` | Python | Core ML inference (verify path during execute) |
| `backend/apps/email_engine/services/generator.py` | Python | Claude API integration (verify path) |
| `backend/apps/agents/tasks.py` | Python | Orchestrator Celery task (verify path) |
| `frontend/src/app/page.tsx` | TSX | Frontend home |
| `frontend/src/app/dashboard/page.tsx` | TSX | Dashboard entry |
| `tools/` representative script | Python | One tool script as a sample |

**Python template:**
```python
# AI Usage: Significant portions of this file were implemented with AI assistance
# (Claude Code by Anthropic). Design, review, and integration by the author.
# Full attribution: AI_USAGE.md at repo root.
```

**TypeScript template:**
```typescript
// AI Usage: Significant portions of this file were implemented with AI assistance
// (Claude Code by Anthropic). Design, review, and integration by the author.
// Full attribution: AI_USAGE.md at repo root.
```

Note: Paths for `predictor.py`, `generator.py`, `tasks.py` are best-guess — the execute phase will verify exact paths and adjust if filenames differ in current code.

---

## Git Strategy

- Fresh `git init` inside `loan-approval-ai-system-cs50/` (no history from source repo).
- Initial commit: `chore: initial CS50x final project bundle`.
- `submit50` manages its own branch on a CS50 GitHub repo, so we don't need to push the new folder to GitHub for submission.
- Optional: user can `gh repo create loan-approval-ai-system-cs50 --public` post-submission for portfolio visibility (not in scope here).

The **design spec itself** (this file) is committed in the *main* repo at `docs/superpowers/specs/2026-05-14-cs50-final-project-design.md`. Branching for that commit: create a fresh branch `feat/cs50-final-project` off `master` rather than landing on `feat/codex-adversarial-response`.

---

## Honor Code Compliance Checklist

- [x] README has dedicated AI Usage Acknowledgement section
- [x] AI_USAGE.md provides detailed, honest citation
- [x] Inline citations on ~8 key entry-point files (Python `#` and TS `//`)
- [x] Contribution framed truthfully: design, scaffolding, integration, review, debugging — no false specifics
- [x] AI use described as "amplifying" per CS50 policy
- [x] All AI-assisted code was reviewed by the author (verifiable via git history — ~190 PRs reviewed/merged)

---

## Placeholders for User to Fill at Submission Time

1. **edX username** — for video opening
2. **City/Country** — for video opening (default suggestion: Sydney, Australia, based on Australian lending context)
3. **Recording date** — fill when video recorded
4. **YouTube video URL** — fill after upload
5. **Name preference** — Neville Zeng or Eddie Zeng (memory shows both; need to confirm)

---

## Implementation Phases (input to `/gsd-plan-phase`)

**Phase 1 — Folder scaffolding + curated copy**
- Create `C:\Users\Admin\loan-approval-ai-system-cs50\` sibling folder
- Run copy operation with the include/exclude rules above
- Verify excludes (no `node_modules`, no `venv`, no `.git`, no model binaries)
- `git init` + initial commit in the new folder

**Phase 2 — Documentation generation**
- Write `README.md` per the ~1000-word structure above
- Write `AI_USAGE.md` per structure above
- Write `VIDEO_SCRIPT.md` with explicit `[FILL IN]` placeholders

**Phase 3 — Inline citations**
- Verify file paths in the citation table still exist in the copied bundle
- Add citation comment headers in correct syntax (Python `#`, TS `//`)
- No syntax breakage

**Phase 4 — Verification + smoke test**
- README ≥750 words
- All CS50 required sections present
- Video script ≤180s runtime
- No leaked secrets in `.env.example`
- All placeholders clearly marked `[FILL IN]`
- (Optional) `docker compose up` smoke test from the new folder confirms the bundle is functional

---

## Acceptance Criteria

Submission is "spec-complete and ready to submit" when:

1. `C:\Users\Admin\loan-approval-ai-system-cs50` exists with the structure above
2. `README.md` ≥750 words with all CS50 required sections (Title, Video Demo URL, Description)
3. `AI_USAGE.md` honestly cites all AI tools used and the user's contribution
4. `VIDEO_SCRIPT.md` exists with a ≤3-min runtime budget and clear `[FILL IN]` placeholders
5. ~8 key entry-point files have AI citation comments in correct syntax
6. No secrets, large binaries, `node_modules`, `venv`, or build artifacts in the bundle
7. Fresh git history with an initial commit
8. The user confirms placeholders are reasonable and can be filled before running `submit50`

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Copy script accidentally includes `.env` with real secrets | Explicit exclude rule + post-copy grep for known secret prefixes (`sk-`, `pk_live`, `ANTHROPIC_API_KEY=sk-`) before commit |
| `submit50` upload size exceeds limits | The CS50 ZIP-alternative path is documented; if needed, generate ZIP excluding even more |
| Grader treats AI usage as honor-code violation despite citation | Honest framing + multiple citation surfaces (README section + AI_USAGE.md + inline) covers CS50's policy; this is exactly what CS50 allows |
| Inline citation breaks Python or TS syntax | Use comment syntax appropriate to file type; verify with a smoke import/parse after editing |
| Path drift between spec and current code (e.g., `predictor.py` renamed) | Execute phase verifies each file path before editing; falls back to "closest match" if file was renamed |
| User unsure of exact skeleton work they did initially | README uses general language ("initial scaffolding, project setup") not specific claims; this is truthful without overstating |

---

## Out of Scope

- The uncommitted `frontend/tsconfig.json` change on the current branch
- Recording the video
- Filing the CS50 submission form
- Running `submit50`
- Pushing the new folder to public GitHub
- Refactoring or improving the original `loan-approval-ai-system` codebase
