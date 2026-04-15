# Portfolio Polish — Design Spec

**Date:** 2026-04-15
**Branch:** to be cut from `master` as a series of 4 PRs (see PR Sequencing)
**Status:** Approved for implementation planning
**Feeds from:**
- `reports/au-lender-benchmark.md` — AU policy and applicant-field research
- `reports/senior-dev-portfolio-signals.md` — hiring-signal research (24 URLs)
- `reports/au-lender-design-patterns.md` — AU UX-pattern research (78 URLs)
- Inline frontend + backend inventory (this session, 2026-04-15)

## Purpose

Turn an already-mature loan-approval AI system into something a senior AU fintech engineering reviewer can evaluate in 90 seconds and a recruiter can try in 3 minutes. The codebase already contains ~60 service files, ~70 backend tests (including Hypothesis property tests, metamorphic ML tests, intersectional fairness, drift monitoring, champion/challenger, CDR/open-banking, KYC, credit-bureau, decision waterfall, adverse-action reason codes), a Next.js 15 App Router frontend with multi-step RHF+Zod forms, axe/WCAG tests, SHAP waterfall, model-card page, `/rights` page with AFCA contact, and a CI pipeline running bandit, trivy, gitleaks, pip-audit, npm audit, ZAP DAST, and k6 load tests.

What it lacks is **surface area a reviewer actually sees**: a problem-first README with a live demo, a `make demo` entry point, committed `.env.example`, Architecture Decision Records, a benchmark, an ablation, an auto-generated model card, an APP compliance matrix, a STRIDE threat model, an ACL footer + comparison rate (both NCCP/ASIC requirements), Dependabot, and a fix for a silent CI bug that prevents discovery of `apps/*/tests/`. Every item is either a documentation artefact or a thin packaging change. None of it modifies any existing ML algorithm, feature, calibration, orchestrator, or agent service.

## Success Criteria

Spec is complete when all four PRs are merged to `master` and:

1. A reviewer opening the repo sees — in the first 600px of the README — the project title, a live demo URL, a 3-command clone-to-run block, and an embedded demo GIF.
2. `git clone && cp .env.example .env && make demo` produces a running local instance, verified either on a separate machine from the author's or in a freshly-pulled Docker container started from a bare Ubuntu image.
3. `pytest --co -q` output count grows by ≥6 tests after PR 1 lands (the 6 existing `backend/apps/ml_engine/tests/test_quote_*.py` tests start being collected by CI).
4. Dependabot has opened at least one bump PR within 7 days of PR 1 landing.
5. `<Footer />` renders on every top-level route (`/`, `/apply`, `/apply/new`, `/dashboard`, `/rights`, `/login`, plus any subroutes rendered inside `app/layout.tsx`) with ACL number, ADI disclaimer, ASIC INFO 146 Credit Guide link, `/rights` link, AFCA contact, and last-updated date. `<ComparisonRate />` renders wherever a rate is displayed, with NCCP Sch 1 warning text.
6. `docs/adr/000{1..5}-*.md`, `docs/experiments/benchmark.md`, `docs/experiments/ablations.md`, `docs/model-cards/<active-version>.md`, `docs/compliance/app-matrix.md`, and `docs/security/threat-model.md` are all committed with no TBD / TODO / placeholder markers.
7. The deployed demo URL linked from README top viewport returns 200 on `/api/v1/health/` and the frontend loads in <3s first paint on a cold shared VM.
8. Existing test suite is non-regressing: `pytest` count stays monotonically non-decreasing across all four PRs (ignoring a temporary CI-discovery placeholder test in PR 1).

## Architecture

Four independent PRs, all branched from `master`, each reviewable in ≤30 minutes, each independently revertable. No PR depends on another PR being open; later PRs depend only on earlier PRs being **merged**.

```
PR 1 — chore/foundations-and-ci-fixes    (docs + config, zero runtime changes)
PR 2 — feat/frontend-regulatory-surfaces (Footer + ComparisonRate components)
PR 3 — docs/experiments-and-model-card   (benchmark + ablation + model-card commands + outputs)
PR 4 — chore/demo-and-readme             (deployed demo + README rewrite + GIF)
```

