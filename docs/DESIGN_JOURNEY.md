# Design journey

*A first-person account of how the Loan Approval AI System evolved, by Neville Zeng.*

This covers the decisions I made on the project, the alternatives I weighed,
and the things I would do differently if I were starting again. Each section
follows the same template: what I
built, why I chose this approach, what I considered and rejected, and what I'd
do differently. If you want the short version of a particular decision, skip to
the matching ADR under `docs/adr/`.

---

## 1. Level 1: ML foundation

**What I built.** A supervised loan-approval classifier with two algorithms:
Random Forest as the conservative baseline, and XGBoost with monotonic
constraints as the production model. Training is a straight 80/20 split on a
synthetic dataset of 71 features (counted at `predictor.py:375-459`). The data
comes from a Gaussian copula calibrated against published ATO, ABS, APRA,
Equifax and CoreLogic statistics. Hyperparameters are tuned with Optuna. The
active `ModelVersion` reports AUC 0.8816 on its full test set
(`backend/docs/MODEL_CARD.md`), and the reproducible benchmark on a 2,000-record
subset comes in at 0.8499 with default hyperparameters (`docs/experiments/benchmark.md`).
Every training run also reports a baseline-lift comparison against vanilla
Logistic Regression, so nobody can accuse me of polishing the headline metric
without a sanity check.

**Why I chose this approach.** I wanted something defensible in a lending
context, not the flashiest model. Tree ensembles handle the mix of categorical
and monotonic numeric features (income, LVR, DTI) without heavy preprocessing,
and XGBoost's monotonic constraints let me guarantee that "more income never
decreases approval probability". Regulators care about that property. A linear
model gives it to you for free, but you lose it as soon as you add interactions.
Feature engineering lives in one shared module that both training and inference
import, so the train/serve skew bugs that plague ML projects can't happen here.
ADR-002 (XGBoost + monotonic constraints) and ADR-001 (synthetic data via
copula) have the full reasoning.

**What I considered and rejected.** A deep tabular network (TabNet, FT-Transformer)
would have been fun, but interpretability isn't optional here. I need SHAP
values that make sense to a credit officer, not an attention heatmap.
CatBoost was a near-tie with XGBoost. I picked XGBoost because monotonic
constraints and SHAP are both first-class in its API, and the community
material for Australian lending use cases leans towards XGBoost. Bayesian
hyperparameter search with `scikit-optimize` was slower than Optuna for the
same budget.

**What I'd do differently.** I'd validate on real data sooner. Everything I
know about model quality comes from synthetic benchmarks and out-of-time splits
within the same synthetic distribution. That's useful, but it isn't the same as
seeing how the model behaves on a bank's actual applicant mix. I'd also add a
temporal holdout from day one instead of bolting it on after ADR-004. And I
was slow to write a model card. I should have committed the skeleton in week
one and filled it in as decisions landed, instead of catching up at the end.

---

## 2. Level 2: LLM email automation

**What I built.** A template-first email pipeline. Every approval, denial or
conditional-approval email is first attempted with deterministic templates,
which pass all 15 compliance guardrails by construction (counted at `backend/apps/email_engine/services/guardrails.py`). The Claude API is the
fallback for cases where personalisation really matters, such as a marginal
denial or a request with unusual hardship context. Every Claude-generated email
then goes through the same guardrail service, which checks amount accuracy,
prohibited language, required disclosures (NCCP obligations, credit reporting
rights, the AFCA path) and tone. A hard $5/day budget cap on the Claude path
means the system can't run away on cost. A circuit breaker switches back to
templates after three consecutive API failures.

**Why I chose this approach.** Deterministic templates are cheaper, auditable,
and can't hallucinate. They also pass compliance by construction, because they
were written against the same guardrail checklist. The LLM path is only there
for the long tail of cases where a template would feel robotic. ADR-006
(template-first email with cost cap) covers the architecture in detail. This
is the reverse of the usual "LLM everywhere, fall back to templates on
failure" pattern. I think LLM-first is the wrong default for regulated
correspondence.

**What I considered and rejected.** LLM-only with aggressive guardrails:
rejected, because a single rare hallucination in a denial letter is a
regulatory incident, and a traffic spike would blow the $5 cap. Pure templates
with no Claude path: tempting for simplicity, but denial emails with zero
personalisation read as form letters and hurt customers who deserve a clear
reason. A hybrid where Claude edits templates instead of writing fresh:
interesting, but the guardrails get harder to reason about, because the output
depends on both the template and the model.

**What I'd do differently.** I'd ship the guardrail service as a standalone
package from day one, not a module inside `email_engine`. Right now the
template tests and the LLM tests share the same checks, but exercising them
against a new channel (SMS, in-app notification) means rewriting half of it.
I'd also measure the template-vs-LLM reply rate earlier. I still don't know
empirically whether the extra Claude cost buys measurably better customer
outcomes.

---

## 3. Level 3: agentic pipeline

**What I built.** A single Celery task, `OrchestratorAgent.run`, that walks a
fixed sequence: fraud check → ML prediction → counterfactual generation →
email composition → next-best-offer (NBO) injection. Every step writes to one
`AgentRun` record, so auditors and I can see exactly where a pipeline failed,
how long each step took, and what the agent decided. A bias-detection agent
scores each decision against protected attributes and escalates to a human
review queue when the score crosses a threshold. NBO kicks in on denials, and
it reaches the customer through two separate emails. The denial decision email
carries one deterministic alternative-offer teaser: the best-scoring product
plus its headline figure, computed by the recommendation engine and validated
by the same hallucinated-number guardrail the rest of the letter uses. That way
the customer sees one concrete next step straight away. The full personalised
offer set, with every eligible product and LLM-written reasoning, goes out as a
separate marketing follow-up email that runs through its own bias-detection and
senior-review gate. Splitting decision and marketing like this keeps the
regulated decision letter concise and compliant, and lets the marketing message
be richer and more persuasive.

