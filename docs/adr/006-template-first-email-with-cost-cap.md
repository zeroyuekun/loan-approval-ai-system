# ADR 006: Template-first email generation with cost cap

## Status

Accepted

## Date

2026-04-01

## Context

The email engine uses the Claude API to write compliance correspondence (approval and denial letters). API costs vary and are hard to predict: a runaway loop or a traffic spike could use up the budget. The system must still guarantee email delivery when the API is unavailable or the budget is spent, and every email it sends must stay compliant.

## Decision

Implement a template-first fallback architecture with a hard $5/day budget cap on Claude API usage.

### Architecture

1. **Primary path:** the Claude API writes the email, which then goes through 10 deterministic guardrail checks (amount accuracy, discrimination language, regulatory disclosures, and so on).
2. **Budget guard:** `ApiBudgetGuard` tracks daily API spend. Once the $5 cap is reached, every email for the rest of the day uses the template path.
3. **Circuit breaker:** after 3 consecutive API failures (timeout, rate limit, server error), the system switches to templates for a 10-minute cooldown before trying the API again.
4. **Template fallback:** each decision type (approval, denial, conditional approval) has a pre-written template that passes all 18 guardrail checks by construction. Templates fill in applicant-specific details (name, amount, reason codes) by variable substitution.

### Why templates pass compliance

The templates were written against the same guardrail checklist that validates Claude-generated emails. They include all the required regulatory disclosures (NCCP Act obligations, credit reporting rights, AFCA complaint path, hardship provisions) and use pre-approved language that has been verified against the discrimination checks.

## Consequences

### Positive

- Emails always go out. An API outage never leaves a customer waiting.
- Cost is predictable and bounded: $5/day ≈ $150/month at most.
- Quality degrades gracefully. Templates are compliant but less personalised than Claude-generated emails.
- During outages, the circuit breaker stops cascading failures from hitting the API.

### Negative

- Template emails don't have the natural tone of Claude-generated correspondence.
- With two email paths (API + template), every compliance update has twice the surface area to cover.
- The $5/day cap may need adjusting for application volume. It is currently sized for demonstration/portfolio use.
