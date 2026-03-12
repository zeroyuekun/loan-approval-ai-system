# Bias Detection Workflow

## Objective

Score generated loan decision emails for potential bias on a 0-100 scale using Claude as an evaluator, and route emails based on score thresholds for approval, review, or rejection and regeneration.

## Required Inputs

- Generated email text (from email generation pipeline)
- Original loan application context (decision, applicant details)
- Claude API key (from `.env` as `ANTHROPIC_API_KEY`)

## Tools

| Tool | Location | Purpose |
|------|----------|---------|
| Bias detector service | `backend/apps/agents/services/bias_detector.py` | Sends email to Claude for bias analysis |

## Steps

1. **Prepare analysis prompt** — Construct a prompt asking Claude to analyze the email for bias:
   - System prompt: "You are a fair lending compliance analyst. Analyze the following email for any signs of bias, discriminatory language, or differential treatment."
   - Include the email text and the loan decision context
   - Request structured output: overall score (0-100), category scores, flagged phrases, explanation

2. **Send to Claude for analysis** — Call Claude API with:
   - Model: `claude-sonnet-4-20250514`
   - `max_tokens`: 1024
   - `temperature`: 0 (deterministic analysis)
   - Request JSON output format

3. **Parse response** — Extract from Claude's response:
   - `overall_score`: Integer 0-100
   - `categories`: Dict of category scores (tone_bias, language_bias, information_bias, protected_class_references)
   - `flagged_phrases`: List of specific phrases that triggered concerns
   - `explanation`: Free-text reasoning for the score

4. **Apply thresholds and route**:

   | Score Range | Action | Description |
   |-------------|--------|-------------|
   | 0-30 | **Pass** | Email is cleared for sending. No further action needed. |
   | 31-60 | **Review** | Email is flagged for human review. Loan officer must approve before sending. |
   | 61-100 | **Reject + Regenerate** | Email is rejected. Trigger email regeneration with bias feedback appended to prompt. |

5. **Handle escalation** (score > 60):
   - Log the bias report with full details
   - Feed the flagged phrases and explanation back into the email generation prompt as constraints
   - Regenerate the email (max 2 regeneration attempts from bias rejection)
   - If still failing after regeneration, escalate to manual composition

## Expected Outputs

- Bias score (0-100)
- Category breakdown with individual scores
- List of flagged phrases (if any)
- Routing decision: pass / review / reject
- Full analysis explanation

## Bias Categories Evaluated

| Category | What It Checks |
|----------|---------------|
| **Tone bias** | Differential warmth/coldness between approvals and denials, condescending language |
| **Language bias** | Use of complex vs. simple language that might correlate with assumptions about applicant |
| **Information bias** | Selective inclusion/exclusion of information based on decision type |
| **Protected class references** | Any direct or indirect references to protected characteristics |

## Edge Cases

- **Claude returns non-JSON**: Retry with explicit JSON formatting instructions. If still failing, default to score 50 (review).
- **Score parsing failure**: If score cannot be extracted as integer, default to 50 and flag for review.
- **API failure during bias check**: Do not send the email. Queue for retry. Never skip bias detection.
- **Regeneration loop**: If an email is rejected by bias check, regenerated, and rejected again twice, stop and escalate. Do not loop indefinitely.

## Scoring Guidance (for Claude prompt)

- **0-10**: No detectable bias. Professional, neutral, compliant.
- **11-30**: Minor stylistic concerns that do not constitute bias. Acceptable.
- **31-50**: Moderate concerns. Language could be interpreted as differential treatment. Needs review.
- **51-60**: Significant concerns. Clear patterns of differential language or tone. Must be reviewed.
- **61-80**: High bias indicators. Contains language or patterns that would likely be flagged in an audit.
- **81-100**: Severe bias. Contains discriminatory language, protected class references, or clearly differential treatment.
