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

**Why two tiers?** The junior analyst (Sonnet) is fast and catches obvious violations. The senior reviewer (Opus) is slower and more expensive, but it catches subtle framing, coded language, and context-dependent bias that a less experienced model misses. The senior only runs on moderate scores (41-60), not on every email.

Note: the 60/80 bias thresholds came from testing against real bank denial letters. Marketing thresholds are tighter because ASIC scrutinises outbound marketing to declined customers more heavily.

## Required inputs

- Generated email text (from email generation or marketing agent pipeline)
- Original loan application context (decision, applicant details)
- Claude API key (from `.env` as `ANTHROPIC_API_KEY`)

## Tools

| Tool | Location | Purpose |
|------|----------|---------|
| Decision email bias detector | `backend/apps/agents/services/bias_detector.py:BiasDetector` | Agent 1: first-pass bias scoring on decision emails |
| Decision email senior reviewer | `backend/apps/agents/services/bias_detector.py:AIEmailReviewer` | Agent 2: senior review of flagged decision emails (Opus) |
| Marketing email bias detector | `backend/apps/agents/services/bias_detector.py:MarketingBiasDetector` | Agent 3: first-pass bias scoring on marketing emails |
| Marketing email senior reviewer | `backend/apps/agents/services/bias_detector.py:MarketingEmailReviewer` | Agent 4: senior review of flagged marketing emails (Opus) |

## Decision email pipeline

### Steps

1. **Agent 1 scores the email.** BiasDetector checks the email text against Australian anti-discrimination legislation and banking codes:
   - Sex Discrimination Act 1984 (s 22)
   - Racial Discrimination Act 1975 (s 15)
   - Disability Discrimination Act 1992 (s 24)
   - Age Discrimination Act 2004 (s 26)
   - NCCP Act 2009 (s 131, s 133, s 136: responsible lending)
   - Banking Code of Practice 2025 (para 81: must state the general reason for a decline)

2. **Route by score:**

   | Score range | Action |
   |-------------|--------|
   | 0-40 | **Pass**: the email is cleared for sending |
   | 41-60 | **Agent 2 review**: the senior reviewer (Opus) gives a second opinion |
   | 61-100 | **Block**: escalate directly to a human reviewer |

3. **Agent 2 review (if 41-60).** AIEmailReviewer receives Agent 1's findings plus the email, and uses Opus to:
   - Challenge Agent 1's flags: were they false positives on standard lending language?
   - Look for what Agent 1 missed: subtle framing, coded language, context-dependent bias
   - Make a final approve/reject decision

4. **If Agent 2 rejects,** escalate to a human reviewer through `HumanReviewView`.

### Fail-closed behaviour
- If Agent 1 can't parse Claude's response → default to score 100 (blocked)
- If Agent 2 can't parse Claude's response → default to rejected (human escalation)
- If the API call fails entirely → flag for human review

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

- **Claude returns non-JSON**: fail closed. The score defaults to 100 (blocked).
- **API failure during bias check**: decision emails → escalate to a human. Marketing emails → block silently.
- **Agent 2/4 disagrees with Agent 1/3**: the senior reviewer's decision is final. If they approve, the email ships. If they reject, it escalates or blocks.
- **Both agents score 0**: the email is compliant and needs no senior review.

## Scoring rubric

### Decision emails (Agents 1 & 2)

- **0-15**: Fully compliant. Standard banking language, no protected characteristics referenced.
- **16-40**: Minor observations but compliant. Financial criteria (income, credit score, employment) are never bias.
- **41-60**: Potential bias warranting senior review. Language that could disadvantage a protected group.
- **61-100**: Clear bias or compliance violation. The email should not be sent.

### Marketing emails (Agents 3 & 4): tighter thresholds

Marketing to declined customers carries higher reputational risk, so the thresholds are lower:

- **0-15**: Professional retention email. Respectful tone, appropriate products, no pressure.
- **16-30**: Minor observations but compliant.
- **31-50**: Potential issue warranting senior review (Agent 4, Opus).
- **51-100**: Clear violation. The marketing email is blocked.
