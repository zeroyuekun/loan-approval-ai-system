# Interview Talking Points — Loan Approval AI System

> Short cards for a 45-minute technical screen. Each card is one architectural choice, phrased so it can be said out loud in under a minute, with the follow-up questions an interviewer is likely to ask. Pair with `docs/engineering-journal.md` for the long version.

---

## Card 1 — Framing: why the compliance layer is the product

**Say it:** "The demo this was based on is a three-level AI system: ML, LLM emails, agent pipeline. What's interesting about building that in the Australian lending space isn't the AI — it's whether the system can hold up to NCCP responsible lending, APRA serviceability, Privacy Act APPs, and the Banking Code of Practice. If the compliance layer is thin, nothing else matters. So I reframed the project around that."

**Follow-ups to expect:**
- *Which obligation was hardest to implement?* → APP 11 field-level encryption + retention — Fernet at rest, rotation command, enforce_retention management command that hard-deletes at the policy horizon.
- *Where is compliance actually wired in?* → `docs/compliance/australia.md` maps each obligation to a code path. The file is verified — every cited path exists.
- *What's missing for production?* → No licensed professional has signed off. That's called out in the README and the journal.

---

## Card 2 — WAT architecture

**Say it:** "Workflows, Agents, Tools. Workflows are markdown SOPs describing the procedure. Agents are the probabilistic parts — Claude deciding how to word something, SHAP deciding which features explain a denial. Tools are deterministic Python services. Every probabilistic output passes through a deterministic gate before a customer sees it."

**Follow-ups to expect:**
- *Why not put all of this in agents?* → Because probabilistic gates aren't auditable. A regulator asking "why did you deny this applicant" needs a deterministic answer path.
- *Where does the line sit?* → ADR 007. Email text is probabilistic, but guardrails are deterministic. SHAP feature importance is probabilistic, but the reason-code mapping is deterministic.

---

## Card 3 — Data: the rewrite that made metrics honest

**Say it:** "The first data generator produced clean synthetic records with label leakage — XGBoost hit 0.99 AUC. That's fraudulent. In v1.6.0 I rewrote the generator: Gaussian copula correlations, six borrower sub-populations, statistics anchored to ATO/ABS/APRA/RBA/Equifax, latent variables the model can't see, underwriter disagreement noise, and a 1000-line rules-based underwriting engine producing labels. AUC settled at 0.87–0.88 Optuna-tuned, 0.84–0.85 default. That's honest."

**Follow-ups to expect:**
- *Why copula instead of just sampling marginals?* → Cross-variable dependence matters. Income and credit score correlate in the real world; independent sampling makes the learning task artificial.
- *How do you know 0.87 is realistic?* → TSTR validator estimates real-world AUC around 0.82. Walk-forward temporal CV AUC is reported alongside random-CV AUC so the drift gap is visible. ADR 001.

---

## Card 4 — XGBoost with monotonic constraints

**Say it:** "XGBoost over a logistic scorecard for lift, but with 21 monotonic constraints — higher income always reduces risk, lower DTI always reduces risk, etc. Monotonicity is what makes the model defensible to a regulator: I can point at the constraints and show that the model cannot produce a perverse decision where a better applicant scores worse."

**Follow-ups to expect:**
- *How much lift?* → Measured, not assumed. Every training run fits a logistic baseline on four core features and records `baseline_auc` plus `xgb_lift_over_baseline` in training metadata. ADR 002.
- *What else?* → IV feature selection, isotonic calibration, conformal prediction intervals for high-stakes cases, SHAP-mapped to 70 adverse-action reason codes, APRA +3% stress buffer, parcelling-based reject inference.

---

## Card 5 — Emails: template-first, Claude narrowly scoped

**Say it:** "Claude doesn't write denial letters from scratch. It would be expensive, slow, inconsistent, and regulatorially dangerous. Every email starts from an audited template. Claude is invoked only to personalise the reason-code section. Then 15 deterministic guardrails run before send — prohibited language, hallucinated dollar amounts, overly formal phrasing, apology language, word count, required AFCA reference, and so on."

**Follow-ups to expect:**
- *Why is apology language banned?* → Australian banking guidance interprets it as admission of wrongdoing. There's an explicit guardrail, a test, and a persistent note in the project so it can't come back.
- *Cost?* → <$5/day on the Anthropic API with a hard cap and deterministic fallback if the cap hits. ADR 006.
- *Guardrail tests?* → Pure functions, test suite runs in milliseconds.

---

## Card 6 — Bias: three layers

**Say it:** "Regex pre-screen scores a generated email 0–100 on bias-sensitive patterns. Anything under 60 passes. The 60–80 band goes to Claude with a confidence gate — if Claude says 'clean, confidence ≥ 0.70', it passes; otherwise human review. Anything over 80, or low-confidence Claude output, always goes to human review."

**Follow-ups to expect:**
- *Why not just Claude?* → Slower, more expensive, and not deterministic. Regex catches the obvious 95% for free.
- *Why not just regex?* → Misses context. "Applicants in this area" might be fine or might be a suburb-based proxy for protected attributes.
- *Design history:* → v1 was a 989-LOC god class mixing detection, scoring, escalation, audit, notification. PR #13 split it into a `bias/` package with single-responsibility modules. The trigger was a code review pointing out that each concern changes at a different cadence.

---

## Card 7 — Celery: one orchestrator task per pipeline

**Say it:** "The agent pipeline is one Celery task that moves an AgentRun record through states. Not four micro-tasks chained through groups. One task = one log trace, one error path, one retry unit. Debugging a chained pipeline with four handoffs is where engineer-hours die."

