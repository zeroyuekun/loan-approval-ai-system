# Email Generation Workflow

## Objective

Generate fair lending compliant approval and denial emails for loan applicants using the Claude API, with guardrail checks to ensure regulatory compliance and professional tone.

## Required Inputs

- Loan application details: applicant name, loan amount, purpose, decision (approved/denied), interest rate (if approved), denial reasons (if denied)
- Claude API key (from `.env` as `ANTHROPIC_API_KEY`)

## Tools

| Tool | Location | Purpose |
|------|----------|---------|
| Email generator service | `backend/apps/email_engine/services/email_generator.py` | Django service for Claude API email generation |
| Guardrails module | `backend/apps/email_engine/services/guardrails.py` | Post-generation compliance checks |
| API connectivity test | `tools/test_claude_api.py` | Verify Claude API access before running pipeline |

## Steps

1. **Build prompt** - Construct a system prompt and user message with the loan context:
   - System prompt defines the role (professional loan officer), tone (respectful, clear), and constraints (fair lending compliance)
   - User message includes: applicant first name, loan amount, loan purpose, decision, and decision-specific details
   - For approvals: include approved amount, interest rate, term, next steps
   - For denials: include specific, actionable denial reasons (e.g., "debt-to-income ratio exceeds our threshold"), alternative options

2. **Call Claude API** - Send prompt to Claude (model: `claude-sonnet-4-20250514`) with:
   - `max_tokens`: 1024
   - `temperature`: 0.3 (low creativity for consistency)
   - Timeout: 30 seconds

3. **Run guardrails** - Check the generated email against all rules:
   - **Prohibited language**: Reject if email contains references to race, ethnicity, religion, gender, marital status, national origin, disability, age, sexual orientation, or any other protected class
   - **No hallucinated numbers**: Cross-check any dollar amounts or percentages against the input data. If the email mentions a number not in the input, flag it.
   - **Professional tone**: No slang, no overly casual language, no exclamation marks in denial emails
   - **Required elements**: Subject line present, greeting with applicant name, clear decision statement, closing with contact information
   - **Denial-specific**: Must include at least one specific reason, must mention right to request reconsideration, must not be discouraging about future applications

4. **Retry on failure** - If guardrails fail:
   - Append the failure reasons to the prompt as additional constraints
   - Retry up to 3 times total
   - If all 3 attempts fail, escalate to manual review and log the failure

5. **Save** - Store the generated email in the database with:
   - The final email text
   - Guardrail pass/fail status
   - Number of attempts
   - Generation timestamp
   - Model version used

## Expected Outputs

- Email text (subject + body) ready to send
- Guardrail report (pass/fail with details)
- Metadata: attempt count, generation time, model used

## Guardrail Details

### Prohibited Terms (non-exhaustive, check against full list in guardrails.py)
- Direct references to protected classes
- Stereotyping language
- Assumptions about applicant based on name or location
- Any language that could be interpreted as discriminatory

### Validation Checks
- All monetary values match input data (within rounding tolerance)
- Interest rates are within reasonable bounds (2%-36%)
- Loan terms match standard offerings
- No promises or guarantees not backed by the decision data

## Edge Cases

- **API timeout**: Retry with exponential backoff (2s, 4s, 8s). After 3 timeouts, mark as failed.
- **Rate limiting**: If 429 received, wait for `Retry-After` header duration, then retry.
- **Empty response**: Treat as guardrail failure, retry with explicit instruction to generate complete email.
- **Very long applicant names**: Truncate display name to 50 characters in greeting.

## Example Prompt Structure

```
System: You are a professional loan officer composing an email to a loan applicant.
Write in a respectful, clear, and compliant tone. Never reference protected classes.
Include specific, actionable information.

User: Generate a {decision} email for:
- Applicant: {first_name}
- Loan Amount: ${loan_amount}
- Purpose: {purpose}
- {decision-specific details}
```
