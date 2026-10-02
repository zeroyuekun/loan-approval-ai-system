# ADR 007: WAT architecture (Workflows, Agents, Tools)

## Status

Accepted

## Date

2026-04-01

## Context

The loan approval pipeline has to orchestrate several AI and non-AI steps: ML prediction, email generation, bias detection, next-best-offer generation, and escalation. Some steps are probabilistic decisions (LLM reasoning, model inference) and some are deterministic execution (database writes, email sending, guardrail checks). The architecture has to keep the two apart for testability, auditability, and regulatory compliance.

I considered just chaining Celery tasks directly, but I wanted step-level logging for observability, so I could see exactly where a pipeline failed and how long each step took. The other alternatives were microservices (each step as a separate service) and a monolithic pipeline (all logic in one function).

## Decision

Adopt the WAT (Workflows, Agents, Tools) framework, which has three layers:

### Layer 1: Workflows (Markdown SOPs)

Markdown files in `workflows/` define the objective, required inputs, available tools, expected outputs, and edge cases for each process. They are specifications a person can read, and they serve both as documentation and as the source of truth for what the pipeline should do.

### Layer 2: Agents (AI reasoning)

Agents handle orchestration, decision-making, and failure recovery. The orchestrator agent reads the workflow, decides which tools to invoke, handles conditional logic (e.g., bias score thresholds for escalation), and logs each step to an `AgentRun` record. All agent decisions run inside a single Celery task, with no distributed coordination.

### Layer 3: Tools (Deterministic execution)

Python scripts in `tools/` and Django services in `backend/apps/*/services/` perform the deterministic operations: model inference, SHAP computation, email template rendering, guardrail checks, database writes. Tools are pure functions or service methods with predictable inputs and outputs. They make no LLM calls and have no probabilistic behaviour.

### Why not microservices

- The pipeline steps are tightly coupled in sequence (prediction → email → bias check → send). Microservices would add network hops, distributed transaction complexity, and deployment coordination overhead without a meaningful scaling benefit, because the bottleneck is Celery worker capacity, not service-to-service throughput.
- A single Django process with Celery queues (`ml`, `email`, `agents`) isolates workloads without the operational complexity.

### Why not a monolithic function

- Mixing LLM reasoning with deterministic execution makes testing difficult. You can't unit test a guardrail check if it's buried inside an LLM orchestration loop.
- Regulatory audits require a clear separation between "what the model decided" and "what happened as a result." WAT's layers map directly onto that requirement.

## Consequences

### Positive

- Each layer can be tested on its own: tools have unit tests, workflows have integration tests, and agent behaviour has end-to-end tests.
- The audit trail is clear. `AgentRun` records capture which workflow was followed, which tools were invoked, and what decisions were made.
- Adding a step means creating a tool and updating the workflow. No service deployment is required.
- When a tool fails, the workflow can be updated to handle that edge case (the self-improvement loop).

### Negative

- The workflow markdown files are maintained by hand and can drift from the actual implementation if nobody updates them.
- The single-process design limits horizontal scaling of individual steps (mitigated by separate Celery queues).
- The pattern is less common than microservices, so new contributors may need onboarding time.