PR 1 can land immediately. PRs 2 and 3 can proceed in parallel after PR 1 merges (PR 2 needs `.env.example`'s `NEXT_PUBLIC_ACL_NUMBER` documentation; PR 3 needs the Makefile). PR 4 lands last because its README references content produced by 1–3.

## Scope — In and Out

**In scope (14 deliverables across 4 PRs):**

1. `.env.example` at repo root, every backend+frontend+Celery env var documented with `<REQUIRED>`/`<OPTIONAL>` markers, no real values
2. `Makefile` at repo root with targets: `demo`, `test`, `lint`, `seed`, `train`, `benchmark`, `ablate`, `model-card`, `clean`, `help`
3. `.github/dependabot.yml` — weekly pip/npm/docker/github-actions bumps, `chore(deps)` commit prefix, dev-deps grouped
4. `backend/pytest.ini` adds `testpaths = tests apps`; `.github/workflows/ci.yml` line 79 drops hardcoded `tests/` path
5. Five ADRs in `docs/adr/000{1..5}-*.md` using MADR template: WAT framework boundary, shared feature-engineering module, Optuna over grid search, Celery single orchestrator task, ModelVersion A/B routing
6. `docs/adr/README.md` — index + template + contribution note
7. `docs/compliance/app-matrix.md` — 13-row table, one per Australian Privacy Principle, with coverage, code pointer, gap
8. `docs/security/threat-model.md` — one DFD, STRIDE table (6 rows), lending-specific addenda (model inversion, data poisoning, prompt injection, bias amplification)
9. `frontend/src/components/layout/Footer.tsx` with ACL number (env-driven), ADI disclaimer, Credit Guide link, AFCA contact, last-updated date
10. `frontend/src/components/finance/ComparisonRate.tsx` displaying headline + comparison rate with NCCP Sch 1 warning tooltip
11. Management commands: `generate_model_card`, `run_benchmark`, `run_ablation` — all read-only on `ModelVersion`, reproducible via Makefile
12. Generated outputs committed: `docs/experiments/benchmark.md`, `docs/experiments/ablations.md`, `docs/model-cards/<active-version>.md`
13. Demo GIF at `docs/media/demo.gif` (20–30s, <2MB), deployed demo via Fly.io (`primary_region = "syd"` for AU data residency) + Vercel, `docs/deployment/README.md` with step-by-step
14. `README.md` full rewrite (problem-first scan structure) + `CONTRIBUTING.md` (1 page)

**Out of scope — deferred to dedicated future specs:**

- Fixing the 205 locally-failing tests → `docs/superpowers/specs/2026-04-13-test-coverage-hardening-design.md` (Track A, already approved)
- Customer-facing SHAP / counterfactual explanations panel → Track C (future brainstorm)
- OpenTelemetry distributed tracing → future spec (observability)
- Event-driven orchestrator refactor with saga + compensation → future spec (system design)
- CDR consent UI scaffold → future spec (open_banking_service exists; UX is separate)
- Visual regression / Storybook → future spec (frontend dev-ex)
- Real bureau / bank feed integration → out of scope indefinitely (services are mocked for demo)

**Non-goals:**

- No changes to any ML algorithm, feature-engineering function, calibration method, or monotonic constraint
- No changes to orchestrator execution pattern
- No changes to existing agent services, email guardrails, or Claude API integration
- No new production dependencies (LightGBM is dev-only, used by benchmark command)
- No paid-tier infrastructure — all deployment targets free tiers
- No real PII, real bureau keys, or real applicant data anywhere

## Components

### PR 1 — Foundations and CI fixes

**New files:**

- `.env.example` (repo root) — comment-grouped by concern (Backend Required / Database / Redis / Claude API / Frontend / Deployment). Values are markers only. Includes `FIELD_ENCRYPTION_KEY` generation hint.
- `Makefile` (repo root) — each target ≤5 lines, wraps existing `docker compose` and `manage.py` invocations. `help` target auto-generates from `##` comments.
- `.github/dependabot.yml` — pip `/backend`, npm `/frontend`, docker `/backend` + `/frontend`, github-actions `/`. Weekly cadence. `open-pull-requests-limit: 5`. Dev-dep grouping for pytest/ruff/mypy (backend) and @types/eslint/vitest (frontend).
- `docs/adr/README.md` — one-paragraph index, links to template and each ADR.
- `docs/adr/_template.md` — MADR format: Status / Date / Deciders / Context / Decision / Alternatives Considered / Consequences / References.
- `docs/adr/0001-wat-framework-boundary.md` — separation of workflows (markdown SOPs in `workflows/`), agents (LLM reasoning), tools (Python scripts in `tools/`, Django services in `backend/apps/*/services/`). Alternatives: monolithic prompting; pure-code. Consequences: clear boundaries vs onboarding cost.
- `docs/adr/0002-shared-feature-engineering-module.md` — single `apps.ml_engine.services.feature_engineering.compute_derived_features` used by trainer and predictor. Alternatives: duplicate code; dedicated feature store (Feast). Consequences: zero train/serve skew; tight coupling between training and inference.
- `docs/adr/0003-optuna-over-grid-search.md` — TPE sampler, 50 trials default, 3-fold stratified CV, 1200s timeout. Alternatives: grid search; random search; scikit-optimize Bayesian. Consequences: better hyperparameter frontier; requires same seed + library version to reproduce exactly.
- `docs/adr/0004-celery-single-orchestrator-task.md` — one `AgentRun` row per pipeline invocation, one Celery task, sub-steps recorded via `step_tracker`. Alternatives: Celery canvas (chord/chain); saga with compensation. Consequences: simple mental model; no compensation primitive (compensation deferred to future spec).
- `docs/adr/0005-modelversion-ab-routing.md` — `ModelVersion.traffic_percentage` field, weighted-random selection at inference. Alternatives: feature flag service; shadow deploys. Consequences: simple; no per-user bucketing (same user may flip between variants across requests — acceptable for current scale).
- `docs/compliance/app-matrix.md` — table with columns `APP | Principle | Coverage | Code pointer | Gap`. 13 rows (APP 1 through APP 13). Each row at most 2 sentences in the Coverage/Gap columns. Footer records last-reviewed date and next-review date (+6 months).
- `docs/security/threat-model.md` — 1 page. Mermaid DFD showing: Customer → Next.js → Django API → (Postgres, Redis, Celery → Claude API). STRIDE table with 6 rows (Spoofing, Tampering, Repudiation, Information disclosure, Denial of service, Elevation of privilege) × columns (Threat, Asset, Mitigation, Code pointer). Lending-specific addendum section with 4 threats: model inversion (mitigation: rate-limit predictions per user), data poisoning (mitigation: synthetic-only training; no user-feedback learning loop yet), prompt injection on Claude (mitigation: `email_engine.services.guardrails` + `template_fallback`), bias amplification (mitigation: `fairness_gate`, `intersectional_fairness`, `bias_detector`, human review queue).
- `backend/apps/ml_engine/tests/test_ci_discovery.py` — single placeholder test (`assert 1 + 1 == 2`) to prove CI now discovers `apps/*/tests/`. Removed in a follow-up commit once the existing `test_quote_*.py` tests show up in CI collection output.

**Modified files:**

- `backend/pytest.ini` — add `testpaths = tests apps` line. Other 7 lines unchanged.
- `.github/workflows/ci.yml` line 79 — change `pytest tests/ -v --tb=short --cov-report=term-missing` to `pytest -v --tb=short --cov-report=term-missing`. No other CI changes.

### PR 2 — Frontend regulatory surfaces

**New files:**

- `frontend/src/components/layout/Footer.tsx` — ~80 LOC. Props: none. Reads `process.env.NEXT_PUBLIC_ACL_NUMBER` (fallback `"DEMO-LENDER-000000"`). Renders five rows: lender-name + ACL; Credit Guide + Privacy + Terms links; AFCA phone + URL; ADI disclaimer ("is not an Authorised Deposit-taking Institution"); last-updated date. The date is read from a module-level constant `LAST_UPDATED_DATE` exported from `frontend/src/components/layout/Footer.tsx` itself (one location, human-edited whenever the component is touched; not env-driven to avoid per-deployment drift). `role="contentinfo"`, dark-mode via existing CSS variables.
- `frontend/src/components/finance/ComparisonRate.tsx` — ~60 LOC. Props: `{ headlineRate: number; comparisonRate: number; loanAmount: number; termYears: number }`. Rates formatted with `Intl.NumberFormat('en-AU', { style: 'percent', minimumFractionDigits: 2 })`. Tooltip (shadcn/ui Tooltip primitive) triggered on `*` marker with NCCP Sch 1 verbatim warning text. `aria-describedby` links the rate to its tooltip.
- `frontend/src/__tests__/footer.test.tsx` — renders without error; contains ACL number from `NEXT_PUBLIC_ACL_NUMBER`; `expectNoAxeViolations(container)`; `role="contentinfo"` present.
- `frontend/src/__tests__/comparison-rate.test.tsx` — formats rates in `en-AU`; tooltip accessible via keyboard; disclaimer text matches NCCP Sch 1 wording exactly; `expectNoAxeViolations`.
- `frontend/e2e/regulatory-surfaces.spec.ts` — Playwright: for each route in [`/`, `/apply`, `/apply/new`, `/dashboard`, `/rights`, `/login`], assert footer visible and ACL number text present.

**Modified files:**

- `frontend/src/app/layout.tsx` — import `<Footer />`; render after `<main>` children.
- `frontend/src/components/applications/RepaymentCalculator.tsx` — import `<ComparisonRate />`; replace the single-rate display with `<ComparisonRate headlineRate={...} comparisonRate={...} loanAmount={...} termYears={...} />`. Comparison-rate value passed through from the rate-quote response. If the backend does not yet return a comparison-rate field, the component renders the headline rate in the comparison slot with the tooltip disclaimer augmented to read "Illustrative only — this demo does not include lender fees. Production comparison rate will reflect the standardised NCCP Sch 1 calculation." This keeps the regulated UI pattern correct while being honest about the demo scope; a follow-up spec wires the real server-side comparison-rate calculation into `rate_quote_service.py`.
- `frontend/src/app/apply/status/[id]/page.tsx` — if decision is approved and rate present in payload, render `<ComparisonRate />` below the decision banner.

### PR 3 — Experiments and model card

**New files:**

- `backend/apps/ml_engine/management/commands/generate_model_card.py` — ~120 LOC. Flags: `--version <uuid>`, `--active` (mutually exclusive), `--output docs/model-cards/<version>.md`. Reads a `ModelVersion` row; renders into Google Model Card schema with these sections: Model Details (algorithm, version, creators, license), Intended Use (pulled from `docs/model-cards/_template-intended-use.md`), Factors (groups evaluated — state, employment_type, applicant_type, age band), Metrics (from row: AUC, PR-AUC if present, Brier, Gini, KS, ECE, confusion matrix at optimal threshold), Evaluation Data (split strategy, test-set size), Training Data (synthetic + generator version), Quantitative Analyses (subgroup metrics if `fairness_metrics` populated; else "not yet computed — see Track C roadmap"), Ethical Considerations (static template), Caveats and Recommendations (synthetic-data caveat, macro-regime caveat).
- `backend/apps/ml_engine/management/commands/run_benchmark.py` — ~180 LOC. Flags: `--num-records 10000`, `--seed 42`, `--output docs/experiments/benchmark.md`. Uses existing `DataGenerator` with fixed seed. Same train/val/test split logic as `trainer.py`. Trains four models on identical data: `LogisticRegression(penalty="l2")`, `RandomForestClassifier`, `XGBClassifier` (no Optuna — default hyperparameters for fair comparison), `LGBMClassifier`. Evaluates on identical test set using `apps.ml_engine.services.metrics`: AUC-ROC, PR-AUC, Brier, ECE, wall-clock training time. Writes markdown table + methodology footer (seed, split ratios, CV, hyperparameters). Writes `docs/experiments/_takeaway.md` as a human-editable stub — command appends its table but does not overwrite any text below `<!-- BENCHMARK TABLE END -->`.
- `backend/apps/ml_engine/management/commands/run_ablation.py` — ~150 LOC. Flags: `--version active`, `--top-k 10`, `--num-records 10000`, `--output docs/experiments/ablations.md`. Loads active `ModelVersion` and training data. Identifies top-K features by `feature_importances_`. Retrains once per removed feature (K+1 total trainings including baseline). Reports ΔAUC and ΔPR-AUC per feature. Writes markdown table with columns: `Feature removed | Baseline AUC | AUC w/o feature | ΔAUC | ΔPR-AUC`. Human takeaway written below `<!-- ABLATION TABLE END -->` marker.
- `backend/apps/ml_engine/tests/test_generate_model_card.py` — fixture creates a `ModelVersion` row with known metrics; command runs with `--version <id>`; assert output file contains required sections; assert metric values in output match row.
- `backend/apps/ml_engine/tests/test_run_benchmark.py` — `@pytest.mark.slow`. Run with `--num-records 200 --seed 42`. Assert output file exists, markdown table has four rows, each AUC > 0.55 (catastrophic-failure floor only).
- `backend/apps/ml_engine/tests/test_run_ablation.py` — `@pytest.mark.slow`. Run with `--top-k 3 --num-records 200`. Assert output file exists, table has 3 rows, ΔAUC values are numeric floats.
- `docs/model-cards/_template-intended-use.md` — human-editable intended-use + out-of-scope-use statements, referenced by `generate_model_card`.
- `docs/experiments/methodology.md` — 1 page: seed strategy, split strategy, CV approach, reproducibility note.
- `docs/experiments/benchmark.md`, `docs/experiments/ablations.md`, `docs/model-cards/<active-version>.md` — generated by the commands above, then committed.

**Modified files:**

- `backend/requirements-dev.txt` — add `lightgbm>=4.0` (dev-only, used by benchmark command).

### PR 4 — Demo and README

**New files:**

- `docs/media/demo.gif` — 20–30s, <2MB. Recording protocol documented in `docs/media/RECORDING.md`: use `asciinema rec` for terminal portions (`make demo` on a fresh clone), use OBS Studio for browser portions (customer application submission → decision result → officer dashboard → model card). Combine via `ffmpeg -i asciinema.cast -i browser.mp4 -filter_complex hstack output.mp4`, then `gifski --fps 10 --quality 80 output.mp4 --output demo.gif`.
- `docs/media/RECORDING.md` — reproducible protocol for future demo refreshes.
- `deploy/fly.toml` — Fly.io config: `app = "loan-approval-demo"`, `primary_region = "syd"`, internal_port 8000, shared-cpu-1x 512MB, release command `python manage.py migrate`, three processes (app: gunicorn, worker: celery worker, beat: celery beat), env vars listed, secrets set via `fly secrets set`.
- `deploy/vercel.json` — build settings, env vars (`NEXT_PUBLIC_API_URL` pointing at Fly URL, `NEXT_PUBLIC_ACL_NUMBER` set to demo value).
- `deploy/seed_demo.py` — Django management-command body: creates a demo admin (`admin` / demo password), 100 seeded synthetic applications, one named "Neville Zeng" golden applicant with known outcome, loads trained model bundle from `ml_models/`.
- `docs/deployment/README.md` — step-by-step: flyctl install; `fly launch --copy-config`; `fly secrets set DJANGO_SECRET_KEY=... FIELD_ENCRYPTION_KEY=... ANTHROPIC_API_KEY=sk-ant-test-key`; `fly deploy`; `fly ssh console -C "python manage.py migrate && python manage.py seed_demo"`. Vercel: `vercel link`; set env vars via dashboard; `vercel --prod`. Cost notes: free tier is $0/month with <3GB bandwidth; cold-start latency ~10–20s on shared VM (documented, acceptable for demo).
- `deployment/test_smoke.sh` — `curl -fsS https://loan-approval-demo.fly.dev/api/v1/health/` and frontend URL, exit non-zero on failure. Invoked manually before release tagging; not wired to CI.
- `CONTRIBUTING.md` (repo root) — 1 page: "Add an ADR for any architectural decision. Tests-first for any new service method. See `make help` for workflow commands. Pre-commit hooks run ruff + detect-secrets."

**Modified files:**

- `README.md` — full rewrite. First 600px must contain: title; live demo URL + credentials; 3-line clone-to-run code block; embedded `docs/media/demo.gif`. Below fold: 3-sentence "What this does"; Mermaid architecture diagram with links to each ADR; "Key design decisions" bulleted list linking ADRs; "AU regulatory posture" section linking `app-matrix.md` and `threat-model.md` and noting NCCP 3% buffer, HEM, APRA Feb-2026 DTI cap; "Metrics summary" 1-row-per-model table linking `benchmark.md` and the active model card; "Limitations" honest list (synthetic data only; no real bureau; deployed demo on shared VM; retirement-age gate not legally reviewed); "Future work" linking Track C and subsequent specs; "Quickstart" copy-paste block; "Project structure" tree to depth 2; "Contributing" link; "License" MIT.

## PR Sequencing & Dependencies

```
PR 1 (standalone, docs+config)
  └─▶ PR 2 (depends on PR 1 for .env.example NEXT_PUBLIC_ACL_NUMBER entry)
  └─▶ PR 3 (depends on PR 1 for Makefile targets)
  └─▶ PR 4 (depends on PRs 1, 2, 3 for content to link/render)
```

PR 2 and PR 3 can run in parallel after PR 1 merges. PR 4 waits until PRs 1–3 all merge, because its README references files produced by them.

## Testing Strategy

**PR 1:** No runtime behaviour changes. Validation = manual review of docs + the CI-discovery placeholder test running successfully in CI to prove `testpaths = tests apps` works.

**PR 2:** Vitest + Axe unit tests for `Footer` and `ComparisonRate`; Playwright e2e for footer presence on every top-level route. All plugged into existing `frontend-test` and accessibility test jobs.

**PR 3:** Each command gets a fixture-based unit test. Benchmark + ablation tests marked `@pytest.mark.slow`. Content review required: PR description includes the generated markdown and a checkmark confirming it reads coherently to a second author.

**PR 4:** Smoke script invoked locally. Manual walkthrough of deployed demo (record evidence in PR description). Lighthouse audit of deployed frontend (paste score in PR description; no CI gate).

## Rollback Plan

Every PR is fully revertable with `git revert <merge-sha>` with zero effect on existing functionality, except PR 4 which additionally requires tearing down the deployed apps (`fly apps destroy loan-approval-demo` and removing the Vercel project). No PR touches production-path code in a way that could leave the system in an inconsistent state if reverted mid-implementation.

## Verification Checklist per PR

**PR 1**
- `.env.example` grepped for `sk-ant-`, `Fernet`, long hex strings — nothing real
- `make demo` completes on a fresh clone on a machine other than the author's
- `make test` output matches what CI runs
- All five ADRs have all six required MADR sections populated
- `app-matrix.md` has 13 rows, no TBD/TODO/placeholder markers
- `threat-model.md` has one DFD, 6 STRIDE rows, 4 lending-specific addenda, no TBD markers
- After merge, the first CI run collects tests from `backend/apps/ml_engine/tests/` (visible in CI log)

**PR 2**
- Footer renders on `/`, `/apply`, `/apply/new`, `/dashboard`, `/rights`, `/login` (manual + Playwright)
- `<ComparisonRate />` renders on `RepaymentCalculator` and on approved-decision status pages
- Dark-mode contrast passes WCAG AA on footer (manual devtools check)
- Axe unit tests + Playwright e2e green
- `NEXT_PUBLIC_ACL_NUMBER` documented in `.env.example` (PR 1 dependency)

**PR 3**
- `make benchmark`, `make ablate`, `make model-card` all complete on clean run
- Generated `benchmark.md`, `ablations.md`, `model-cards/<version>.md` committed
- Takeaway paragraphs are human-written below command-managed markers
- Model card fairness section has real data or explicit "not yet computed — see Track C" sentence
- Every command has at least one fixture-based test

**PR 4**
- Deployed backend URL returns 200 on `/api/v1/health/`
- Deployed frontend first paint <3s on shared VM (Lighthouse Performance ≥70 acceptable)
- `docs/media/demo.gif` exists, <2 MB
- README first 600px contains: title + live URL + clone block + GIF
- `markdown-link-check README.md` reports no broken links
- Mermaid architecture diagram renders in github.com preview
- Deployed demo contains the "Neville Zeng" golden applicant with a known outcome

## Safety & Reversibility

- All four PRs branch from `master`, not `chore/test-coverage-hardening`
- No production-path code is modified in PRs 1, 3, 4. PR 2 adds two new components; deleting them restores prior state
- No new production dependencies (LightGBM is dev-only; no frontend package additions beyond existing devDependencies)
- No Docker production-image size increase beyond KB-scale
- Merge policy: CI green + 1 human review (or 24h solo cool-off self-review)
- Squash-merge preserves Conventional Commit subject lines

## Out of Scope Reminders

- Not fixing the 205 locally-failing tests (Track A — existing approved spec `2026-04-13-test-coverage-hardening-design.md`)
- Not building customer-facing SHAP or counterfactual explanations (Track C — future brainstorm)
- Not integrating OpenTelemetry / distributed tracing (future spec)
- Not refactoring the orchestrator into event-driven saga pattern (future spec)
- Not wiring CDR consent UI (future spec; `open_banking_service.py` already exists)
- Not adding Storybook / visual-regression testing (future spec)
- Not touching any ML algorithm, feature-engineering function, calibration method, or monotonic constraint
- Not adding real bureau keys, real bank feeds, or any real PII

## Next Step

After user sign-off on this spec, invoke the `superpowers:writing-plans` skill to produce a step-by-step implementation plan scoped to this document.
