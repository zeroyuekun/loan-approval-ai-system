# Bias detection workflow

## Objective

Score generated emails (loan decision and marketing) for potential bias with a two-tier AI compliance team, then route each email by its score: approve it, send it to senior review, or block it.

## Agent architecture

The bias detection pipeline uses four AI agents, each with its own role and persona:

| Agent | Class | Model | Role |
|-------|-------|-------|------|
| **Agent 1** (Compliance Analyst) | `BiasDetector` | Sonnet | Junior analyst, 2 years in. Follows the checklist. Cites legislation by section. Scores and flags. |
| **Agent 2** (Head of Compliance) | `AIEmailReviewer` | **Opus** | Senior reviewer, 18 years in. Interrogates Agent 1's findings. Catches what the junior missed. Tougher model, harder to fool. |
| **Agent 3** (Marketing Compliance Analyst) | `MarketingBiasDetector` | Sonnet | Junior analyst reviewing marketing emails. Checks for patronising tone, pressure tactics, discriminatory product steering, false promises. |
| **Agent 4** (Marketing Head of Compliance) | `MarketingEmailReviewer` | **Opus** | Senior reviewer for marketing emails. Knows ASIC watches marketing to declined customers closely. Protects the customer. |

**Why two tiers?** The junior analyst (Sonnet) is fast and catches obvious violations. The senior reviewer (Opus) is slower and more expensive, but it catches subtle framing, coded language, and context-dependent bias that a less experienced model misses. For decision emails the senior reviewer only reads a rewrite of a moderate-band email (score 31-59), never every email.

In the code, "Agent 2" (`backend/apps/agents/services/bias_agent2.py`) is the moderate-band rewrite step: the email generator writes a new draft, and the senior reviewer is the second of its two checks.

Note: the decision-email thresholds are `BIAS_THRESHOLD_PASS` = 30 and `BIAS_THRESHOLD_REVIEW` = 60 (`backend/config/settings/base.py`). Marketing thresholds are tighter because ASIC scrutinises outbound marketing to declined customers more heavily.

## Required inputs

- Generated email text (from email generation or marketing agent pipeline)
- Original loan application context (decision, applicant details)
- Claude API key (from `.env` as `ANTHROPIC_API_KEY`)

## Tools

| Tool | Location | Purpose |
|------|----------|---------|
| Decision email bias detector | `backend/apps/agents/services/bias_detector.py:BiasDetector` | Agent 1: first-pass bias scoring on decision emails |
| Decision email senior reviewer | `backend/apps/agents/services/bias_detector.py:AIEmailReviewer` | Senior review of Agent 2 rewrites of moderate-band decision emails (Opus) |
| Marketing email bias detector | `backend/apps/agents/services/bias_detector.py:MarketingBiasDetector` | Agent 3: first-pass bias scoring on marketing emails |
| Marketing email senior reviewer | `backend/apps/agents/services/bias_detector.py:MarketingEmailReviewer` | Agent 4: senior review of flagged marketing emails (Opus) |
| Moderate-band rewrite (Agent 2) | `backend/apps/agents/services/bias_agent2.py:run_agent2` | Email pipeline step: rewrites a moderate-band flagged decision email with the bias findings as feedback, then requires a clean bias check and the senior reviewer's approval before the rewrite may be sent |

## Decision email pipeline

### Steps

1. **Agent 1 scores the email.** BiasDetector checks the email text against Australian anti-discrimination legislation and banking codes:
   - Sex Discrimination Act 1984 (s 22)
   - Racial Discrimination Act 1975 (s 15)
   - Disability Discrimination Act 1992 (s 24)
   - Age Discrimination Act 2004 (s 26)
   - NCCP Act 2009 (s 131, s 133, s 136: responsible lending)
   - Banking Code of Practice 2025 (para 81: must state the general reason for a decline)

2. **Route by score.** A score above `BIAS_THRESHOLD_PASS` (30) is flagged. A score at or above `BIAS_THRESHOLD_REVIEW` (60) is severe; the bound is inclusive.

   | Score range | Action |
   |-------------|--------|
   | 0-30 | **Pass**: the email is sent |
   | 31-59 | **Moderate**: the email is never sent as written; see the moderate-band route below |
   | 60-100 | **Severe**: the email is withheld and the application goes to the human-review queue (waterfall: `ESCALATED_SEVERE_BIAS`) |

