# Engineering Journal — Loan Approval AI System

> A narrative record of how this project was built, why each major decision was made, what went wrong, and how the rough edges were ground down. Written so a reader (hiring manager, teammate, future-me) can understand not just *what* was shipped but *why it was shipped that way*.

**Project:** Australian Loan Approval AI System
**Timeline:** project start → current polish pass (2026-04-17)
**Current version:** see `CHANGELOG.md` top entry (v1.8.2)
**Status:** portfolio / demonstrator — not in production use

---

## 1. Project origin and framing

The brief was a three-level AI system in the shape of Sajjaad Khader's loan approval demo: ML scoring, LLM email generation, and an agentic pipeline on top. The interesting engineering question wasn't the demo shape — it was whether the system could hold up to the regulatory load that a real Australian lender carries: NCCP responsible lending, Privacy Act APP obligations, APRA serviceability buffers, Banking Code transparency on denials. If that layer is thin, nothing else matters for the role it's targeted at.

That reframing drove every subsequent decision. The ML model is useful but not the point. The email generation is impressive but not the point. The point is: can this thing defend the decision it just made, in the language a regulator expects, with an audit trail that holds up?

## 2. Architecture — the WAT layering

The system follows the Workflows-Agents-Tools (WAT) pattern:

- **Workflows** (markdown SOPs in `workflows/`) describe the procedure
- **Agents** (AI reasoning) choose which tool to invoke and when
- **Tools** (Python services in `backend/apps/*/services/`) are deterministic

This is useful because the probabilistic parts (Claude writing an email, SHAP picking reason codes) are cleanly separated from the deterministic parts (guardrail checks, APRA buffer calculations, retention policy enforcement). It means every probabilistic output flows through a deterministic gate before it reaches a customer.

For the Django layout, service-layer patterns were chosen over fat views: each app has `services/` modules that do the real work, views are thin. Tests target the services. ADR 007 (`backend/docs/adr/007-wat-architecture.md`) captures the reasoning.

## 3. Data — the big rewrite in v1.6.0

The original data generator produced clean, label-leaked synthetic records that trained models to 0.99 AUC. That felt fraudulent. In v1.6.0 (March 2026) the generator was rewritten end-to-end:

- Gaussian copula correlations between income, credit score, expenses, DTI, LVR
- Six borrower sub-populations with realistic state-specific profiles
- ATO, ABS, APRA, RBA, Equifax statistics as calibration anchors
- Latent variables the model can't see (documentation quality, savings patterns, employer stability)
- Underwriter disagreement noise and measurement error
- A 1000-line rules-based underwriting engine producing the labels, with outcomes run through a separate loan-performance simulator

Result: test AUC settled at 0.87–0.88 with Optuna-tuned XGBoost, 0.84–0.85 with default hyperparameters. That number is honest — a reproducible benchmark on a 2,000-record subset is recorded in `docs/experiments/benchmark.md` for exactly this reason. ADR 001 covers the copula choice.

## 4. The model — XGBoost with guardrails on top

XGBoost with 21 monotonic constraints (higher income → lower risk, etc.) was chosen over an LR scorecard for lift, with the tradeoff that monotonicity is what makes the model defensible. ADR 002 documents it. Every training run fits a logistic-regression baseline on the four core features and records `training_metadata.baseline_auc` plus `xgb_lift_over_baseline` — so "why did you use XGBoost" has a specific number, not marketing copy.

Other ML parts that came in over time:

- **IV-based feature selection** so the 71 inputs don't all fight for the model's attention
- **PSI/CSI drift monitoring** with a weekly Celery beat task
- **SR 11-7-style ModelValidationReport** — the output is what a regulator expects, not a notebook dump
- **Conformal prediction intervals** on top of raw probabilities for high-stakes decisions
- **APRA +3% stress buffer** baked into the serviceability rule
- **SHAP-mapped adverse-action reason codes** (70 of them, compiled from real denial-letter language)
- **Reject inference** using the parcelling method so the training label space isn't biased by who actually got approved in the simulator
- **Walk-forward temporal CV** recorded alongside the random-CV AUC so the drift gap is visible

## 5. The emails — template-first with a Claude escape hatch