**Why I chose this approach.** One task with step-level logging gives me
auditability without distributed-transaction overhead. Microservices would add
network hops and deployment coordination with no scaling benefit, because the
bottleneck is Celery worker CPU, not service-to-service throughput. ADR-007
(WAT architecture) covers this. Human review is deliberately limited to bias
flags. Conditional approvals and low-confidence predictions don't go there.
Sending everything marginal to a human queue defeats the point of automation
and trains reviewers to rubber-stamp.

**What I considered and rejected.** A DAG framework (Airflow, Prefect): far
too heavy for a five-step pipeline. LangGraph-style agent graphs with dynamic
routing: rejected, because the pipeline is linear and the "agentic" branching
would be illusory. Making NBO *only* a separate marketing email: rejected,
because a denied customer should see at least one concrete alternative in the
decision letter itself instead of waiting for a follow-up. Putting the *full*
offer set inside the decision letter: also rejected, because it would bloat a
regulated communication and mix marketing into a compliance document. The final
design renders one deterministic teaser into the denial prompt from engine
output (data, not a Jinja template). The orchestrator still owns NBO as an
explicit step that produces the richer marketing email, so the
counterfactual/NBO dependency stays visible in the pipeline instead of hidden
in a template.

**What I'd do differently.** I'd deploy earlier, even if half the steps were
stubs. Running the pipeline on real traffic (internal, synthetic customers)
would have surfaced the async timing issues with counterfactual generation
much sooner. I'd also make the orchestrator resumable from any step. Right now
a failure at step 4 restarts from step 1, which wastes the ML prediction call.

---

## 4. Track C: counterfactual explanations

**What I built.** A DiCE-powered counterfactual explanation panel on
`/apply/status/[id]`. For denied applicants the panel shows three suggestion
cards generated by Microsoft Research's DiCE library (genetic method). Each
card varies only the loan-product parameters an applicant can actually change:
`loan_amount`, `loan_term_months`, and `has_cosigner`. The framing is
lender-faithful: "change the loan you're asking for," not "change yourself."
If DiCE times out or returns nothing, a binary-search fallback guarantees the
panel is never empty. The static educational guidance (credit-score bands, LVR
tips) comes from published Pepper Money, Unloan and Equifax AU guides.

**Why I chose this approach.** The original binary-search implementation in
`predictor.py` varied one feature at a time and usually produced one huge
jump, like "increase your income by $40,000". That's tone-deaf, and it isn't how
any Australian lender actually communicates. DiCE generates multi-feature
counterfactuals that stay realistic. The part that matters most is that I
constrained the features-to-vary, so the suggestions talk about the loan
product rather than the applicant. ADR-009 (DiCE over binary search) documents
this decision in full.

**What I considered and rejected.** Keeping binary search only: simpler, but
the robotic single-feature output is exactly what makes algorithmic denial
letters feel dehumanising. DiCE's random method: faster than genetic, but it
gives less stable, less realistic CFs. DiCE's KD-tree method: it requires
TensorFlow, which is a 400MB+ dependency I refuse to ship for one feature.
A custom genetic search: fun, but reinventing well-tested library code is a
bad trade for a portfolio project.

**What I'd do differently.** I'd run the panel past real denied applicants
(or proxies, such as credit counsellors) before locking the copy. The current
lender-faithful framing feels right to me, but I don't have user research
behind it, only a reading of competitor patterns. I'd also cache CF results
per applicant so the orchestrator doesn't regenerate them on every status poll.

---

## 5. AU regulatory posture

**What I built.** Compliance scaffolding for Australian consumer lending. The
comparison rate is computed and displayed on every offer, every approval
email carries an ACL footer and links to the Credit Guide, and the
`/rights` page lays out the AFCA complaint path in plain English. The
serviceability engine applies APRA's 3% buffer on the assessment rate and, as
of February 2026, caps DTI at 6 in line with the new macroprudential
guidance. The ML engine honours ASIC RG 209's responsible-lending framing: no
approval is returned without a serviceability check. The data generator is
calibrated to ABS, APRA and RBA statistics, so benchmarks reflect the
Australian market rather than US defaults. There is no real PII anywhere in
the repo.

**Why I chose this approach.** The system is designed so it can be shown to an
Australian regulator without embarrassment. I chose plain-English
disclosures over statute-name citations because customers don't know what
"NCCP Act section 128" means. They know they want a fair outcome. The
comparison rate, the buffer and the DTI cap are the three most commonly
misconfigured items in Australian consumer lending tech, so those are the ones
I locked down first. The full market calibration story is in
`reports/au-lender-benchmark.md`.

**What I considered and rejected.** US-style APR-only disclosure: rejected,
because Australian customers expect a comparison rate, and it's the right
single number for total cost of credit here. Storing applicant data
indefinitely for model retraining: rejected on privacy grounds. The synthetic
generator means I never needed to.

**What I'd do differently.** I'd get an actual credit lawyer to do a one-hour
review earlier. My compliance posture is based on reading public regulatory
guidance and patterns from live neobank disclosures. That's a solid starting
point, but it isn't a substitute for a qualified opinion. I would also build
the audit log as structured events from day one instead of free-text log
lines, so the compliance surface can be queried rather than grepped.

---

*Neville Zeng, 2026-04-16*