3. **Moderate band.** Agent 2 tries a rewrite (new draft, then a fresh bias check, then the senior review). If it hands over, the template replaces the email and gets its own bias check. If the template is still flagged, the application goes to human review.

### Moderate-band route: rewrite before template, template before escalation

An email lands in the moderate band when the email pipeline (`EmailPipelineService.run`) finds it flagged but below `BIAS_THRESHOLD_REVIEW`. A flagged email is never sent as written, so the pipeline tries two replacements in order before it holds the application for human review:

1. **Try a rewrite (`run_agent2`, gated by `BIAS_AGENT2_ENABLED`, on by default).** The email generator is asked for a new draft of the same decision, with Agent 1's findings passed back as feedback (flagged categories plus the analysis text). The rewrite must then pass two independent checks before it may be sent:
   - A fresh `BiasDetector` run against the rewrite must come back clean (not flagged).
   - `AIEmailReviewer` must approve it with confidence at or above `BIAS_AGENT2_MIN_REVIEWER_CONFIDENCE` (0.70). This is a fixed setting in `backend/config/settings/base.py`, not an environment variable.

   If both checks pass, the rewrite is sent and the original flagged draft stays unsent; the waterfall records `EMAIL_REGENERATED_AGENT2` under the `bias_agent2_regeneration` step. Otherwise the step hands over to the template path: the rewrite failed either check, the generator degraded to the template (LLM unavailable or guardrails exhausted), the rewrite failed its guardrails, or Agent 2 raised an error. Agent 2 can only replace the flagged email with something that passed more checks, never with something weaker.

   Agent 2 does not run, and the template path takes over, when:
   - the original email already was the deterministic template (regenerating it gives the same text);
   - fewer than `BIAS_AGENT2_MIN_SECONDS_LEFT` (240) seconds remain before the pipeline task's soft time limit, since a rewrite plus two checks can take minutes on a slow local LLM;
   - the API budget gate is closed (daily budget spent or circuit breaker open).

   A soft time limit during Agent 2 stops the pipeline task; it does not fall through to the template path.

   The rewrite is saved only after the bias detector has scored it, in one transaction with its bias report. That report has `ai_review_approved=False` until the senior reviewer approves the rewrite, and then records the verdict and the reviewer's reasoning. The staff "send latest" endpoint and the `generate_email_task` redelivery refuse any unsent draft whose report is flagged or not approved, so a rejected rewrite, or one whose review never finished (a time limit or crash, after which recovery returns the application to pending), is never sent.

   The `bias_agent2_outcomes_total{outcome}` counter records each run: `sent`, `handed_over_<reason>` (`low_time`, `budget_closed`, `no_rewrite`, `guardrails`, `bias_flagged`, `reviewer_rejected`, `error`) or `skipped`.

2. **Fall back to the template.** When the rewrite was skipped, disabled, or handed over, the pipeline generates the deterministic template, bias-checks it, and sends it only if that check comes back clean (waterfall: `EMAIL_REPLACED`).

3. **Escalate.** If the template replacement is also flagged, or its bias check fails, the application is held and routed to the human-review queue (waterfall: `ESCALATED_MODERATE_BIAS`).

The human-review resume path (re-running a previously escalated application after a reviewer clears it) does not go through the rewrite step. It only ever replaces a flagged email with the template, since a human has already reviewed the run.

### Fail-closed behaviour
- If Agent 1's LLM interpretation fails or can't be parsed, the deterministic pre-screen score stands, so a moderate finding stays flagged.
- If the senior reviewer fails or its response can't be parsed, the rewrite counts as not approved: it is not sent, and the template path takes over.
- If the bias check can't run at all (budget gate, circuit breaker, crash), `BIAS_FAILURE_MODE` applies. The default, `block`, withholds the email, returns the application to pending for a retry and marks the run failed. It does not go to human review, because an outage is not a bias finding.

## Marketing email pipeline

Marketing emails to declined customers carry compliance risks that go beyond standard bias:

### Marketing-specific risk categories

