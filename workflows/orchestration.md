# Orchestration Workflow

## Objective

Chain all three levels of the AI loan approval system into a single agentic pipeline: ML prediction, email generation, and bias detection, with retry logic, next-best-offer generation for denials, and full step tracking via `AgentRun` records.

## Required Inputs

- `loan_id`: ID of the loan application to process
- Active trained model (loaded from `ModelVersion` with `is_active=True`)
- Claude API key for email generation and bias detection

## Tools

| Tool | Location | Purpose |
|------|----------|---------|
| Orchestrator service | `backend/apps/agents/services/orchestrator.py` | Chains all pipeline steps |
| ML predictor | `backend/apps/ml_engine/services/predictor.py` | Runs model inference |
| Email generator | `backend/apps/email_engine/services/email_generator.py` | Generates decision emails |
| Bias detector | `backend/apps/agents/services/bias_detector.py` | Scores emails for bias |
| NBO generator | `backend/apps/agents/services/next_best_offer.py` | Generates next-best-offer for denials |
| Marketing agent | `backend/apps/agents/services/marketing_agent.py` | Generates follow-up marketing email with alternative offers for denied applicants |

## Steps

1. **Receive loan_id** - Validate that the loan application exists and is in `pending` status. If not found or already processed, abort with appropriate error.

2. **Run ML prediction** (Level 1)
   - Load the active model version from `ModelVersion.objects.filter(is_active=True)`
   - Prepare features from the loan application record
   - Run prediction to get `approved` (bool) and `confidence` (float)
   - Record step: `{"step": "ml_prediction", "result": {"approved": bool, "confidence": float}, "duration_ms": int}`

3. **Generate email** (Level 2)
   - Pass loan details and prediction result to the email generator
   - Follow the email generation workflow (see `workflows/email_generation.md`)
   - Record step: `{"step": "email_generation", "result": {"attempt": int, "guardrail_passed": bool}, "duration_ms": int}`

4. **Run bias check** (Level 3)
   - Send generated email to bias detector
   - Follow the bias detection workflow (see `workflows/bias_detection.md`)
   - Record step: `{"step": "bias_detection", "result": {"score": int, "action": str}, "duration_ms": int}`

5. **Handle bias result**:
   - **Pass** (score 0-30): Proceed to finalization
   - **Review** (score 31-60): Mark for human review, proceed to finalization with `requires_review=True`
   - **Reject** (score 61-100): Regenerate email with bias feedback, re-run bias check (max 2 retries from this step)
   - Record each retry as a separate step entry

6. **Generate NBO** (if denied)
   - If the loan was denied, generate a next-best-offer suggestion
   - Consider: lower loan amount, different term, secured vs. unsecured, co-signer suggestion
   - Record step: `{"step": "nbo_generation", "result": {"offer_type": str}, "duration_ms": int}`

7. **Generate Marketing Message** (if NBO succeeded)
   - Generate a customer-facing marketing message summarising the NBO offers
   - Update the NBO record with the marketing message

8. **Marketing Agent Email** (if NBO succeeded)
   - The Marketing Agent generates a full follow-up email presenting the alternative offers
   - The email is forward-looking (no decline references) and includes a clear call to action
   - Runs marketing-specific guardrails: prohibited language, tone, no decline language, call to action
   - Retries up to 3 times if guardrails fail
   - Saves a `MarketingEmail` record linked to the `AgentRun`
   - Record step: `{"step": "marketing_email_generation", "result": {"subject": str, "passed_guardrails": bool}, "duration_ms": int}`

9. **Finalize AgentRun**
   - Update loan application status to `approved` or `denied`
   - Save the complete `AgentRun` record with all steps
   - Store the final email in `GeneratedEmail` model
   - Set `AgentRun.status` to `completed` (or `review_needed` if flagged)

## AgentRun Schema

```python
AgentRun(
    loan_application=loan,          # FK to LoanApplication
    status="completed",             # pending | running | completed | failed | review_needed
    steps=[                         # JSONField - ordered list of step records
        {
            "step": "ml_prediction",
            "started_at": "2026-03-12T10:00:00Z",
            "completed_at": "2026-03-12T10:00:01Z",
            "duration_ms": 1000,
            "result": {"approved": True, "confidence": 0.87}
        },
        # ... additional steps
    ],
    total_duration_ms=5000,
    created_at=...,
    updated_at=...
)
```

## Expected Outputs

- Updated `LoanApplication` with final decision
- `AgentRun` record with full step history and timing
- `GeneratedEmail` record with final email content
- NBO record (if applicable)
- `MarketingEmail` record with follow-up marketing email (if denied and NBO generated)

## Edge Cases

- **Model not found**: If no active model version exists, abort with `"No active model. Train a model first."` and set `AgentRun.status = "failed"`.
- **Prediction failure**: Log the error, set status to `failed`, do not proceed to email generation.
- **Email generation exhausts retries**: Set status to `failed`, log all attempts.
- **Bias check exhausts retries**: Set status to `failed`, flag for manual email composition.
- **Database error during save**: Wrap the entire pipeline in a transaction. If any save fails, roll back and set status to `failed`.
- **Celery timeout**: Set a hard time limit of 120 seconds on the orchestrator task. If exceeded, mark as `failed`.

## Celery Integration

The orchestrator runs as a single Celery task on the `agents` queue:

```python
@shared_task(queue='agents', time_limit=120, soft_time_limit=110)
def run_agent_pipeline(loan_id):
    orchestrator = OrchestratorService()
    return orchestrator.run(loan_id)
```

The frontend polls `/api/v1/tasks/{task_id}/status/` every 2 seconds to check progress.
