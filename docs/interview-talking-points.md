# Interview talking points: Loan Approval AI System

> Short cards for a 45-minute technical screen. Each card covers one architectural choice, worded so I can say it out loud in under a minute, plus the follow-up questions an interviewer is likely to ask. The long version is in `docs/engineering-journal.md`.

---

## Card 1. Framing: why the compliance layer is the product

**Say it:** "It's a three-level AI lending system: ML scoring, LLM emails, and an agent pipeline. What's interesting about building that for Australian lending isn't the AI. It's whether the system holds up against NCCP responsible lending, APRA serviceability, the Privacy Act APPs and the Banking Code of Practice. If the compliance layer is thin, nothing else matters, so I built the project around it."

**Follow-ups to expect:**
- *Which obligation was hardest to implement?* → APP 11, meaning field-level encryption plus retention. That's Fernet at rest, a rotation command, and an enforce_retention management command that hard-deletes at the policy horizon.
- *Where is compliance actually wired in?* → `docs/compliance/australia.md` maps each obligation to a code path. The file is verified: every path it cites exists.
- *What's missing for production?* → No licensed professional has signed off. I call that out in the README and in the journal.

---

## Card 2. WAT architecture

**Say it:** "Workflows, Agents, Tools. Workflows are markdown SOPs that describe the procedure. Agents are the probabilistic parts, like Claude deciding how to word something or SHAP deciding which features explain a denial. Tools are deterministic Python services. Every probabilistic output goes through a deterministic gate before a customer sees it."

**Follow-ups to expect:**
- *Why not put all of this in agents?* → Because probabilistic gates aren't auditable. When a regulator asks "why did you deny this applicant", you need a deterministic path to the answer.
- *Where does the line sit?* → It's in ADR 007. Email text is probabilistic, but the guardrails are deterministic. SHAP feature importance is probabilistic, but the mapping to reason codes is deterministic.

---

## Card 3. Data: the rewrite that made metrics honest

**Say it:** "The first data generator produced clean synthetic records with label leakage, and XGBoost hit 0.99 AUC. That's fraudulent. In v1.6.0 I rewrote the generator: Gaussian copula correlations, six borrower sub-populations, statistics anchored to ATO, ABS, APRA, RBA and Equifax, latent variables the model can't see, underwriter disagreement noise, and a 1000-line rules-based underwriting engine that produces the labels. AUC settled at 0.87 to 0.88 with Optuna tuning and 0.84 to 0.85 on defaults. That's honest."

**Follow-ups to expect:**
- *Why copula instead of just sampling marginals?* → Because cross-variable dependence matters. Income and credit score are correlated in the real world, and sampling them independently makes the learning task artificial.
- *How do you know 0.87 is realistic?* → The TSTR validator estimates real-world AUC at around 0.82. Walk-forward temporal CV AUC is reported next to the random-CV AUC, so you can see the drift gap. That's in ADR 001.

---

## Card 4. XGBoost with monotonic constraints

**Say it:** "I went with XGBoost over a logistic scorecard for the lift, but with 76 monotonic constraints: higher income always reduces risk, lower DTI always reduces risk, and so on. The monotonicity is what makes the model defensible to a regulator. I can point at the constraints and show that the model can't produce a perverse decision where a better applicant scores worse."

**Follow-ups to expect:**
- *How much lift?* → It's measured, not assumed. Every training run fits a logistic baseline on four core features and records `baseline_auc` plus `xgb_lift_over_baseline` in the training metadata. See ADR 002.
- *What else?* → IV feature selection, isotonic calibration, conformal prediction intervals for high-stakes cases, SHAP values mapped to 70 adverse-action reason codes, the APRA +3% stress buffer, and reject inference by parcelling.

---

## Card 5. Emails: template-first, Claude narrowly scoped

**Say it:** "Claude doesn't write denial letters from scratch. That would be expensive, slow, inconsistent and regulatorially dangerous. Every email starts from an audited template, and Claude is only called to personalise the reason-code section. Then 18 deterministic guardrails run before it's sent (19 for marketing emails). They check prohibited language, hallucinated dollar amounts, overly formal phrasing, apology language, word count, the required AFCA reference, and so on."

**Follow-ups to expect:**
- *Why is apology language banned?* → Australian banking guidance reads it as an admission of wrongdoing. There's an explicit guardrail for it, a test, and a persistent note in the project so it can't come back.
- *Cost?* → Under $5/day on the Anthropic API, with a hard cap and a deterministic fallback if it hits the cap. ADR 006.
- *Guardrail tests?* → The guardrails are pure functions, so the test suite runs in milliseconds.