Claude is not writing every denial letter from scratch. That would be: expensive, slow, inconsistent, and regulatorially dangerous. The pattern is **template-first**: every email starts from an audited template, and Claude is only invoked to generate the personalised reason-code section. The whole thing then runs through 15 deterministic guardrails before it goes out:

1. Prohibited language (discrimination acts)
2. Hallucinated dollar amounts (validated against application data)
3. Aggressive tone
4. Overly formal / corporate phrasing
5. Unprofessional financial language
6. Markdown / HTML rejection (plain text only)
7. Word count limits
8. Required regulatory elements (AFCA reference, cooling-off period, etc.)
9. Double sign-off detection
10. Sentence rhythm uniformity (flags suspiciously even sentence lengths)

Plus five more added over the project for the Australian denial tone specifically — including enforced **no apology / no disappointment language**, which matters because Australian banking guidance interprets that language as admission of wrongdoing. ADR 006 covers the cost cap (<$5/day on the Anthropic API) and the fallback when the cap is hit.

The guardrails layer has its own regression suite (`tests/test_guardrails.py`, `test_guardrails_comprehensive.py`) — every guardrail is a pure function, so tests run in ms.

## 6. Bias — three layers

ADR 003 documents the pipeline: regex pre-screen scores 0–100, Claude reviews the 60–80 band with a confidence gate, everything >80 or Claude-confidence <0.70 goes to human review. This wasn't my first attempt.

The v1 bias detector was a 989-LOC god class that did detection, scoring, escalation, audit logging, and notification. It worked but was unmaintainable. PR #13 (commit `d18ce4c`) split it into a `bias/` package with single-responsibility modules. The split happened specifically because a code-quality review flagged that the file was holding concerns that changed at different cadences — the regex patterns change with new discrimination law, the Claude review logic changes with prompt engineering, the escalation routing changes with org structure. Keeping them in one file made every change a merge conflict.

## 7. The Celery pipeline

All work behind the API is a single orchestrator Celery task that moves an `AgentRun` record through states. That was a deliberate choice: one task per pipeline means one log trace, one error path, one retry unit. The alternative — micro-tasks chained through Celery groups — was rejected because debugging a broken pipeline with four handoffs and three retry policies is where engineer-hours go to die.

What makes it resilient:

- **Separate queues per workload** (`ml`, `email`, `agents`) so a CPU-bound ML run can't starve a fast bias-review task
- **`task_acks_late=True`** (added in the April 2026 polish pass) so workers killed mid-task don't drop work
- **`task_reject_on_worker_lost=True`** for the same reason
- **`prefetch_multiplier=1`** on the ML queue specifically (CPU-bound work gets one task at a time so the worker can't hold a second ML task hostage while it's running)
- **`worker_max_tasks_per_child=1000`** to recycle any accumulated native state (XGBoost + OpenMP threads leak across tasks)
- **A watchdog service** in the core stack that polls every 30 seconds for applications stuck >5 minutes and re-queues them — so transient broker failures self-recover rather than zombie the pipeline

## 8. Security — learned from code review, not intuition

The security story was aggressive but not theatrical. Every piece came from an actual review finding, not a checklist:

- JWT with HttpOnly cookies (not localStorage)
- Argon2 password hashing (not bcrypt — it tolerates GPU attacks worse)
- 60-minute access / 7-day refresh with rotation and blacklist
- Fernet field-level encryption for PII at rest (key rotation via `rotate_encryption_key` command)
- Rate limiting: 20/min anon, 60/min auth
- CORS locked to frontend origin
- Three RBAC roles with per-endpoint permission checks
- Prompt injection defences on user text entering LLM prompts
- Trivy container scanning pinned to commit SHAs after the supply-chain advisory in April 2026
- Bandit SAST, gitleaks, npm audit, OWASP ZAP DAST on every CI run

ADR 008 documents the layered threat model.

## 9. The mistakes

**Over-engineered denial emails in v0.** The first denial emails tried to be empathetic. They triggered the regulatory red flag (apology language). The fix was a hard-coded guardrail rule plus a persistent note in the memory layer so future work can't re-introduce it.