| Risk | What it checks |
|------|---------------|
| **Patronising tone** | Talking down to the customer, implying they made a bad decision |
| **Pressure tactics** | False urgency, "limited time" offers, pushing unsuitable products |
| **Discriminatory product steering** | Offering inferior products based on assumptions about demographics |
| **False promises** | Implying guaranteed approval for alternative products |
| **Standard bias** | Gender, race, age, religion, disability, marital status |

### Steps

1. **Agent 3 scores the marketing email.** MarketingBiasDetector checks the email against the marketing-specific risks plus standard anti-discrimination law.

2. **Route by score.** Marketing uses tighter thresholds, because declined customers are vulnerable:

   | Score range | Action |
   |-------------|--------|
   | 0-30 | **Pass**: the marketing email is cleared for sending |
   | 31-50 | **Agent 4 review**: the senior marketing reviewer (Opus) gives a second opinion |
   | 51-100 | **Block**: the marketing email is not sent |

3. **Agent 4 review (if 31-50).** MarketingEmailReviewer asks:
   - Would ASIC object to this email in a compliance audit?
   - Is the tone appropriate for someone who just got declined?
   - Are the offered products financially appropriate?
   - Would a Big 4 bank send this?

4. **If Agent 4 rejects,** block the marketing email (don't send it). The pipeline continues without it.

Unlike a decision email, a marketing email that fails the bias check is blocked silently instead of escalating the whole pipeline to human review. The decision email has already been sent, and the marketing follow-up is optional.

### Pipeline ordering

Save marketing emails to the database only AFTER the bias check completes, so the `passed_guardrails` field accurately reflects whether the email was cleared:

1. Generate marketing email (Claude)
2. Run deterministic guardrails (patronising language, false urgency, decline references, prohibited terms, tone)
3. Run marketing bias check (Agent 3 + optional Agent 4)
4. **If passed:** Save MarketingEmail with `passed_guardrails=True`, then send
5. **If blocked:** Save MarketingEmail with `passed_guardrails=False`, do not send

### Marketing-specific deterministic guardrails

On top of the standard prohibited language and tone checks, marketing emails are checked for:

| Guardrail | What it catches |
|-----------|----------------|
| `patronising_language` | "we know this is hard", "don't worry", "cheer up", "this isn't the end", etc. |
| `false_urgency` | "limited time", "act now", "offer expires", "hurry", "last chance", etc. |
| `no_decline_language` | References to the decline (the marketing email is forward-looking) |
| `call_to_action` | Must include a clear next step (phone number, branch visit, reply) |

## Expected outputs

- Bias score (0-100)
- Categories triggered (bias-specific or marketing-specific)
- Detailed analysis citing specific phrases and legislation
- Routing decision: pass / senior review / block
- If reviewed: senior reviewer's reasoning and final determination

## Gotchas

- **Claude returns non-JSON**: the junior analyst keeps the deterministic pre-screen score; a senior reviewer's unparseable answer counts as not approved.
- **API failure during bias check**: decision emails follow `BIAS_FAILURE_MODE` (default `block`: withhold the email and retry later). Marketing emails → block silently.
- **The senior reviewer rejects**: for a decision email, the Agent 2 rewrite is not sent and the template path takes over. For a marketing email (Agent 4), the email is blocked.
- **Both agents score 0**: the email is compliant and needs no senior review.

## Scoring rubric

### Decision emails (Agents 1 & 2)

- **0-15**: Fully compliant. Standard banking language, no protected characteristics referenced.
- **16-30**: Minor observations but compliant. Financial criteria (income, credit score, employment) are never bias.
- **31-59**: Potential bias (moderate band). Language that could disadvantage a protected group. The email is not sent as written; Agent 2 or the template replaces it.
- **60-100**: Clear bias or compliance violation. The email is withheld and the application goes to human review.

### Marketing emails (Agents 3 & 4): tighter thresholds

Marketing to declined customers carries higher reputational risk, so the thresholds are lower:

- **0-15**: Professional retention email. Respectful tone, appropriate products, no pressure.
- **16-30**: Minor observations but compliant.
- **31-50**: Potential issue warranting senior review (Agent 4, Opus).
- **51-100**: Clear violation. The marketing email is blocked.