---

## Card 6. Bias: three layers

**Say it:** "A regex pre-screen scores each generated email from 0 to 100 on bias-sensitive patterns. Anything under 60 passes. The 60 to 80 band goes to Claude with a confidence gate: if Claude says 'clean, confidence ≥ 0.70', it passes, and otherwise it goes to human review. Anything over 80, or any low-confidence answer from Claude, always goes to human review."

**Follow-ups to expect:**
- *Why not just Claude?* → It's slower, more expensive and not deterministic. The regex catches the obvious 95% for free.
- *Why not just regex?* → Regex misses context. "Applicants in this area" might be fine, or it might be a suburb-based proxy for protected attributes.
- *Design history:* → v1 was a 989-LOC god class that mixed detection, scoring, escalation, audit and notification. PR #13 split it into a `bias/` package of single-responsibility modules. What triggered that was a code review pointing out that each of those concerns changes at a different cadence.

---

## Card 7. Celery: one orchestrator task per pipeline

**Say it:** "The agent pipeline is one Celery task that moves an AgentRun record through its states, instead of four micro-tasks chained through groups. One task means one log trace, one error path and one retry unit. Debugging a chained pipeline with four handoffs is where engineer-hours die."

**Follow-ups to expect:**
- *What about resilience?* → There are separate queues per workload (ml, email, agents). `task_acks_late=True` means killed workers don't drop work, and there's `task_reject_on_worker_lost=True` as well. The ML queue has `prefetch_multiplier=1` because CPU-bound work can't share a worker. And `worker_max_tasks_per_child=1000` is there because XGBoost and OpenMP leak native state.
- *What if the task itself dies?* → A watchdog service polls every 30s for applications stuck for more than 5 min and re-queues them.

---

## Card 8. Security: layered and learned, not checklist-driven

**Say it:** "JWT in HttpOnly cookies, not localStorage. Argon2 rather than bcrypt, because it handles GPU attacks better. 60-minute access tokens and 7-day refresh tokens, with rotation and a blacklist. Fernet field-level encryption for PII, with a key rotation command. Rate limiting per role. Trivy, Bandit, gitleaks and OWASP ZAP on every CI run. Each of those came from a specific review finding, not a checklist."

**Follow-ups to expect:**
- *Prompt injection defence?* → Yes. User text going into the LLM prompt is sanitised, and the system prompt is pinned.
- *Supply chain?* → The Trivy images are pinned to commit SHAs. That went in after the April 2026 supply-chain advisory.
- *ADR?* → ADR 008 covers the layered threat model.

---

## Card 9. Mistakes and what they cost

**Say it (pick one):**

- **The denial emails tried to be empathetic.** The apology language set off the regulatory red flag. The fix was a hard-coded guardrail and a persistent project note. *Lesson:* in regulated writing, tone is a correctness property.
- **The dev frontend container kept exiting with code 243.** It crash-looped for months and I kept restarting it. The root cause was that Node's default heap was larger than the cgroup memory, so the OS killed it with signal 15 and Node reported exit 243. The fix is three lines of docker-compose (`NODE_OPTIONS=--max-old-space-size=768`, `mem_limit: 1g`, `healthcheck.start_period: 90s`) plus a runbook. *Lesson:* stop treating symptoms. Find the root cause, even when the workaround is cheap.
- **Flaky Hypothesis tests were marked `@skip`.** That tells CI the code works when it doesn't. PR #12 pinned the seeds, simplified the strategies and removed the skips. *Lesson:* flaky tests are lies.
- **A 989-LOC `bias_detector.py`.** Everything worked, but none of it was maintainable. Different concerns changed on different clocks, so every change was a merge conflict. *Lesson:* when a file is doing three things that move on three clocks, the file is wrong.
- **A timeout mismatch in CounterfactualEngine.** The caller passed `timeout_seconds=10`, but the default was 15, so the internal timeout sometimes won. The caller saw "no fallback" while the logs showed a timeout. The April 2026 fix aligned both to 20s and cut `total_CFs=5→3`. *Lesson:* when two layers have the same parameter with different defaults, there's a bug waiting to fire.
- **I assumed the model was the product.** I spent the first few months optimising AUC. Reframing the project around regulatory defensibility, guardrail breadth and audit trails happened too late. *Lesson:* compliance isn't a wrapper. It shapes the data model and the schema, so start there.

---

## Card 10. Rating journey: the polish pass

