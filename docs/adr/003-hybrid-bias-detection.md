# ADR 003: Hybrid bias detection system

## Status

Accepted

## Date

2026-03-23

## Context

The system sends AI-written emails (approval and denial communications) directly to loan applicants. Before an email reaches a customer, it has to be free of discriminatory language, patronizing tone, and pressure tactics. Australian anti-discrimination law (Racial Discrimination Act 1975, Sex Discrimination Act 1984, Age Discrimination Act 2004) and ASIC conduct obligations require that customer communications do not discriminate on protected attributes.

## Decision

Implement a three-layer hybrid bias detection system:

1. **Deterministic regex pre-screen.** Catches explicit violations instantly (<1ms, zero cost). The patterns cover references to age, gender, marital status, ethnicity, disability, religion, and other protected attributes. This layer handles the 85-90% of cases where the email is clean.

2. **LLM review via the Claude API.** Runs on moderate-risk emails flagged by heuristic scoring. It judges subtle, contextual bias that regex cannot detect: "consider your family situation" is appropriate in some contexts and discriminatory in others. It returns a structured severity score.

3. **Human escalation (decision emails) / senior AI review (marketing emails).** For decision emails, a score at or above the review threshold sends the application to the human-review queue. There is no per-email senior Claude call, to respect the $5/day budget cap. Marketing emails to declined customers carry more cross-selling risk, so a senior compliance reviewer (`MarketingEmailReviewer`, Opus) assesses the moderate-band ones and escalates when its confidence is below 0.70. The `AIEmailReviewer` class exists for a senior pass on decision emails but is deliberately not wired into the decision pipeline, for cost reasons. Enabling it is a documented future option; it is not current behaviour.

### Why not pure LLM?

- It is non-deterministic: the same email could pass on one call and fail on the next.
- It costs $0.003-0.01 per API call, which is wasted on clearly clean emails.
- It is slow: 1-3 seconds of latency per call, against <1ms for regex.
- It fails closed on an API outage, so every email is blocked while the Claude API is unavailable.
- The deterministic layer already handles most cases at zero cost in under 1ms.

### Why not pure regex?

- It misses contextual bias, where the same phrase can be appropriate or discriminatory depending on context.
- It can't detect subtle patronizing tone or condescension.
- It can't judge pressure tactics or manipulative framing.
- Regex rules get brittle and need constant maintenance for edge cases.

## Consequences

**Positive:**

- Clean emails take a fast path: 85-90% are resolved in <1ms with zero API cost.
- The regex baseline is deterministic, so its results are reproducible and auditable.
- LLM calls, and their cost, are limited to the 10-15% of emails that need closer review.
- Three independent layers reduce false negatives (defense in depth).

**Negative:**

- Regex rules need ongoing maintenance as new bias patterns appear.
- The LLM layer adds an API dependency, and its latency, for flagged emails.
- When the layers disagree, a three-layer system is harder to debug.
- The regex patterns and the LLM prompt definitions have to be kept consistent with each other.

## Alternatives considered

| Alternative | Reason for rejection |
|---|---|
| Pure LLM review | Non-deterministic, expensive for clean emails, API dependency for all traffic |
| Pure regex/keyword matching | Misses contextual and subtle bias, high false negative rate |
| Fine-tuned classifier (BERT/RoBERTa) | Needs labeled bias training data (scarce) and ongoing retraining, and still misses novel patterns |
| Human review for all emails | Does not scale, introduces delay, expensive at volume |

## Implementation note (2026-06-01)

Layer 2 (junior LLM) runs only on the *moderate* deterministic band. The
deterministic gate resolves clean emails on its own at zero API cost, and severe
ones with a single escalation. For **decision** emails, layer 3 is direct human
escalation: the `AIEmailReviewer` senior pass is implemented but not invoked, to
keep within the $5/day Claude budget. Senior AI review applies only to
**marketing** emails, where the cross-selling risk justifies the spend. The
severe-violation boundary is inclusive (`>=`) and shared by the decision and
marketing gates through `apps/agents/services/bias/thresholds.is_severe`. If the
bias check's *infrastructure* fails, the pipeline fails SAFE (`BIAS_FAILURE_MODE`,
default `block`): the email is withheld and the run is flagged, so it never ships
a decision with bias detection effectively off.
