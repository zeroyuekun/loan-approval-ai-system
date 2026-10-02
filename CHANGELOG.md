# Changelog

## Unreleased: post-v1.11.1 hardening (on `master`, not yet tagged)

Work landed on `master` after the `v1.11.1` tag and has not been cut as a release yet.

- **Moderate bias findings no longer ship or stall.** A decision email with a flagged bias score below the review threshold is replaced by the deterministic template, which is bias-checked again. A clean template is sent; otherwise the application goes to the human-review queue. The flagged text is never sent. Fixes a column-length bug (`BiasReport.score_source`, migration `agents/0014`) that turned every LLM-confirmed moderate finding into a false "bias check unavailable" hold. The template, LLM prompt and marketing follow-up emails are rewritten in plainer language: one statement of the outcome, no stock phrases such as "please don't hesitate", and no dashes used as punctuation.
- **Model Metrics redesign, chart hover and more honest fairness results.** Tabbed the Model Metrics page (page file 357→125 lines) and fixed ECE and visualisation correctness bugs (#211). Hover detail now renders in a fixed strip below each of the 7 charts instead of in a floating tooltip that covered the plot, and group labels are capitalised (#220). The fairness disparate-impact ratio now excludes protected groups smaller than `FAIRNESS_MIN_GROUP_SIZE` (default 30), so sampling noise in a cohort of ~10-20 samples can't produce a fail. Excluded groups are still shown for transparency. When fewer than two large groups remain, the result gets a neutral "Not assessable" badge instead of a false green PASS (#222 + #220).
- **Fixes from a deep 5-agent review (~22 findings across #212 to #219 and #221).** Backend agents/ML correctness and operability (#213); backend security, guardrails and API hardening (#214); frontend null-safety, auth redirect, payload and PII hardening (#215); k8s, compose, CI and monitoring hardening (#216); backend healthcheck moved to the open `/api/v1/health/` probe and the gated `/ready/` removed (#212); CI back to green: ruff pinned, Django 5.2.15, build-workflow env, smoke-e2e (#217 to #219); `celery_beat` uses the default scheduler, not django-celery-beat (#221).
- **Staff-endpoint PII trust boundary (#171).** Staff customer endpoints now filter to `role=CUSTOMER`, so an officer can no longer enumerate admin/officer accounts or auto-create a phantom `CustomerProfile` against a non-customer.

## v1.11.1: Full-codebase review remediation (2026-06-05)

Fixes for a 93-finding full-codebase senior review (9 Critical / 30 High / 36 Medium / 18 Low). Every finding was re-verified adversarially before it was fixed. The fixes landed on the review branch and were merged to master. `APP_VERSION` bumped to `1.11.1` (#210) and tagged `v1.11.1`. The fixes cover correctness, security, reliability and operability on top of the v1.11.0 ADM/contestability baseline. No model retraining, and nothing removed from the API surface.

## v1.11.0: Decision transparency, contestability & audit remediation

Adds Privacy Act automated-decision-making (ADM) transparency and a contestability path for customers, then works through a verified senior-audit backlog (3 HIGH / 9 MEDIUM / 21 LOW, each finding re-verified adversarially) in six phases. Released 2026-06-03 (PR #207 merged to master, merge commit `eb21013`, tagged `v1.11.0`).

### Phase 1: ADM transparency correctness (3 HIGH)

- **Honour `requires_human_review` (H1).** The orchestrator escalates borderline, severe-drift and policy-"refer" predictions to the human-review queue before it generates or sends any decision email. It used to auto-decide and email these silently.
- **Persisted human-involvement (H2).** New `LoanDecision.human_involvement` field (`none`/`assisted`/`overridden`, migration `0025`), set to `assisted` when a reviewer resolves an escalation. The ADM disclosure reads this stored value, not the transient `application.status`.
- **Honest disclosure on officer overturn (H3).** An overturn sets `overridden`, so the disclosure reads *"Reviewed and decided by a lending officer"* (mode `human`) instead of falsely saying *"solely automated"*. Adds a `human_override` register entry and a defensive row lock on the overturned `LoanDecision`.

### Phase 2: Contestability feature finish

- **`DecisionReview` model + API** (built earlier on this branch). Request human review of a declined automated decision; an officer upholds or overturns it. The flow is concurrency-safe, audit-logged and gated by `DECISION_REVIEW_ENABLED`. Also adds the ADM disclosure register and the unified `DecisionExplanation` assembler, which is now the single source for denial-reason ranking.
- `DecisionReview.resolve` now returns 409 instead of 500 on an ineligible state, and serializes the resolved object with its fresh status instead of the stale pre-resolution one (M3/L30/M8). A server-side `?application=` filter lets the customer UI find the right review regardless of pagination (L32). The customer UI can now reach the overturned and withdrawn statuses (L31/M9). An audited customer withdraw action puts the application into the `WITHDRAWN` state (L33). The legacy `POST /ml/predict/{id}/` is disabled by default behind `ML_STANDALONE_PREDICT_ENABLED`, which closes an ADM-disclosure gap on a path that had no AgentRun lifecycle.

### Phase 3: Bias & escalation safety

- An infrastructure failure in bias detection now fails safe (`BIAS_FAILURE_MODE`, default `block`). The email is withheld, the run is marked failed, a `bias_check_unavailable_total` metric is emitted and the application is rolled back to `pending`. Before, the email shipped silently with a hardcoded passing score (M7/M10/L21). The decision and marketing gates now share an inclusive `>=` bias boundary (M4), and `requires_human_review` is monotonic with `flagged` (L18). The README and ADR now describe the actual flow: the senior Opus review runs on marketing emails only, and no per-decision-email Claude call was added, to keep costs down.

### Phase 4: Reliability hardening

- The `$5/day` Claude spend cap is now an atomic Lua reserve, so concurrent calls can't overshoot it through a check-then-act (TOCTOU) race, and a failed call releases its whole reservation (M5). In the decision-email task, Celery-native retry plus `soft_time_limit` replace the blocking in-task sleeps. Sends are idempotent: each is gated on a new `GeneratedEmail.sent_at` marker under `select_for_update`, so at-least-once redelivery can't send duplicate emails (M6/L25, migration `email_engine 0006`). Stuck-state cleanup is locked and owner-checked (L22). The outbox row is deleted only after the application leaves `PENDING`, and the broker options now fail fast (L23). The watchdog reaps only `idle in transaction` connections, scoped by `application_name` (L24).

### Phase 5: Next-best-offer in the denial email

- The denial email now includes a short alternative-offer teaser (the recommendation engine's best offer and its headline figure), validated by the guardrails. The fuller personalised offer set still goes out as a separate marketing follow-up; the two-email split is intentional. The hallucinated-number guardrail validates the new figure by extending the existing whitelist; there is no new check. NBO bug fixes: term selection for unsecured personal loans applies a real affordability constraint instead of always picking 60 months (L19), and offer reasoning is bound to offers by product id instead of positional index, so figures can't attach to the wrong product (L20). No apology language (the locked rule still holds).

### Phase 6: Architecture & security polish

- One canonical PSI primitive (`drift_monitor.compute_on_demand_feature_psi`); the view, `MetricsService` and the module-level `psi()` delegate to it (M1). Split the god methods `DataGenerator.generate()` and `UnderwritingEngine.compute_approval()` into smaller pieces. The code moved verbatim with RNG call order preserved, and determinism snapshots check that the synthetic data stays byte-identical (M2/L15). `agents` endpoints use proper DRF serializers, which restores the OpenAPI schema and stops the list endpoint re-rendering marketing HTML for every row (L13/L14). The orchestrator calls a public predictor seam instead of a private method (L17), and task status restores go through the audited state machine (L16). Security: the marketing agent and the senior bias reviewers use the shared prompt-injection sanitizer with `<user_content>` fencing and never-follow guards, and registration validates name content (L26/L27). `ReferralListView` clamps a bad `limit` instead of returning a 500 (L28). Adds an optional maker/checker gate on officer overturns (`DECISION_OVERTURN_GATE_MODE`, default `off`, which is a no-op until enabled) (L29).

### Tests & migrations

Final suite: backend 1743 passed / 34 skipped / 0 failed, frontend 327 passed. Migrations: `loans 0025` (`human_involvement`), `email_engine 0006` (`sent_at`).

### Operational notes for merge

- **`BIAS_FAILURE_MODE` defaults to `block`.** This behaviour change is intended. If bias-detection infrastructure goes down, the email is now withheld instead of shipped; set `BIAS_FAILURE_MODE=off` to restore the old fail-open behaviour.
- **Celery `broker_transport_options` fail-fast flags are global.** Before deploying, run a worker-connect smoke check against a healthy broker (`docker compose up`, then confirm the workers connect).
- **`POST /ml/predict/{id}/` is disabled by default.** If a caller outside the orchestrator needs it, enable it with `ML_STANDALONE_PREDICT_ENABLED=true`, and make it consistent with AgentRun and ADM first.
- Released 2026-06-03: PR #207 merged to master (merge commit `eb21013`); `APP_VERSION` bumped to `1.11.0` and tagged `v1.11.0`. The release also includes the post-milestone hardening done on the same branch: a 17-finding senior audit, Python/npm CVE bumps, a 7-area pre-merge review (1 HIGH and 4 mediums fixed, all with regression tests), and doc fixes for metric drift and the k8s probes. That brings the suite to backend 1752 passed / 34 skipped, frontend 327 passed.

## v1.10.6: Renderer XSS hardening + external benchmark + realism audit (2026-04-20)

Four atomic PRs. They close the last items deferred from the v1.10.3 senior review and re-land the two concept PRs that had gone stale as fresh atomic changes. No data migrations, no model retraining, no API surface changes.

### Deliverables

- **#139: HTML escape on both renderers.** Every string-interpolated value in `backend/apps/email_engine/services/html_renderer.py` and `frontend/src/lib/emailHtmlRenderer.ts` is now HTML-escaped, as a defense-in-depth layer. This closes the parity item that the senior review flagged and v1.10.3 deferred. Both sides of the Py↔TS parity contract now escape every interpolated value, not just body rendering. All 16 fixture snapshots are still byte-identical.
- **#142: URL scheme allowlist.** `_e()` escapes `<>&"'` but does not block `javascript:alert(1)`, because that scheme contains no special characters. The marketing footer parses the unsubscribe URL out of the LLM-rendered body with `UNSUBSCRIBE_LINE_RE`, so a prompt-injected value could land in `<a href="javascript:…">` unchanged. A new `_safe_url()` helper (Python) and a matching `safeUrl()` (TS) now check every `href=` interpolation. http, https, mailto and tel pass through (case-insensitive, whitespace trimmed); anything else falls back to `https://aussieloanai.com.au/unsubscribe`. Eight unit tests per side, plus an end-to-end injection test that renders a marketing body containing `Unsubscribe: javascript:alert('xss')` and asserts that no href starts with the dangerous scheme. Snapshot parity CI is unaffected.
- **#141: GMSC external benchmark re-land.** Re-lands PR #92, which had been closed as stale, as a fresh atomic change. `scripts/benchmark_gmsc.py` runs 5-fold stratified CV on the Kaggle Give Me Some Credit dataset (150k real 2011-vintage borrowers), with a SHA256-pinned download, a 50-trial Optuna search on a 30k sub-sample, and isotonic calibration. It reports AUC 0.8663 ± 0.0035, KS 0.581 and Brier 0.049, a documented external ceiling that reviewers can check the synthetic-only metrics against. New `make benchmark-gmsc` target. The full 150k-row CV is run by hand (not CI-gated), but 12 CI-safe unit tests exercise the loader, preprocessor and integrity checks against a synthetic mimic CSV. `backend/docs/MODEL_CARD.md` gets an "External Benchmark Validation" section.
- **#140: Synthetic data realism audit.** Re-lands the concept that was deferred when v1.9.8 PR #93 went stale (the `postcode_default_rate` noise-std fix had already shipped in v1.10.4 as #118). The new `docs/experiments/synthetic_data_realism_audit.md` grades every `DataGenerator` feature as ANCHORED, APPROXIMATED or UNCITED against 14 AU data sources (ATO, ABS, APRA, RBA, Equifax, CoreLogic, HEM, etc.): ~28 anchored, ~18 approximated, ~6 uncited. It lists the known gaps and 7 recalibration triggers. The Training Data section of MODEL_CARD.md now links back to it. Docs-only PR, no CI impact.

### Version bump

`APP_VERSION` advances `1.10.5` → `1.10.6`. No data migrations. No trained-model invalidation. No API surface changes.

### Scope notes

- The v1.10.3 senior-review parity backlog is now closed: #139 (escape) and #142 (scheme allowlist) together cover the HTML-escape parity follow-up that was deferred through v1.10.3, v1.10.4 and v1.10.5.
- Both stale concept PRs from earlier cycles, #92 (v1.9.7 GMSC benchmark) and #93 (v1.9.8 realism audit documentation), have been re-landed and can be closed.

## v1.10.5: Live denial shape + aesthetic v3 + staff re-run (2026-04-20)

Three atomic PRs: a fix for a silent email-rendering regression seen in production, the v3 aesthetic polish pass on top of it, and a fix that unblocks staff re-runs from the application detail page. No data migrations, no model retraining, no API surface changes.

### Deliverables

- **#125: Parse live Claude denial shape.** Live Claude denials were silently degrading to plain-text rendering in Gmail because the parser was tuned to the shape of the fixture templates. There were two parsing gaps: (1) factor lines from the live prompt start with a bullet (`• Label: value`) instead of arriving bare, so `_extract_factor_paragraphs` matched nothing; (2) the free-credit-report block opens with a prose intro ("You can request a free copy...") instead of an explicit header, so `_extract_free_credit_report_block` fell through. The fix accepts optional bullet prefixes in factor matching and adds two-branch credit-block detection (an explicit header, OR a prose intro plus ≥2 bureau bullets for Equifax / Illion / Experian). It renames `_extract_free_credit_report_block` → `_extract_credit_report_block` to match the broader detection, mirrors the same changes byte-identically in `emailHtmlRenderer.ts`, and adds a `denial_06_live_shape` fixture and snapshot that capture the live layout end to end. Py↔TS parity holds across all 16 fixtures; 58/58 backend and 22/22 frontend tests pass.
- **#126: Aesthetic v3 polish.** Small presentation-layer changes on top of v2. The denial hero drops the orange info icon that Gmail rendered as a loud block between header and body. A dedicated marketing-close renderer puts sign-off paragraphs on the correct 12px/2px rhythm. A new `_next_nonblank_matches` helper and regex constants stop bullet/numbered lookahead spacing from collapsing across blank lines. The ABN/Website special case is trimmed in favour of margin-based spacing, for consistent Gmail quoting. The header gets a `<span class="badge">` treatment. Parser logic is unchanged; this is only the visual pass. The denial hero test now asserts that the icon is absent. All 16 snapshots were regenerated, byte-identical across trees.
- **#124: Staff re-run escalation.** The orchestrate-pipeline mutation short-circuits with `{status: "already_completed"}` when a completed `AgentRun` already exists for a loan. Staff who click "Re-run AI Pipeline" on the application detail page expect a fresh run and a new email, not a silent no-op. `usePipelineOrchestration` now escalates: when `orchestrate.mutateAsync()` returns `already_completed`, it immediately calls `forceRerun.mutateAsync()` with a staff-originated reason string. The dashboard is staff-only, so customers never reach this path. Adds 2 test cases (positive escalation and the force-rerun failure branch) to the existing 8, for 10/10 passing.

### Version bump

`APP_VERSION` advances `1.10.4` → `1.10.5`. No data migrations. No trained-model invalidation. No API surface changes.

### Scope notes

- HTML-escaping LLM-interpolated values in `emailHtmlRenderer.ts` / `html_renderer.py` (deferred from v1.10.3 and v1.10.4) is still planned for a future coordinated PR. The v1.10.5 parser change is additive (no existing fixture re-renders), so it leaves the 15 legacy parity snapshots alone.

## v1.10.4: Senior review follow-ups + SLO instrumentation (2026-04-19)

Five atomic PRs that finish the backlog from the senior code-review pass and add the SLO histograms the Grafana dashboard was silently missing. No model retraining, no data migrations, no API surface changes.

### Deliverables

- **#118: ML data-realism fix.** `DataGenerator` was emitting `postcode_default_rate = base + rng.normal(0, 0.003)`. The noise std was too tight and collapsed the feature into a near-deterministic function of SA4 unemployment, which also drives the label. Raised the noise std `0.003 → 0.008` to match the correlation that real Equifax / illion AU bureau data shows with SA4 unemployment (r ≈ 0.3 to 0.45). Added the regression guard `test_postcode_default_rate_correlation_realistic`, which asserts `|corr(postcode_default_rate, approved)| < 0.25` so the leakage shortcut can't silently come back. This re-lands the substance of the earlier closed PR #93 as a fresh atomic change against current master. The fix takes effect on the next `DataGenerator.generate()` call; no in-flight ModelVersion is invalidated.
- **#119: CI Fernet key hardening.** `.github/workflows/{test,build}.yml` hardcoded a Fernet encryption key in plaintext, which the senior review flagged as a credential in source. Each CI job now generates a fresh 32-byte urlsafe-base64 key with the Python stdlib (`os.urandom(32)` + `base64.urlsafe_b64encode`) and exports it through `$GITHUB_ENV`. No repo secret, no hardcoded key in source, no new dependency. The CI test DB is ephemeral, so the key only has to be valid, not confidential. Closes #59.
- **#120: Bandit SAST gate tightening.** `.github/workflows/security.yml` scanned at `--severity-level medium`, which produced noise without blocking on the real issues. The gate now runs at `--severity-level high --confidence-level high`, the pair that fits the threat model the review identified. There were 0 HIGH/HIGH findings when the gate was tightened, so from here on it blocks any new one. The five remaining MEDIUM findings are tracked as follow-ups and do not block CI. Closes #60.
- **#121: `enforce_retention` regression coverage.** `backend/apps/loans/management/commands/enforce_retention.py` enforces AU regulatory retention periods (AML/CTF Act s107/s112 7y loan/KYC retention, APRA CPG 235 5y ML audit trail, Privacy Act APP 11.2 90d soft-delete purge) but had 0% test coverage. A silent regression in either direction would be a data-loss or compliance incident. Added 8 regression tests that pin down the `--dry-run` no-op, the 90d/5y/3y cutoff directions (strict `<`, not `<=`), AuditLog emission per purge/archive, and no-op behaviour on fresh data. The tests backdate `auto_now_add` timestamps with `QuerySet.update()` instead of adding `freezegun` as a new dev dependency. Closes #61.
- **#122: SLO histogram instrumentation.** `docs/slo.md` listed four SLOs whose metrics were marked _"follow-up issue tracks this"_ and never emitted, so the Grafana panels couldn't render them and the PagerDuty alerts couldn't fire. This PR instruments all four at their service-layer chokepoints:
  - `pipeline_e2e_seconds{status,decision}` Histogram (1s to 120s buckets), emitted in `StepTracker.finalize_run`, the single chokepoint that every terminal pipeline run passes through (completed / failed / escalated)
  - `email_generation_total{decision,source,status}` Counter, emitted in `EmailGenerator.generate()` at both return paths (claude_api + template_fallback)
  - `ml_prediction_latency_seconds` gains an `algorithm` label so xgboost / rf / logistic can be compared separately on the Grafana latency panel (the existing `HighPredictionLatency` alert uses `sum by (le)` and aggregates across labels, so the rule needs no rewrite)
  - `bias_review_ttr_seconds{decision}` Histogram (1min to 3d buckets) + `bias_review_total{outcome}` Counter, emitted in `HumanReviewHandler.resume_after_review`

  Also added two Prometheus alert rules: `PipelineE2ESLOBurn` (p95 > 60s for 30min, double the 30s SLO) and `EmailGenerationErrorBudgetBurn` (success rate < 95% for 15min, which burns the monthly 2% budget in <1 day). Every emission is wrapped in `try/except` with a debug log, so a Prometheus client failure can't propagate into the pipeline. 14 new registration and observe/increment tests in `tests/test_slo_metrics.py`. Closes #50, #51, #52, #53.

### Version bump

`APP_VERSION` advances `1.10.3` → `1.10.4`. No data migrations. No trained-model invalidation. No API surface changes.

### Scope notes

- HTML-escaping LLM-interpolated values in `emailHtmlRenderer.ts` / `html_renderer.py` (deferred from v1.10.3) is still planned as a single coordinated future PR. The 15 byte-for-byte Python/TypeScript parity snapshots in email-renderer CI would all have to regenerate in lockstep, which is too big a change for a coverage and observability release.

## v1.10.3: Senior code review response (2026-04-19)

Four atomic PRs that fix findings from a full senior-engineer code review. No model retraining, no migrations, no API surface changes. Each PR passed CI against master and was merged on its own, to keep each change small and independently revertible.

### Deliverables

- **#113: Security critical gaps.** Fernet `InvalidToken` is now caught explicitly; before, a bare `except Exception` swallowed it and hid key-rotation mistakes. Export-path quotas are tighter, the denial guardrails gain an apology regex, and the bias threshold changes from `>` to `>=` (the old form misclassified borderline cases). The template-mode code path now reaches the fallback guardrail call, as the LLM path always did. The new `test_apology_language_blocked_in_denial` pins the apology rejection.
- **#114: ML correctness.** Moved the `processing_time_ms` timestamp to the end of `predict()` so the Prometheus latency histograms show real wall-clock time. The old stamp was taken mid-function and left out the counterfactual and shadow-scoring cost. Added a defence-in-depth leakage drop: `train()` now drops any `POST_OUTCOME_FEATURES` column at the load boundary and logs a warning, instead of relying only on IV selection and the monotone-constraints review to catch leakage. A regression test can't cover every path such a column could sneak through; the explicit drop makes the invariant auditable in one place.
- **#115: Infra hardening.** `POSTGRES_PASSWORD` is now required (`:?` guard) in every compose service. The old `:-postgres` default would silently start Postgres with a known credential if `.env` was missing. Pinned `prom/prometheus:v3.1.0`, `prom/alertmanager:v0.28.0`, `grafana/grafana:11.5.1`, `danihodovic/celery-exporter:0.10.13` and `prometheuscommunity/postgres-exporter:v0.17.1`, which removes the supply-chain risk of silent major upgrades through `:latest`. The `build.yml` deploy gate changes from `!contains(... 'failure')` to `== 'success'`; the old form allowed a deploy when upstream stages were cancelled or skipped. `.env.example` now gives `openssl rand -base64 24` as the generation hint and no longer ships a weak default value.
- **#116: Frontend polling.** The customer status page swaps a hand-rolled `useEffect` + `setInterval` pair for the function form of TanStack Query's `refetchInterval`. The hook now decides whether to poll from the current `status`: `pending` / `processing` poll every 5s, and everything else stops. This removes the manual cleanup edge cases around unmount, re-render and status transitions. `useApplication` accepts an optional `refetchInterval` option so other callers can opt in.

### Deferred to future PR

Two items from the review were scoped out of v1.10.3:

- **HTML-escape LLM-interpolated values** in `emailHtmlRenderer.ts` and Python `html_renderer.py`. Deferred because the 15 byte-for-byte parity snapshots in email-renderer CI must regenerate in lockstep across Python and TypeScript, which is too large a change for a "safe" release PR. Planned as one future PR that adds `escapeHtml()` to both renderers together, with a fresh snapshot regen and a tighter DOMPurify `ALLOWED_URI_REGEXP`.
- **URL protocol allowlist** for LLM-extracted unsubscribe URLs. The residual risk on the frontend path is low (DOMPurify's default URI allowlist strips `javascript:` / `data:`); the real benefit is only on the SMTP-delivered email path. Bundled with the HTML-escape follow-up.

### Also reviewed but not changed

`user: root` on the frontend compose service stays. The named `frontend_node_modules` volume needs write access from `npm ci`, and the safer fix needs a Dockerfile `chown` at build time, which is out of scope for a compose-only PR.

### Version bump

`APP_VERSION` advances `1.10.2` → `1.10.3`. No data migrations. No trained-model invalidation. No API surface changes.

## v1.10.2: Consolidation release (2026-04-19)

Seven atomic deliverables that fix latent bugs, close security gaps and remove dead code, with no change to model behaviour or the API surface. Builds on the in-flight PRs #103 / #104 / #105, which shipped as milestones M1 to M3.

### Milestones (merged before D-series)

- **M1: Smoke E2E stabilisation (#103).** Fixed container-network hostname resolution and the login auth payload shape in `tools/smoke_e2e.sh`, so the `workflow_dispatch` smoke job exits 0 against a live deploy.
- **M2: Watchdog httpx swap (#104).** Replaced the missing `requests` dependency in the `docker-compose` watchdog service with the already-vendored `httpx` client, so the watchdog now starts.
- **M3: Calibration lazy-import fix (#105).** `ml_engine/services/calibration.py` had a broken top-of-file import that crashed any calibration-adjacent code in production; moved the sklearn import inside the function.

### Deliverables

- **D1: Python 3.13 datetime deprecation.** Replaced every `datetime.utcnow()` call in `apps/ml_engine/` with `datetime.now(UTC)`, so the module no longer emits `DeprecationWarning: datetime.utcnow() is deprecated` under Python 3.13. Added an AST guard, `tests/test_utcnow_deprecation.py`, against regression.
- **D2: `seed_profiles` percentage scale.** `seed_profiles` set `on_time_payment_pct` to a fraction in `[0.75, 1.0]`, but the field is documented as `[0, 100]`. Credit-policy and scoring code downstream reads the field as a whole-number percentage and would silently mis-rank seeded users. It now uses `random.uniform(75.0, 100.0)`, with a regression test that asserts the value is in the documented range AND ≥ 1.0 (which catches the fraction form).
- **D3: `on_time_payment_pct` validators.** The field had no bounds, so a buggy writer could persist `-5.0` or `250.0` and crash downstream scoring. Added `MinValueValidator(0.0)` + `MaxValueValidator(100.0)` with migration `0010_add_on_time_payment_pct_validators`, plus tests for the boundary cases (0.0 / 100.0 / mid), negatives, and > 100. Closes #55.
- **D4: Grafana admin password required in monitoring profile.** The default compose had `GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:-changeme}`, which ships a known weak credential. Moved the Grafana service into `docker-compose.monitoring.yml` (an opt-in profile) using the required-env form `${GRAFANA_ADMIN_PASSWORD:?set in .env}`, so the monitoring stack fails fast instead of exposing an `admin/changeme` dashboard. The main compose no longer references the variable, so a standard `docker compose up -d` is unaffected. Closes #57.
- **D5: Dead DiCE callpath removed.** `CounterfactualEngine` had a DiCE branch that never ran in production: `dice_ml` was never in `requirements.txt`, and the orchestrator always passes `transform_fn=predictor._transform`, which sends `generate()` straight to the binary-search fallback. Removed `_dice_counterfactuals`, `_build_dice_dataset`, `_parse_dice_result`, `_timeout_ctx` and the no-op `timeout_seconds` parameter. `counterfactual_engine.py` goes from 458 → 230 lines. Added an AST-based guard, `tests/test_no_dice_ml_dependency.py`, that detects executable `dice_ml` references and ignores docstring mentions. Closes #54.
- **D6: `make clean-soft`.** `make clean` used to run `docker compose down -v`, which silently deleted the Postgres volume along with the caches. It is now split into `clean-soft` (caches and build output only, volumes kept) and `clean` (full wipe). `clean` calls `clean-soft` internally for the cache sweep. The README documents `clean-soft` as the day-to-day default, and a guard test pins the split.
- **D7: Release packaging.** `APP_VERSION` advances `1.10.1` → `1.10.2`. Closes the stale issue #56 (the Celery `DJANGO_SETTINGS_MODULE` default, already fixed in `config/celery.py:8` via `os.environ.setdefault`).

### Version bump

`APP_VERSION` advances `1.10.1` → `1.10.2`. No data migrations beyond `0010_add_on_time_payment_pct_validators`. No trained-model invalidation. No API surface changes.

### Scope notes

- Issue #61 (retention regression test for `enforce_retention`) stays open as future work. The command runs in production through the `weekly-data-retention` Celery beat job (`celery.py:95`) but still has no unit coverage. Left out of v1.10.2 on purpose to keep D7 release-only.

## v1.10.1: Production hardening (2026-04-19)

Six atomic deliverables that tighten the production surface without changing model behaviour:

- **D1: Hosted-demo scaffolding removed.** Removed the placeholder wizard, profile and about pages and their fixtures. Nothing in the current build rendered them, and deleting them shrinks the bundle.
- **D2: Extended `make clean`.** `make clean` now removes containers, build caches, test artifacts and tsbuildinfo; the new `make clean-deep` also drops `node_modules` and `backend/.venv`. Both are documented in a new README "Housekeeping" section.
- **D3: Stale model artifact pruning.** A new `manage.py prune_model_artifacts [--dry-run] [--keep N]` command removes stale `.joblib` files under `backend/ml_models/`, keeping the active `ModelVersion` and the N most recent inactive ones (default 3). Covered by 11 pytest cases.
- **D4: Dead-code sweep.** The new `make deadcode` target runs `ruff --select F401,F811,F841` and `vulture --min-confidence 80`; the sweep found one unused parameter, now removed.
- **D5: Robustness audit.** A new `backend/mypy.ini` and a lightweight CI `mypy` job gate the 10 Arm C Phase 1 extraction modules. Adds `make typecheck` / `make security` / `make verify` targets, plus `pip-audit --strict`, `npm audit --audit-level=high --omit=dev` and bandit `-lll`. Frontend `lint:strict` and `typecheck` are available as developer tools but not as a CI gate: 8 react-hooks warnings, intentionally demoted in the Next 16 upgrade, would block it.
- **D6: End-to-end smoke test.** Adds `tools/smoke_e2e.sh` (register → apply → orchestrate → decision → email), a deterministic applicant fixture and a `workflow_dispatch`-only GitHub Actions job. The result is written to `.tmp/smoke_result.json`.

### Version bump

`APP_VERSION` advances `1.10.0` → `1.10.1`. No data migrations. No trained-model invalidation.

## v1.10.0: XGBoost AU lender parity (2026-04-18)

A bundle of 8 deliverables that bring the unified champion XGBoost model to APRA / AU-big-4 production parity, plus a regression-gate JSON file so CI can catch silent metric decay after promotion. The audit areas it targets: APRA CPS 220 model validation, SR 11-7 MRM dossier, APS 112 credit policy overlay, APS 220 referral trail, AFCA 2023 hardship guidance, ASIC RG 209 responsible-lending capture, NCCP Act s.128 unsuitability screen.

### ML / Risk

- **D1: XGBoost monotone constraints.** `ModelTrainer.build_model()` now sets a `monotone_constraints` tuple aligned to feature index order. `credit_score`, `annual_income`, `employment_length` and `years_in_residence` are constrained `+1` (higher input → lower predicted default probability); `debt_to_income`, `num_late_payments`, `num_delinquencies`, `credit_utilization`, `num_hardship_flags`, `loan_amount` and `loan_to_income` are constrained `-1` (higher input → higher PD). The remaining features stay at `0` (free). The justification table is in the MRM dossier §4.
- **D2: Segmented training.** `ModelTrainer` can now fit per-segment bundles (`home_owner_occupier`, `home_investor`, `personal`, `unified`) against the generator's `purpose`-based product split. They share a validation split, and a `SegmentedBundle` accessor lets the predictor route by application intent at inference. The unified model stays the live champion while the segment-specific challengers build up hold-out evidence; promotion gates run per segment.
- **D3: Hard credit policy overlay (shadow-mode default).** The new `backend/apps/ml_engine/services/credit_policy.py` encodes 12 underwriter rules: P01 `has_bankruptcy`, P02 `has_default_last_2y`, P03 `credit_score<550`, P04 `loan_amount<2000`, P05 `loan_amount>500000`, P06 `age<18`, P07 `debt_to_income>0.8` (hard fails); P08 `loan_to_income>9x`, P09 `postcode_default_rate>0.10`, P10 `self_employed AND employment_length<1y`, P11 `num_hardship_flags>=1`, P12 TMD-mismatch (refers). The `CREDIT_POLICY_MODE` env var sets the overlay mode (`off`/`shadow`/`enforce`, default shadow), so the first deploy only logs decisions to audit. Switch to `enforce` after a shadow-period review.
- **D4: Risk-based pricing tiers.** The new `pricing_engine.py` maps (PD, segment) → `PricingTier` (tiers A to D, rate_min/rate_max, rationale) using NAB-aligned bands: personal 7.0 to 24.0%, home 6.0 to 9.0%. Segment normalisation maps `home_owner_occupier` / `home_investor` / `owner_occupier` / `investor` / `investment` → `home` and `personal` / `auto` / `education` / `unified` → `personal`. A rejection returns tier `D` with a midpoint-safe rationale instead of raising.
- **D5: KS / PSI / Brier + champion-challenger promotion gate.** `ModelEvaluator.compute_metrics()` now returns the KS statistic, the Brier score with its Murphy (1973) decomposition (reliability, resolution, uncertainty), PSI against the previous champion's validation bins, and ECE. `model_selector.promote_if_better()` enforces four gates: AUC regression tolerance 0.02pp, KS tolerance 0.015pp, PSI ≤ 0.25, ECE ≤ 0.05. All metrics are stored on `ModelVersion` for audit.
- **D6: Referral audit records (bias-queue-safe).** New `LoanApplication.ReferralStatus` choices (`none` / `referred` / `cleared` / `escalated`) plus `referral_codes` (JSONList) and `referral_rationale` (JSONDict) fields, which `predictor.py` fills in when a policy run returns `refers`. A new admin-only `GET /api/loans/referrals/` endpoint supports `?code=P09,P11`, `?status=referred` and `?limit=100` filters. The bias human-review queue stays bias-only: referral evidence lives on a separate admin surface with no customer-facing UI.
- **D7: MRM dossier auto-generation.** The new `mrm_dossier.py` writes the 11-section APRA/SR 11-7 model-risk-management dossier as plain Markdown (`generate_dossier_markdown(mv) -> str`, `write_dossier(mv, dir) -> str`), with fallback text when PSI, fairness or calibration data is missing. A `post_save` signal on `ModelVersion` enqueues `generate_mrm_dossier_task.delay(id)` (Celery, 300s time limit, 1 retry), controlled by the `MRM_DOSSIER_AUTO_GENERATE` env var (default `true`). A broker outage is non-fatal. `python manage.py generate_mrm_dossier <id>` regenerates the dossier offline. It is written to `<ML_MODELS_DIR>/<id>/mrm.md`.
- **D8: `predictor.py` cleanup.** Split `predict_loan_outcome()` into composed steps (policy overlay resolution → PD inference → segment-aware pricing → referral-audit capture → rationale assembly) and moved Claude / SHAP / policy-code rendering into one structured-logging surface. This lowers cyclomatic complexity on the critical inference path and tightens the contract around `PolicyResult.rationale_by_code`.

### CI / Audit

- **Regression-gate baseline (`backend/ml_models/golden_metrics.json`).** Records the v1.9.9 champion's floor: AUC 0.87, KS 0.45, Brier 0.10, ECE 0.03, Gini 0.74. Tolerances: AUC drop ≤ 0.02pp, KS drop ≤ 0.015pp, Brier rise ≤ 0.02pp, ECE rise ≤ 0.015pp. Refresh it only when a new champion is promoted.
- **Regression-gate service (`backend/apps/ml_engine/services/regression_gate.py`).** A pure function `check_regression(metrics, golden) -> List[str]` (an empty list means pass), plus `load_golden()` and `active_model_metrics()`, which returns `None` when there is no active model so CI on a fresh clone stays green. It complements the runtime champion-challenger gate in `model_selector.py`: the runtime gate blocks promotion, while this static file lets a nightly CI cron catch drift on the currently active model.
- **Regression-gate tests (`backend/apps/ml_engine/tests/test_regression_gate.py`).** 16 tests covering the golden-file shape, required baselines and tolerances, drops in higher-is-better metrics, rises in lower-is-better metrics, compound breaches, skipping missing or non-numeric metrics cleanly, and a `@pytest.mark.django_db` integration test that skips when there is no active model.

### Migration note

No data migration beyond additive fields on `LoanApplication` (0023). Existing trained models still score. To get the monotone, segmented, calibrated champion, retrain through Admin → *Train New Model* or `python manage.py train_ml_model`; the promotion gate stops a silently regressed bundle from becoming active.

### Target

`v1.10.0` is the XGBoost-parity arm of the Arm A / Arm B / Arm C portfolio-polish push. Arm B (stress test, soak, fairness uplift) and Arm C (ml_engine code-review sweep) follow as separate specs.

## v1.9.9: Expose HEM + LMI policy variables as model features (2026-04-18)

### ML

- Four variables that were internal to the underwriter are now model features, so the scorecard can learn the HEM-floor and LMI-capitalisation policies the underwriter enforces at decision time instead of re-deriving them implicitly from raw inputs:
  - `hem_benchmark`: Household Expenditure Measure lookup for the applicant's family structure and income tier (the same `get_hem()` call the underwriter uses when computing `effective_expenses`).
  - `hem_gap`: declared `monthly_expenses` minus `hem_benchmark`. A positive value means the applicant's declared spending already clears the HEM floor; a negative value means the HEM floor bites in serviceability.
  - `lmi_premium`: capitalised Lenders Mortgage Insurance premium (0 for non-home loans, tiered 1%/2%/3% at LVR 80/85/90% thresholds, matching AU market rate cards).
  - `effective_loan_amount`: `loan_amount + lmi_premium` (mirrors `UnderwritingEngine._compute_effective_loan_amount`).
- Extended `ModelTrainer.NUMERIC_COLS` in `backend/apps/ml_engine/services/trainer.py`. `feature_engineering.DEFAULT_IMPUTATION_VALUES` gets safe defaults so historical rows still fit. At inference, `ModelPredictor` derives the four features by calling `UnderwritingEngine.get_hem()` (falling back to 2950.0) and applying the LVR-tier LMI schedule, the same logic the generator uses.
- A new `TestUnderwriterPolicyFeatures` test class in `backend/tests/test_data_generator.py` pins the realism contract: HEM rises with dependants, HEM gap = expenses − benchmark, LMI is zero for personal/car/business loans and for LVR ≤ 80%, LMI is charged on home loans above 85% LVR, and `effective_loan_amount = loan_amount + lmi_premium`.
- `test_feature_consistency.TestFeatureAlignment.test_trainer_features_in_generated_data` now checks the four new columns against the generated dataframe automatically.

### Migration note

Existing trained models are unaffected, because each bundle stores its own feature set. To use the new features, run **Train New Model** in Admin so a fresh bundle is fit with the expanded `NUMERIC_COLS`.

## v1.9.6: Workstream B (partial), throttle & version fixes (2026-04-18)

### Security

- Scoped throttle on `ComplaintViewSet.create`: `ComplaintFilingThrottle` (`complaint_filing` scope, 10/hour per user). Complaint filing was only covered by the default 60/min user throttle, which left the endpoint open to spam and possibly abusive complaint floods. List and retrieve paths are unaffected.
- Scoped throttle on `CustomerDataExportView`: `DataExportThrottle` (`data_export` scope, 10/hour per user). Privacy Act APP-12 self-service export is low-frequency by nature, and the view runs a heavy `prefetch_related` across loans, decisions, emails, agent runs, bias reports and marketing emails, so a tight cap is a modest guard against accidental or deliberate resource exhaustion.
- Three new tests in `backend/tests/test_security_throttles.py` assert 10 successful calls then 429 on the 11th, and that the filing cap does not affect complaint list access.

### Housekeeping

- Bumped `APP_VERSION` in `backend/config/settings/base.py` from `1.8.1` → `1.9.6`; it had been stale since v1.8.2. The version shows up in the `/api/v1/health/` output.

Deferred to future sweeps: moving CSP from `REPORT_ONLY` → enforce (needs a review of production reports first), and a field allowlist for `CustomerDataExportView` (the current reflective `_meta.get_fields()` is APP-12-safe but fragile).

## v1.9.5: Workstream D, dead-code cleanup (2026-04-18)

### Housekeeping

- Removed 8 unused frontend components (608 lines), confirmed orphaned with `knip` and a manual import grep. No page, test or doc referenced them.
  - `components/agents/PipelineSummaryBar.tsx`, `components/agents/StepLatencyChart.tsx` (superseded by the PR #75 agents-UI removal).
  - `components/applications/CustomerDenialExplanation.tsx` (replaced by `components/loans/DenialExplanation.tsx`).
  - `components/dashboard/ApprovalTrendChart.tsx`, `components/dashboard/PipelineStats.tsx` (left unused by the dashboard redesign).
  - `components/layout/ComplianceFooter.tsx` (compliance moved into page-level disclosures).
  - `components/metrics/DriftFeatureTable.tsx`, `components/metrics/ModelComparison.tsx` (model-metrics page re-implemented inline).
- Dropped `@types/dompurify` from `frontend/package.json`. `dompurify` 3.x ships its own type definitions at `dist/purify.cjs.d.ts`, so the separate types package did nothing.
- Minor lint fix in `loadtests/locustfile.py`: removed unused `resp = ` assignment in `ApplicantUser.create_application`.

No behaviour change. `npm run build`, `tsc --noEmit` and the backend pytest suite still pass.

## v1.9.4: Security & reliability follow-ups (2026-04-18)

### Security

- Validate complaint ownership on create. `ComplaintSerializer` now rejects (400) a complaint whose `loan_application` belongs to another customer; staff (`admin`/`officer`) may still file on behalf of customers, which is recorded as `details.on_behalf_of_id` on the new `complaint_filed` audit entry. Addresses Codex adversarial review finding #3 (second pass).

### Reliability

- Hard-cap batch orchestration default path at 100 applications (was unbounded). The `recheck=true` path already had the cap; the default `POST /api/v1/agents/orchestrate-all/` now applies the same limit, orders oldest-first, and reports `skipped` + a drain-hint `detail` when the backlog exceeds the cap. The `batch_pipeline_triggered` audit entry gains a `skipped_count` field. Addresses Codex adversarial review finding #2 (second pass).

## v1.9.3: Security & reliability hardening (2026-04-18)

### Security

- Enforce Django CSRF validation on cookie-based JWT authentication. Mutating requests authenticated via the `access_token` HttpOnly cookie now require a matching `X-CSRFToken` header. Bearer-header auth is unchanged. Addresses Codex adversarial review finding #1.
- Gate `/metrics` and deep-health behind auth. `/metrics` now requires a staff session or an `X-Health-Token` header (it was unauthenticated). Removed `/metrics` from the public Kubernetes ingress; Prometheus can still reach it on the internal network. `deep_health_check` refuses to respond (503) in non-DEBUG environments when `HEALTH_CHECK_TOKEN` is unset, so production won't silently leak diagnostics. The Prometheus scrape config carries the token via `http_headers`. Addresses Codex adversarial review finding #2.

### Reliability

- Orchestrate endpoint is now idempotent by default. The non-force path short-circuits when a completed `AgentRun` exists and returns the existing run ID instead of dispatching. `force=true` requires `admin`/`officer` role AND a non-empty `reason` query/body param, and writes an `AuditLog(action="pipeline_force_rerun")` entry before dispatch, so every force rerun is traceable to a named user and a reason. The frontend drops the unconditional `?force=true` from `orchestrate()` and exposes a separate `useForceRerun` hook, wired into the staff-only human-review page behind a dialog that collects the reason. Addresses Codex adversarial review finding #3.
- Submission-path durability: loan `perform_create` now dispatches `orchestrate_pipeline_task` under `transaction.on_commit`, and a broker outage no longer swallows submissions. Failed dispatches land in a new `PipelineDispatchOutbox` table and the loan moves to `status=queue_failed`. A Celery beat task, `retry_failed_dispatches`, drains the outbox every 60s with a 5-attempt cap; exhausted rows show up in the admin. Addresses Codex adversarial review finding #4.

## 1.9.2 (2026-04-18)

Email aesthetic v2 redesign. A 6-PR stack (#69 to #74) rebuilt the approval, denial and marketing emails as Gmail-safe HTML with a proper visual hierarchy. The plain-text-first pipeline and the existing compliant content (Sarah Mitchell tone, Banking Code alignment, apology-free denial wording) are kept.

- **PR #69:** Shared `html_renderer.py` with design tokens (brand colors, type scale, spacing), inline CSS, a 600px max width and a `<table role="presentation">` skeleton. One pure-Python renderer drives both the dashboard preview and the Gmail recipient view.
- **PR #70:** TypeScript port at `frontend/src/lib/emailHtmlRenderer.ts` with the same tokens. A new CI gate (`.github/workflows/email-parity.yml`) enforces byte-for-byte parity between the Python and TypeScript snapshots, so the preview can't drift from what Gmail renders.
- **PR #71:** Approval-specific blocks: success hero with loan-type line, loan-details card with `SUCCESS`-colored left border, next-steps pill rows, CTA button, attachments chips, signature block.
- **PR #72:** Denial-specific blocks: caution hero, assessment-factors card (plain-English factor list), what-you-can-do card, free credit report card, dual CTA (call Sarah + email). No apology language.
- **PR #73:** Marketing offer cards with `MARKETING`-colored left border, 11px uppercase label, 17px title, bulleted benefits and an italic "why it fits" line. Mandatory unsubscribe footer (Spam Act 2003), a conditional FCS disclaimer when the body mentions term deposits, and a conditional bonus-rate disclaimer.
- **PR #74:** Playwright visual regression that loads the shared HTML snapshots with `page.setContent()` (no backend or dashboard dependency), plus 7 Gmail-safe lint tests (`<td>` margin ban, https/tel/mailto only, zero `<img>`, CTA contrast, no `javascript:` URLs, no Outlook conditional comments, `role="presentation"` on all tables). Pixel screenshots are opt-in via `PLAYWRIGHT_SCREENSHOTS=1`; CI runs cross-platform content assertions.

Design tokens and snapshots are the source of truth: if either renderer drifts, CI fails. Unicode icons (✓ ✦ Ⓘ 📎) replace images, so Gmail's default image blocking doesn't degrade the branding.

Post-merge manual Gmail smoke test: approval, denial and marketing emails sent to the dev inbox all render with the intended hero blocks, cards and CTAs on Gmail web.

## 1.9.1 (2026-04-17)

Portfolio-polish pass in response to an external Claude review (same day, 9.2/10 baseline). Four atomic PRs landed on `master`.

- **A: DataGenerator post-outcome leak regression test** (#63). Extracted a `POST_OUTCOME_FEATURES` frozenset in `apps/ml_engine/services/data_generator.py` and added `test_training_features_exclude_post_outcome_columns` and `test_post_outcome_features_constant_is_not_empty`. CI fails if any post-outcome field joins the training feature set, or if the constant is emptied so the check passes vacuously.
- **B: Backend test collection + coverage gate bump; frontend multi-metric threshold** (#64). Setting `testpaths = ["tests", "apps"]` in `backend/pyproject.toml` picked up 20 tests that had never been collected (counterfactual engine, orchestrator CF, CF integration, serializer CF). Coverage went from 61.35% → 63.98%, and `--cov-fail-under` from 60 → 63. Frontend vitest now enforces `lines: 65, statements: 65, functions: 75, branches: 75` (before, only `lines: 60`), set at the measured floor.
- **C: Stale `feat/*` PR triage** (#1, #3, #4, #5 closed with rationale). Audited four stale `feat/*` PRs from an older Claude Code session. #1 was closed as "too large to review as one PR"; #3/#4 were closed because the base had diverged and the force-push policy blocked a clean rebase; #5 was closed as a half-finished placeholder, per user preference.
- **D: 431-line `ci.yml` split into lint/test/security/build** (#65). Four workflows, one per concern. Deploy's `needs:` shrinks to `[docker-build, dast-scan]` because GitHub Actions doesn't support cross-workflow `needs:`; branch-protection rules require the upstream workflows to be green instead. The nine required-status-check job names are unchanged, so no admin UI change was needed.

Response document: `docs/reviews/2026-04-17-v1.9.1-review-response.md`.

Tracked follow-up (not in this pass): coverage phase 2, with targeted tests for `counterfactual_engine` (11%), `marketing_agent` (11%) and `next_best_offer` (13%) to move toward the external review's 75% target.

## 1.9.0 (2026-04-17)

Portfolio production-polish pass with 18 tasks in two tiers: governance and operability documentation (Tier A) and latent-bug fixes with regression tests (Tier B). 20 PRs shipped (#15 to #48).

**Tier A: portfolio signal & operability**

- Published a P0 cumulative code review (`docs/reviews/2026-04-17-p0-baseline.md`); its 12 findings are triaged into fold-ins, follow-ups and a parking lot.
- Pre-commit hook stack (ruff, bandit, pip-audit, gitleaks) matches the CI gates, so contributor laptops and CI can't diverge.
- `pyproject.toml` split from `requirements.txt`: ruff/bandit/pytest config lives in one place, dev-only deps are separate, and Dependabot watches both.
- CODEOWNERS + PR/issue templates enforce review attribution.
- ADR scaffold (`docs/adr/*`) with four initial decisions: Gaussian-copula synthetic data, XGBoost-with-monotonic-constraints over LR, Celery multi-queue topology, Redis-fallback budget guard.
- `README.md` rewritten to put the production details first (decision latency, fairness-gate budget, bias-detection flow).
- Operational runbooks (`docs/runbooks/*`) for the six most likely incidents (Redis down, Claude outage, budget exhausted, model drift, pipeline stuck, DAST ZAP alarm).
- SLI/SLO catalogue (`docs/slo.md`) with four production SLOs (pipeline-e2e P95, email-gen error rate, ml-prediction latency, bias-review TTR). The catalogue itself lists 4 custom-metric instrumentation gaps as follow-ups.
- Australian compliance doc (`docs/compliance/australia.md`) mapping NCCP, Privacy Act APP, ASIC RG 209 and APRA CPG 235 to controls in code.
- Engineering journal and interview talking points (`docs/engineering-journal.md`, `docs/interview-talking-points.md`) for walk-throughs with hirers.

**Tier B: latent fixes with regression tests**

- **F-01/F-02/F-03:** Every `.update(status=...)` call that bypassed the state machine in `apps/agents/services/*` now uses `transition_to()` inside the existing atomic block, each with a `details.source` audit tag. A static-guard test fails if the raw pattern comes back.
- **F-04:** The `api_budget` Redis-fallback counter is now guarded by a lock (`threading.Lock`) and resets when Redis recovers, so a transient outage no longer bricks the worker for good. The regression test runs 1,000 concurrent increments across 16 threads and asserts the exact count.
- **F-05:** Celery integration tests now assert the expected exception type for each task instead of `result is not None`, so a task stuck in serialisation fails the test. This exposed a latent Postgres locking bug in `human_review_handler.py` (`select_for_update` against a nullable OneToOne LEFT JOIN), which is now fixed.
- **B1:** DiCE counterfactual timeout raised from 30s to 120s to cover the slow end of the search frontier, which is what the notebook-validated experiment needs.
- **B2:** Celery `prefetch_multiplier=1` + `acks_late=True` for IO workers, so long-running Claude calls no longer starve peer tasks.
- **B2.5:** Fixed frontend exit code 243 (Node heap cap and healthcheck window), which ends the dev-server crash loop on low-memory laptops.

Post-merge follow-ups tracked as GitHub issues: 4 SLO custom-metric instrumentation gaps; F-06 (`dice-ml>=0.11`), F-07 (`on_time_payment_pct` validator), F-08 (`celery.py` settings default), F-09 (Grafana default password); F-10 (email availability probe), F-11 (CI Fernet key), F-12 (bandit severity gate); regression test for `enforce_retention`.

## 1.8.1 (2026-04-02)

Security hardening from code review: restrict ML views to admin/officer, bind monitoring ports to localhost, timing-safe health check tokens, pin Trivy action to commit SHA after supply-chain advisory.

Fixes: Optuna `fit_params` kwarg, LVR interaction magnitude error (`/100`), reject inference clobbering train imputation values, watchdog connection leak, frontend `setTimeout` cleanup.

## 1.8.0 (2026-04-02)

- Optuna Bayesian hyperparameter optimisation replaces RandomizedSearchCV
- 4 new feature interactions (LVR x property growth, deposit x income stability, DTI x rate sensitivity, credit x employment)
- Self-healing watchdog container (stuck task detection, idle DB connection cleanup)
- Trivy container image scanning in CI

## 1.7.0 / 1.7.1 (2026-04-01)

Application state machine, fairness gate (EEOC 80% rule), repayment estimator component, NCCP/AFCA/Privacy disclosures. Sentry error tracking. SA3-level property data. RBA and AIHW benchmark integration.

## 1.6.0 (2026-03-31)

Big data generator overhaul: 65+ features, Gaussian copula correlations, 6 borrower sub-populations, state-specific profiles, macro features (RBA cash rate, unemployment), CDR/Open Banking features, CCR. CalibrationValidator for APRA benchmark comparison.

## 1.5.0 (2026-03-27)

Pipeline auto-completion, champion/challenger model scoring, conformal prediction intervals, stress testing (4 scenarios), counterfactual explanations, PSI drift detection, monotonic constraints.

## 1.4.0 (2026-03-27)

k6 load tests, ModelValidationReport for SR 11-7, data retention lifecycle, `validate_model` management command.

## 1.3.0 (2026-03-27)

TOTP 2FA, soft deletes, Fernet encryption on address/phone/employer, retraining policy field, weekly fairness alerting, Schemathesis contract tests.

## 1.2.0 (2026-03-26)

Docker resource limits, PII masking log filter, model governance fields, credit score disclosure in denial emails.

## 1.1.0 (2026-03-24)

Fraud detection, decision waterfall, conditional approvals, model card generator, field-level encryption with key rotation.

## 1.0.0 (2026-03-24)

Production deployment config (multi-stage Docker, gunicorn), monitoring stack (Prometheus/Grafana/AlertManager), OWASP ZAP DAST in CI, Playwright E2E tests.

## 0.1.0 - 0.5.0 (2026-03-19 to 2026-03-24)

Initial build: XGBoost pipeline with SHAP, synthetic data generator (Gaussian copula), Claude email generation with 10 guardrails, bias detection (regex + LLM), NBO engine, orchestrator, JWT auth with roles, Celery queues, Docker Compose, CI/CD pipeline.
