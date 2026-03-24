# ADR 003: Hybrid Bias Detection System

## Status

Accepted

## Date

2026-03-23

## Context

The system generates AI-authored emails (approval and denial communications) sent directly to loan applicants. These emails must be free of discriminatory language, patronizing tone, and pressure tactics before reaching customers. Australian anti-discrimination law (Racial Discrimination Act 1975, Sex Discrimination Act 1984, Age Discrimination Act 2004) and ASIC conduct obligations require that customer communications do not discriminate on protected attributes.

## Decision

Implement a three-layer hybrid bias detection system:

1. **Deterministic regex pre-screen** — catches explicit violations instantly (<1ms, zero cost). Patterns cover references to age, gender, marital status, ethnicity, disability, religion, and other protected attributes. Handles 85-90% of cases where emails are clean.

2. **LLM review via Claude API** — for moderate-risk emails flagged by heuristic scoring. Evaluates nuanced and contextual bias that regex cannot detect (e.g., "consider your family situation" is appropriate in some contexts but discriminatory in others). Provides structured severity scoring.

3. **AI Email Reviewer** — a senior compliance second opinion for borderline cases where the LLM review returns an ambiguous score. Uses a separate prompt focused on regulatory compliance standards.

### Why not pure LLM?

- **Non-deterministic** — the same email could pass on one call and fail on the next
- **Expensive** — $0.003-0.01 per API call, unnecessary for clearly clean emails
- **Slow** — 1-3 seconds latency per call vs <1ms for regex
- **Fails closed on API outage** — all emails blocked if Claude API is unavailable
- The deterministic layer handles the majority of cases at zero cost in under 1ms

### Why not pure regex?

- Misses contextual bias (same phrase can be appropriate or discriminatory depending on context)
- Cannot detect subtle patronizing tone or condescension
- Cannot evaluate pressure tactics or manipulative framing
- Regex rules grow brittle and require constant maintenance for edge cases

## Consequences

**Positive:**

- Fast path for clean emails — 85-90% resolved in <1ms with zero API cost
- Deterministic baseline — regex results are reproducible and auditable
- Cost-efficient — LLM calls only for the 10-15% that need nuanced review
- Defense in depth — three independent layers reduce false negatives

**Negative:**

- Regex rules require ongoing maintenance as new bias patterns emerge
- LLM layer adds API dependency and associated latency for flagged emails
- Three-layer system is more complex to debug when disagreements occur between layers
- Must maintain consistency between regex patterns and LLM prompt definitions

## Alternatives Considered

| Alternative | Reason for rejection |
|---|---|
| Pure LLM review | Non-deterministic, expensive for clean emails, API dependency for all traffic |
| Pure regex/keyword matching | Misses contextual and subtle bias, high false negative rate |
| Fine-tuned classifier (BERT/RoBERTa) | Requires labeled bias training data (scarce), ongoing retraining, still misses novel patterns |
| Human review for all emails | Does not scale, introduces delay, expensive at volume |
