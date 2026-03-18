# Bias Detection Workflow

## Objective

Score generated emails (both loan decision and marketing) for potential bias using a two-tier AI compliance team, and route emails based on score thresholds for approval, senior review, or blocking.

## Agent Architecture

The bias detection pipeline uses four distinct AI agents, each with a specific role and persona:

| Agent | Class | Model | Role |
|-------|-------|-------|------|
| **Agent 1** — Compliance Analyst | `BiasDetector` | Sonnet | Junior analyst, 2 years in. Follows the checklist. Cites legislation by section. Scores and flags. |
| **Agent 2** — Head of Compliance | `AIEmailReviewer` | **Opus** | Senior reviewer, 18 years in. Interrogates Agent 1's findings. Catches what the junior missed. Tougher model, harder to fool. |
| **Agent 3** — Marketing Compliance Analyst | `MarketingBiasDetector` | Sonnet | Junior analyst reviewing marketing emails. Checks for patronising tone, pressure tactics, discriminatory product steering, false promises. |
| **Agent 4** — Marketing Head of Compliance | `MarketingEmailReviewer` | **Opus** | Senior reviewer for marketing emails. Knows ASIC watches marketing to declined customers closely. Protects the customer. |

**Why two tiers?** The junior analyst (Sonnet) is fast and catches obvious violations. The senior reviewer (Opus) is slower, more expensive, but catches subtle framing, coded language, and context-dependent bias that a less experienced model misses. The senior only activates on moderate scores (41-60) — not on every email.

## Required Inputs

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

## Decision Email Pipeline

### Steps

1. **Agent 1 scores the email** — BiasDetector analyzes the email text against Australian anti-discrimination legislation and banking codes:
   - Sex Discrimination Act 1984 (s 22)
   - Racial Discrimination Act 1975 (s 15)
   - Disability Discrimination Act 1992 (s 24)
   - Age Discrimination Act 2004 (s 26)
   - NCCP Act 2009 (s 131, s 133, s 136 — responsible lending)
   - Banking Code of Practice 2025 (para 81 — must state general reason for decline)

2. **Route based on score**:

   | Score Range | Action |
   |-------------|--------|
   | 0-40 | **Pass** — Email is cleared for sending |
   | 41-60 | **Agent 2 Review** — Senior reviewer (Opus) gets second opinion |
   | 61-100 | **Block** — Escalate directly to human reviewer |

3. **Agent 2 review (if 41-60)** — AIEmailReviewer receives Agent 1's findings plus the email. Uses Opus to:
   - Challenge Agent 1's flags: were they false positives on standard lending language?
   - Look for what Agent 1 missed: subtle framing, coded language, context-dependent bias
   - Make a final approve/reject decision

4. **If Agent 2 rejects** — Escalate to human reviewer via `HumanReviewView`

### Fail-closed behaviour
- If Agent 1 cannot parse Claude's response → default to score 100 (blocked)
- If Agent 2 cannot parse Claude's response → default to rejected (human escalation)
- If the API call fails entirely → flag for human review

## Marketing Email Pipeline

Marketing emails to declined customers carry specific compliance risks beyond standard bias:

### Marketing-Specific Risk Categories

| Risk | What It Checks |
|------|---------------|
| **Patronising tone** | Talking down to the customer, implying they made a bad decision |
| **Pressure tactics** | False urgency, "limited time" offers, pushing unsuitable products |
| **Discriminatory product steering** | Offering inferior products based on assumptions about demographics |
| **False promises** | Implying guaranteed approval for alternative products |
| **Standard bias** | Gender, race, age, religion, disability, marital status |

### Steps

1. **Agent 3 scores the marketing email** — MarketingBiasDetector analyzes the email against marketing-specific risks plus standard anti-discrimination law.

2. **Route based on score** (marketing uses tighter thresholds — declined customers are vulnerable):

   | Score Range | Action |
   |-------------|--------|
   | 0-30 | **Pass** — Marketing email is cleared for sending |
   | 31-50 | **Agent 4 Review** — Senior marketing reviewer (Opus) gets second opinion |
   | 51-100 | **Block** — Marketing email is not sent |

3. **Agent 4 review (if 31-50)** — MarketingEmailReviewer asks:
   - Would ASIC object to this email in a compliance audit?
   - Is the tone appropriate for someone who just got declined?
   - Are the offered products financially appropriate?
   - Would a Big 4 bank send this?

4. **If Agent 4 rejects** — Marketing email is blocked (not sent). The pipeline continues without it.

**Key difference from decision emails:** Marketing email bias failures block the email silently rather than escalating the entire pipeline to human review. The decision email has already been sent — the marketing follow-up is optional.

### Pipeline Ordering

Marketing emails are saved to the database AFTER the bias check completes, so the `passed_guardrails` field accurately reflects whether the email was cleared:

1. Generate marketing email (Claude)
2. Run deterministic guardrails (patronising language, false urgency, decline references, prohibited terms, tone)
3. Run marketing bias check (Agent 3 + optional Agent 4)
4. **If passed:** Save MarketingEmail with `passed_guardrails=True`, then send
5. **If blocked:** Save MarketingEmail with `passed_guardrails=False`, do not send

### Marketing-Specific Deterministic Guardrails

In addition to the standard prohibited language and tone checks, marketing emails are checked for:

| Guardrail | What It Catches |
|-----------|----------------|
| `patronising_language` | "we know this is hard", "don't worry", "cheer up", "this isn't the end", etc. |
| `false_urgency` | "limited time", "act now", "offer expires", "hurry", "last chance", etc. |
| `no_decline_language` | References to the decline (the marketing email is forward-looking) |
| `call_to_action` | Must include a clear next step (phone number, branch visit, reply) |

## Expected Outputs

- Bias score (0-100)
- Categories triggered (bias-specific or marketing-specific)
- Detailed analysis citing specific phrases and legislation
- Routing decision: pass / senior review / block
- If reviewed: senior reviewer's reasoning and final determination

## Edge Cases

- **Claude returns non-JSON**: Fail-closed. Score defaults to 100 (blocked).
- **API failure during bias check**: Decision emails → escalate to human. Marketing emails → block silently.
- **Agent 2/4 disagrees with Agent 1/3**: The senior reviewer's decision is final. If they approve, the email ships. If they reject, it escalates or blocks.
- **Both agents score 0**: Email is compliant. No senior review needed.

## Scoring Rubric

### Decision Emails (Agents 1 & 2)

- **0-15**: Fully compliant. Standard banking language. No protected characteristics referenced.
- **16-40**: Minor observations but compliant. Financial criteria (income, credit score, employment) are never bias.
- **41-60**: Potential bias warranting senior review. Language that could disadvantage a protected group.
- **61-100**: Clear bias or compliance violation. Email should not be sent.

### Marketing Emails (Agents 3 & 4) — Tighter Thresholds

Marketing to declined customers carries higher reputational risk. Thresholds are lower:

- **0-15**: Professional retention email. Respectful tone. Products appropriate. No pressure.
- **16-30**: Minor observations but compliant.
- **31-50**: Potential issue warranting senior review (Agent 4, Opus).
- **51-100**: Clear violation. Marketing email blocked.
