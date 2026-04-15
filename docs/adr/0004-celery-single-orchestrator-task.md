# ADR-0004: Celery single orchestrator task

**Status:** Accepted
**Date:** 2026-04-15
**Deciders:** Neville Zeng

## Context

A loan decisioning pipeline has multiple IO-bound steps (prediction, bias check, email generation, next-best-offer, audit). There are three common orchestration shapes: canvas chord/chain (Celery native), saga with compensation (distributed transaction replacement), or monolithic task with internal step tracking.

## Decision

We will run each pipeline invocation as **one `AgentRun` row and one Celery task**, with substeps recorded via `apps.agents.services.step_tracker`. The task is responsible for: calling services in order, persisting step outcomes, escalating on failure, emitting the final `LoanDecision`.

## Alternatives Considered

- **Celery canvas chord/chain** — Rejected for now: harder to reason about partial failure, introduces broker state across task boundaries, makes local debugging awkward. Revisit if step durations diverge dramatically.
- **Saga pattern with compensation** — Rejected for now: the only real revert (un-send email, reverse decision) is not actually reversible; a saga adds complexity for a compensation surface we cannot exercise. Documented as future work.
- **AWS Step Functions / Temporal** — Rejected: vendor lock-in, operational cost for a portfolio project. The principle (state-machine orchestration) is documented in the workflow SOP instead.

## Consequences

**Positive:**
- Single mental model: one Redis key per run, one row per run, one process
- Local debugging: rerun the task in a Python shell with a saved kwargs dict
- Retry logic lives in one place (Celery retry policy on the task)
- Tests mock one entrypoint

**Negative:**
- No automatic compensation — a bias-check failure means we've already persisted a prediction but not the decision
- Long-running tasks hold a worker; one slow Claude API call blocks a worker thread
- No parallelism between steps — sequential by construction

## References

- `backend/apps/agents/services/orchestrator.py` — main orchestrator
- `backend/apps/agents/services/step_tracker.py` — substep recording
- `backend/tests/test_orchestrator.py`, `test_orchestrator_resilience.py`
- Future spec (not yet written): event-driven refactor with compensation