**Say it:** "In April 2026 I self-audited and landed at 8.9/10. I wrote out what was missing and turned it into a sequence of small PRs: an ADR scaffold, a README quickstart, pre-commit, Dependabot, CODEOWNERS, runbooks, an SLI/SLO catalogue, the Australian compliance doc and the engineering journal. On top of that there were five targeted engineering-honesty fixes: DiCE timeout alignment, Celery prefetch tuning, a state-machine bypass audit, api_budget thread-safety, and Celery integration test assertions."

**Follow-ups to expect:**
- *Why do this publicly?* → The PR train says something by itself. Each fix cites a specific review finding, comes with a test and lands on its own. That's how I want to work.
- *Is it 9.5 yet?* → Close. Still on the list: paging on SLO breach, multi-region failover, real historical data and formal compliance sign-off.

---

## Card 11. What I'd do differently

**Say it:** "Three things. First, I'd start with the compliance doc, not the model. Knowing the regulatory frame earlier would have shaped data generation and the AuditLog schema. Second, I'd write ADRs from day one. Without them, 'why is it this way' lives only in commit messages, and those drift. Third, I'd draw the probabilistic/deterministic boundary earlier. The WAT pattern clicked six months in, and before that, guardrails were mixed into email generators and bias detection into orchestrators. All three are process lessons. The technical work is fine; the process is what would have saved months."

**Follow-ups to expect:**
- *What would you keep?* → The framing instinct: treating this as a regulatory system that happens to use ML. That held up.
- *Biggest time sink?* → Reverse-engineering compliance into a codebase that was shaped for speed. I wouldn't do that again.

---

## Card 12. Free AI without the data-safety mistake

**Say it:** "I made the email LLM backend pluggable so it can run for free, but the part that needed care was *which* free option. The lazy move is to send applicant data to whatever free AI is cheapest, and most free AI tiers train on your prompts, some with human review. So I default to Claude, and the free option is Groq specifically, because its free tier doesn't train on prompts. Free Gemini and Mistral do, so they're deliberately excluded. On top of that, the demo runs on synthetic data and the prompt only ever sends anonymised feature summaries, never raw PII."

**Follow-ups to expect:**
- *How big was the change?* → It's a thin adapter that duck-types the Anthropic client with the same call surface, so the $5/day budget guard, the 18 guardrails, the retry loop and the deterministic template fallback are all untouched. Zero new dependencies, since it's built on httpx, which was already there. ADR 010.
- *Did you put the free model on the bias check too?* → No, and that was deliberate. The free model writes prose. The safety-critical bias gate stays on the deterministic rules, so it's auditable and doesn't depend on any model. Putting a weaker model on the compliance gate to save nothing is a bad trade.
- *What about real production?* → This free tier isn't the production endpoint. You'd switch the same toggle to a no-train paid tier or a self-hosted model. That's a config change, not a rewrite, and it's the point of making it pluggable.

---

## Pre-screen cheat sheet

**One-line pitches:**
- *Project in one sentence:* A loan approval system where the interesting work is the Australian regulatory layer, not the ML.
- *What's technically novel:* Deterministic guardrails that every probabilistic output has to pass.
- *What you learned:* Regulated writing is a correctness property, not a style choice. And monotonic constraints do more than preserve lift. They're also a regulatory defence.
- *What you'd ship first in a real lender:* The AuditLog schema and the retention command. Those are the compliance floor, and the rest can come later.

**Numbers worth remembering:**
- Test AUC 0.87-0.88 Optuna-tuned and 0.84-0.85 with default hyperparameters (synthetic), with a ~0.82 real-world estimate (TSTR).
- 71 input fields, 76 monotonic constraints, 31 engineered interactions.
- 18 deterministic email guardrails on a decision email (19 on a marketing email). Up to three regeneration attempts, and after that the email is withheld and flagged to operations. The human-review queue is only for bias escalations.
- 70 SHAP-mapped adverse-action reason codes.
- <$5/day LLM API cap (Claude by default, with an optional free Groq backend, selectable via `EMAIL_LLM_BACKEND`, chosen because its free tier doesn't train on prompts).
- 30s watchdog poll, 5-minute stuck threshold.
- 63% backend test coverage floor, 1,900+ backend tests across 180+ files, plus 370+ frontend tests.

**Things you shouldn't oversell:**
- No production users. No licensed compliance sign-off. Synthetic data only.
- No paging. No multi-region. No Vault: secrets are in `.env`.
- Model card is honest, not audited.

*Last updated: 2026-06-10.*
