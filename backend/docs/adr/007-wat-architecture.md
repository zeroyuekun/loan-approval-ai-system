# ADR 007: WAT Architecture (Workflows, Agents, Tools)

## Status

Accepted

## Date

2026-04-01

## Context

The loan approval pipeline requires orchestrating multiple AI and non-AI steps: ML prediction, email generation, bias detection, next-best-offer generation, and escalation. These steps involve both probabilistic decisions (LLM reasoning, model inference) and deterministic execution (database writes, email sending, guardrail checks). The architecture must keep these concerns separated for testability, auditability, and regulatory compliance.

I considered just chaining Celery tasks directly but wanted step-level logging for observability — being able to see exactly where a pipeline failed and how long each step took. The other alternatives were microservices (each step as a separate service) and a monolithic pipeline (all logic in one function).

## Decision

Adopt the WAT (Workflows, Agents, Tools) framework with three distinct layers:

### Layer 1: Workflows (Markdown SOPs)

Markdown files in `workflows/` define the objective, required inputs, available tools, expected outputs, and edge cases for each process. These are human-readable specifications that serve as both documentation and the source of truth for what the pipeline should do.

### Layer 2: Agents (AI Reasoning)

Agents handle orchestration, decision-making, and failure recovery. The orchestrator agent reads the workflow, decides which tools to invoke, handles conditional logic (e.g., bias score thresholds for escalation), and logs each step to an `AgentRun` record. All agent decisions run as a single Celery task — no distributed coordination.

### Layer 3: Tools (Deterministic Execution)

Python scripts in `tools/` and Django services in `backend/apps/*/services/` perform deterministic operations: model inference, SHAP computation, email template rendering, guardrail checks, database writes. Tools are pure functions or service methods with predictable inputs and outputs — no LLM calls, no probabilistic behaviour.

### Why not microservices

- The pipeline steps are tightly coupled in sequence (prediction → email → bias check → send). Microservices would add network hops, distributed transaction complexity, and deployment coordination overhead without meaningful scaling benefits — the bottleneck is Celery worker capacity, not service-to-service throughput.
- A single Django process with Celery queues (`ml`, `email`, `agents`) provides workload isolation without operational complexity.

### Why not a monolithic function

- Mixing LLM reasoning with deterministic execution makes testing difficult — you can't unit test a guardrail check if it's buried inside an LLM orchestration loop.
- Regulatory audits require clear separation between "what the model decided" and "what happened as a result." WAT's layered design maps directly to this requirement.

## Consequences

### Positive

- Each layer can be tested independently — tools have unit tests, workflows have integration tests, agent behaviour has end-to-end tests
- Audit trail is clear: `AgentRun` records capture which workflow was followed, which tools were invoked, and what decisions were made
- New steps can be added by creating a tool and updating the workflow — no service deployment required
- Self-improvement loop: when a tool fails, the workflow can be updated to handle the edge case

### Negative

- The workflow markdown files require manual maintenance — they can drift from actual implementation if not updated
- Single-process design limits horizontal scaling of individual steps (mitigated by separate Celery queues)
- The pattern is less common than microservices, which may require onboarding time for new contributors