**Dev frontend container exit-243 crash loop.** The Next.js dev server inside the container kept dying. For months the response was "restart it". The April 2026 polish pass finally root-caused it: Node heap default was larger than the cgroup memory, so the OS reaped it with signal 15 → exit code 243. The fix is three lines in `docker-compose.yml` (`NODE_OPTIONS=--max-old-space-size=768`, `mem_limit: 1g`, `healthcheck.start_period: 90s`). Documented in `docs/runbooks/frontend-exit-243.md`.

**Flaky Hypothesis tests.** Hypothesis would generate edge cases that revealed real bugs, then the same generation would pass next run. For a while these were marked `@skip`. That's a lie — it tells your CI the code works when it doesn't. PR #12 (`3c48b71`) pinned the seeds, simplified the strategies, and removed the skip guards.

**989-LOC bias_detector.** Covered above. The lesson: when a file is doing three things that change on different clocks, the file is wrong.

**CounterfactualEngine timeout mismatch.** The DiCE counterfactual engine was called with `timeout_seconds=10` but internally defaulted to `timeout_seconds=15`. Rarely the internal timeout won, which meant the caller saw "no fallback" while logs showed a timeout. April 2026 fix (PR #36): align both to 20s and cut `total_CFs=5→3` to hit the budget.

**Assumed the model was the product.** For the first few months the polish went into making AUC look better. The realisation that regulatory defensibility, audit trails, and guardrail breadth were the actual product came later and reframed everything after that point.

## 10. The rating journey

Self-rating after an exhaustive audit in April 2026 was 8.9/10. The polish pass to push it toward 9.5/10 drove this set of PRs:

- **A1** — ADR scaffold so architectural decisions live in version control, not memory
- **A2** — Mermaid architecture diagram + 60-second quickstart in the README
- **A3** — pre-commit config with ruff, gitleaks, hygiene hooks
- **A4** — `pyproject.toml` + split dev dependencies
- **A5** — Dependabot config for pip, npm, and github-actions
- **A6** — CODEOWNERS + PR/issue templates
- **A7** — operational runbooks (frontend exit-243, Celery backpressure, migration rollback)
- **A8** — SLI/SLO catalogue
- **A9** — Australian compliance doc mapping every obligation to a code path
- **A10** — this engineering journal + the interview talking-points companion
- **B1** — DiCE counterfactual timeout/total_CFs fix (engineering honesty: the code didn't match the spec)
- **B2** — Celery prefetch and ack tuning (covered in §7)
- **B3/B4/B5** — three targeted fixes from the P0 baseline code review (state-machine bypass audit, api_budget thread-safety, Celery integration test assertions)

The polish pass is itself an example of the engineering philosophy: observe what's there, cite with specifics, fix the minimum, leave breadcrumbs for future-you.

## 11. What would a production rollout need

This is a portfolio project. Before real users, it would need:

- **Real historical training data**, not synthetic — the TSTR validator estimates real-world AUC around 0.82, but that's a guess
- **Compliance sign-off** — no licensed professional has reviewed the Australian obligations doc yet
- **Paging on SLO breach** — the SLO catalogue lists targets but nothing pages
- **Multi-region failover** — currently single-region Docker Compose
- **Secrets management beyond .env** — Vault or AWS Secrets Manager rather than environment variables
- **Pre-deploy migration review** — for anything touching `Application` or `AuditLog`
- **Model-card sign-off workflow** — new `ModelVersion` should require a formal review step before `is_active=True`

## 12. What I'd do differently

- **Start with the compliance doc, not the model.** Knowing the regulatory frame earlier would have shaped data generation, the AuditLog schema, and the retention command. Instead compliance was reverse-engineered after the fact, which meant rewriting.
- **Write ADRs from day one.** Without them, "why is it this way" lives only in commit messages, which drift and get squashed. The ADRs added in April 2026 recover decisions that were clear at the time but hard to reconstruct.
- **Separate the probabilistic and deterministic layers sooner.** The WAT pattern clicked six months in. Before that, guardrails were mixed into email generators, bias detection into orchestrators. The rewrite cost time that could have been saved by drawing the boundaries early.

---

*Reviewed: 2026-04-17. Next review on the next major polish pass or if the project restarts after ≥90 days of dormancy.*
