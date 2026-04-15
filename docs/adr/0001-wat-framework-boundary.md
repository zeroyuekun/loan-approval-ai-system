# ADR-0001: WAT Framework Boundary

**Status:** Accepted
**Date:** 2026-04-15
**Deciders:** Neville Zeng

## Context

A loan-approval system mixes probabilistic reasoning (Claude-drafted emails, LLM-driven agentic orchestration, bias assessments) with deterministic execution (regulatory rules, arithmetic, database writes). Mixing these freely produces prompts that carry load-bearing business logic — the hardest kind of code to test, version, or review.

## Decision

We will separate three layers:

- **Workflows** — markdown SOPs in `workflows/` describing objective, inputs, tools, outputs, edge cases. Versioned as docs.
- **Agents** — AI reasoning and orchestration. Read the workflow, pick tools, handle failures, escalate.
- **Tools** — deterministic Python in `tools/` (standalone scripts) and `backend/apps/*/services/` (Django services). Unit-testable without the LLM.

The orchestrator runs workflows by invoking agents that call tools. Business logic lives in tools. Reasoning lives in agents. Intent lives in workflows.

## Alternatives Considered

- **Monolithic prompting** — one giant prompt doing everything. Rejected: unversionable, untestable, expensive, unpredictable under guardrail failure.
- **Pure-code pipelines** — no LLM reasoning, rules only. Rejected: cannot handle the compliance-email generation use case (tone, personalisation, edge explanations) without losing fidelity.
- **LangGraph / CrewAI frameworks** — tight coupling to one vendor, opinionated state model. Rejected for now: our surface is small; a 200-line orchestrator service is clearer than a framework.

## Consequences

**Positive:**
- Business logic is testable without network calls
- Prompts carry only reasoning, not arithmetic — cheaper, safer, auditable
- Workflows are human-readable SOPs; compliance can review them without reading Python
- Swapping LLM providers touches only the agent layer

**Negative:**
- Onboarding cost: three directories to learn instead of one
- Discipline required: resisting the temptation to put rules in prompts
- Some duplication — the workflow markdown restates what the code does

## References

- `backend/apps/agents/services/orchestrator.py`
- `workflows/` — SOP directory
- `backend/apps/ml_engine/services/underwriting_engine.py` — tool example
- Commit pattern: tools + services test-first; agents integrated afterwards
