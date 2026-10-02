# Email generation workflow

## Objective

Use the Claude API to write approval and denial emails for loan applicants. The emails must comply with fair lending rules, and guardrail checks confirm regulatory compliance and a professional tone.

## Tools

| Tool | Location | Purpose |
|------|----------|---------|
| Email generator service | `backend/apps/email_engine/services/email_generator.py` | Django service for Claude API email generation |
| Guardrails package | `backend/apps/email_engine/services/guardrails/` | Post-generation compliance checks |
| API connectivity test | `tools/test_claude_api.py` | Verify Claude API access before running pipeline |

## Steps

1. **Build the prompt.** Take the loan application details (applicant name, loan amount, purpose, decision, interest rate if approved, denial reasons if denied) and build a system prompt and a user message:
   - The system prompt defines the role (professional loan officer), tone (respectful, clear), and constraints (fair lending compliance)
   - The user message includes the applicant's first name, loan amount, loan purpose, decision, and decision-specific details
   - For approvals, include the approved amount, interest rate, term, and next steps
   - For denials, include specific, actionable denial reasons (e.g., "debt-to-income ratio exceeds our threshold") and alternative options

2. **Call the Claude API.** Send the prompt to Claude (model: `claude-sonnet-4-20250514`) with:
   - `max_tokens`: 1024
   - `temperature`: 0.3 (low creativity for consistency)
   - Timeout: 30 seconds

3. **Run guardrails.** Check the generated email against every rule:
   - **Prohibited language**: Reject the email if it refers to race, ethnicity, religion, gender, marital status, national origin, disability, age, sexual orientation, or any other protected class
   - **No hallucinated numbers**: Cross-check every dollar amount and percentage against the input data. If the email mentions a number that isn't in the input, flag it.
   - **Professional tone**: No slang, no overly casual language, and no exclamation marks in denial emails
   - **Required elements**: A subject line, a greeting with the applicant's name, a clear decision statement, and a closing with contact information
   - **Denial-specific**: Must include at least one specific reason, must mention the right to request reconsideration, and must not discourage future applications

4. **Retry on failure.** If the guardrails fail:
   - Append the failure reasons to the prompt as additional constraints
   - Retry up to 3 times total
   - If all 3 attempts fail, escalate to manual review and log the failure

5. **Save.** Store the generated email in the database with:
   - The final email text
   - Guardrail pass/fail status
   - Number of attempts
   - Generation timestamp
   - Model version used

## Expected outputs

- Email text (subject + body) ready to send
- Guardrail report (pass/fail with details)
- Metadata: attempt count, generation time, model used

## Guardrail details

### Prohibited terms (non-exhaustive, check against full list in guardrails.py)
- Direct references to protected classes
- Stereotyping language
- Assumptions about applicant based on name or location
- Any language that could be interpreted as discriminatory

### Validation checks
- All monetary values match input data (within rounding tolerance)
- Interest rates are within reasonable bounds (2%-36%)
- Loan terms match standard offerings
- No promises or guarantees not backed by the decision data

## Edge cases

- **API timeout**: Retry with exponential backoff (2s, 4s, 8s). After 3 timeouts, mark the email as failed.
- **Rate limiting**: If you get a 429, wait for the `Retry-After` header duration, then retry.
- **Empty response**: Treat it as a guardrail failure and retry with an explicit instruction to generate the complete email.
- **Very long applicant names**: Truncate the display name in the greeting to 50 characters.

## Example prompt structure

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
