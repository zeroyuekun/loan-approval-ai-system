# ADR 006: Template-First Email Generation with Cost Cap

## Status

Accepted

## Date

2026-04-01

## Context

The email engine uses Claude API to generate compliance correspondence (approval/denial letters). API costs are variable and unpredictable — a runaway loop or traffic spike could exhaust the budget. The system must guarantee email delivery even when the API is unavailable or budget is exhausted, while maintaining regulatory compliance in every email sent.

## Decision

Implement a template-first fallback architecture with a hard $5/day budget cap on Claude API usage.

### Architecture

1. **Primary path:** Claude API generates the email, which then passes through 10 deterministic guardrail checks (amount accuracy, discrimination language, regulatory disclosures, etc.).
2. **Budget guard:** `ApiBudgetGuard` tracks daily API spend. When the $5 cap is reached, all subsequent emails use the template path for the remainder of the day.
3. **Circuit breaker:** After 3 consecutive API failures (timeout, rate limit, server error), the system switches to templates for a 10-minute cooldown period before retrying the API.
4. **Template fallback:** Pre-written templates for each decision type (approval, denial, conditional approval) that pass all 18 guardrail checks by construction. Templates use variable substitution for applicant-specific details (name, amount, reason codes).

### Why templates pass compliance

The templates were authored against the same guardrail checklist that validates Claude-generated emails. They include all required regulatory disclosures (NCCP Act obligations, credit reporting rights, AFCA complaint path, hardship provisions) and use pre-approved language that has been verified against discrimination checks.

## Consequences

### Positive

- Emails always deliver — no scenario where a customer is left waiting because of an API outage
- Cost is predictable and bounded — $5/day ≈ $150/month maximum
- Quality degrades gracefully — templates are compliant but less personalised than Claude-generated emails
- Circuit breaker prevents cascading failures from hitting the API during outages

### Negative

- Template emails lack the natural tone of Claude-generated correspondence
- Maintaining two email paths (API + template) doubles the surface area for compliance updates
- The $5/day cap may need adjustment based on application volume — currently sized for demonstration/portfolio use