**Follow-ups to expect:**
- *What about resilience?* → Separate queues per workload (ml, email, agents); `task_acks_late=True` so killed workers don't drop work; `task_reject_on_worker_lost=True`; `prefetch_multiplier=1` on the ML queue because CPU-bound work can't share a worker; `worker_max_tasks_per_child=1000` because XGBoost + OpenMP leak native state.
- *What if the task itself dies?* → Watchdog service polls every 30s for applications stuck >5 min and re-queues them.

---

## Card 8 — Security: layered and learned, not checklist-driven

**Say it:** "JWT in HttpOnly cookies, not localStorage. Argon2, not bcrypt — it handles GPU attacks better. 60-minute access / 7-day refresh with rotation and blacklist. Fernet field-level encryption for PII with a key rotation command. Rate limiting per role. Trivy, Bandit, gitleaks, OWASP ZAP on every CI run. Each piece came from a specific review finding, not a checklist."

**Follow-ups to expect:**
- *Prompt injection defence?* → Yes — user text entering the LLM prompt is sanitised and the system prompt is pinned.
- *Supply chain?* → Trivy images pinned to commit SHAs after the April 2026 supply-chain advisory.
- *ADR?* → 008 for the layered threat model.

---

## Card 9 — Mistakes and what they cost

**Say it (pick one):**

- **Denial emails tried to be empathetic.** Apology language triggered the regulatory red flag. Fix was a hard-coded guardrail and a persistent project note. *Lesson:* tone in regulated writing is a correctness property.
- **Dev frontend container exit-243.** Crash-looped for months and I kept restarting it. Root cause was Node heap default larger than the cgroup memory — OS killed it with signal 15, Node reported exit 243. Fix is three lines of docker-compose (`NODE_OPTIONS=--max-old-space-size=768`, `mem_limit: 1g`, `healthcheck.start_period: 90s`) plus a runbook. *Lesson:* stop treating symptoms, find the root cause even when the workaround is cheap.
- **Flaky Hypothesis tests marked `@skip`.** That tells CI the code works when it doesn't. PR #12 pinned seeds, simplified strategies, removed the skips. *Lesson:* flaky tests are lies.
- **989-LOC `bias_detector.py`.** Everything worked, nothing was maintainable. Different concerns changed on different clocks and every change was a merge conflict. *Lesson:* when a file is doing three things that move on three clocks, the file is wrong.
- **CounterfactualEngine timeout mismatch.** Caller passed `timeout_seconds=10` but default was 15, so the internal timeout sometimes won and the caller saw "no fallback" when logs showed a timeout. April 2026 fix aligned both to 20s and cut `total_CFs=5→3`. *Lesson:* when two layers have the same parameter with different defaults, the system has a bug waiting to fire.
- **Assumed the model was the product.** Spent the first few months optimising AUC. Reframing around regulatory defensibility, guardrail breadth, and audit trails happened too late. *Lesson:* compliance isn't a wrapper — it shapes the data model and schema. Start there.

---

## Card 10 — Rating journey: the polish pass

**Say it:** "In April 2026 I self-audited and landed at 8.9/10. I wrote out what was missing and turned it into a sequence of small PRs — ADR scaffold, README quickstart, pre-commit, Dependabot, CODEOWNERS, runbooks, SLI/SLO catalogue, Australian compliance doc, engineering journal. Plus five targeted engineering-honesty fixes: DiCE timeout alignment, Celery prefetch tuning, state-machine bypass audit, api_budget thread-safety, Celery integration test assertions."

**Follow-ups to expect:**
- *Why do this publicly?* → The PR train is itself a signal — each fix cites a specific review finding, comes with a test, and lands independently. It's how I want to work.
- *Is it 9.5 yet?* → Close. Still on the list: paging on SLO breach, multi-region failover, real historical data, formal compliance sign-off.

---

## Card 11 — What I'd do differently

**Say it:** "Three things. First, start with the compliance doc, not the model — knowing the regulatory frame earlier would have shaped data generation and the AuditLog schema. Second, write ADRs from day one — without them, 'why is it this way' lives only in commit messages that drift. Third, draw the probabilistic/deterministic boundary earlier — the WAT pattern clicked six months in, and before that guardrails were mixed into email generators and bias detection into orchestrators. All three are process lessons. The technical work is fine; the process would have saved months."

**Follow-ups to expect:**
- *What would you keep?* → The framing instinct — treating this as a regulatory system that happens to use ML. That held up.
- *Biggest time sink?* → Reverse-engineering compliance into a code-base shaped for speed. Would not repeat.

---

## Pre-screen cheat sheet

**One-line pitches:**
- *Project in one sentence:* A loan approval system where the interesting work is the Australian regulatory layer, not the ML.
- *What's technically novel:* Deterministic guardrails gating every probabilistic output.
- *What you learned:* Regulated writing is a correctness property, not a style choice. Monotonic constraints aren't just lift preservation — they're a regulatory defence.
- *What you'd ship first in a real lender:* The AuditLog schema and the retention command. The rest can come later; those are the compliance floor.

**Numbers worth remembering:**
- Test AUC 0.87–0.88 Optuna-tuned, 0.84–0.85 default hyperparameters (synthetic), ~0.82 real-world estimate (TSTR).
- 71 input fields, 21 monotonic constraints, 31 engineered interactions.
- 15 deterministic email guardrails. Three regeneration attempts then human review.
- 70 SHAP-mapped adverse-action reason codes.
- <$5/day Claude API cap.
- 30s watchdog poll, 5-minute stuck threshold.
- 60% backend test coverage floor, ~1000 tests across 66 files.

**Things you shouldn't oversell:**
- No production users. No licensed compliance sign-off. Synthetic data only.
- No paging. No multi-region. No Vault — secrets are in `.env`.
- Model card is honest, not audited.

*Last updated: 2026-04-17.*
