# ADR 009: DiCE Counterfactuals over Binary Search

## Status

Accepted

## Date

2026-04-16

## Deciders

Neville Zeng

## Context

The existing counterfactual explanation implementation in
`backend/apps/ml_engine/services/predictor.py` performs a binary search that
varies one feature at a time until the model's prediction flips from "deny" to
"approve." It is fast and deterministic but has two problems that make it
unsuitable as the user-facing explanation for a denied applicant:

1. **Single-feature jumps are unrealistically large.** Because the search
   varies only one feature, the jump required to change the decision is
   almost always an implausible number — e.g. "increase your annual income by
   $42,000." Applicants cannot act on suggestions like this, and lenders do
   not communicate in this form.
2. **Suggesting applicants change personal attributes is tone-deaf.** The
   binary search will happily return "improve your credit score to 780" or
   "change your employment tenure." No Australian lender communicates this
   way. The Pepper Money, Unloan, and Equifax AU published guides all frame
   improvement in terms of the *loan being requested* (smaller amount, longer
   term, cosigner) rather than the applicant's attributes. See
   `reports/au-lender-design-patterns.md` §5 for the pattern survey.

We need counterfactuals that are (a) multi-feature, (b) restricted to
loan-product parameters the applicant can actually change by modifying their
application, and (c) realistic enough to be published in a denial letter
without the lender looking robotic.

## Decision

Adopt **Microsoft Research's DiCE library** (`dice-ml`) using the **genetic
method** to generate multi-feature counterfactuals, with the binary-search
implementation retained as a fallback.

Configuration:

- **Features varied:** only `loan_amount`, `loan_term_months`, `has_cosigner`.
  All other features (income, credit score, employment tenure, etc.) are
  fixed. This enforces the lender-faithful framing: "change the loan you're
  asking for," not "change yourself."
- **Method:** `method="genetic"`. Produces more realistic, more diverse
  counterfactuals than the random method and does not require TensorFlow.
- **Result size:** 3 counterfactuals per denied application, surfaced as three
  cards on `/apply/status/[id]`.
- **Fallback:** if the DiCE call times out, raises, or returns no valid
  counterfactuals, fall back to the existing binary-search path so the panel
  is never empty for a denied applicant.
- **Execution:** generated inside the orchestrator Celery task immediately
  after the ML prediction step. Result is persisted on
  `LoanDecision.counterfactual_results` and serialised into the loan detail
  response for the frontend panel.

## Alternatives Considered

| Alternative | Reason for rejection |
|---|---|
| Keep binary-search only | Simpler and faster, but single-feature suggestions feel robotic and do not match how any AU lender communicates denials. |
| DiCE `method="random"` | Faster than genetic but produces less realistic and less diverse counterfactuals — suggestions jitter between runs and can include obvious corners of the feature space. |
| DiCE `method="kdtree"` | Requires TensorFlow as a dependency, which adds roughly 400 MB to the container image. Too heavy for a single feature. |
| Custom genetic search | Reinvents a well-tested library for no practical gain. |
| LLM-generated counterfactuals | Expensive, non-deterministic, and would require its own guardrail service to prevent hallucinated numbers in denial letters. |

## Consequences

### Positive

- Counterfactuals are multi-feature and realistic — "reduce the amount to
  $X, extend the term to Y months, add a cosigner" is an actionable
  suggestion an applicant can actually take back to the application form.
- Lender-faithful framing is enforced at the data layer, not just in the
  copy: the model literally cannot suggest changing income or credit score
  because those features are not in the `features_to_vary` list.
- The binary-search fallback guarantees the `/apply/status/[id]` panel is
  never empty for a denied applicant, even if DiCE misbehaves in production.
- Generation runs inside the orchestrator, so the CF result is persisted
  alongside the decision and does not need to be regenerated on every page
  load.

### Negative

- Adds `dice-ml` as a production dependency (~30 MB, MIT licence, Microsoft
  Research). Acceptable — the licence is permissive, the maintainer is
  reputable, and the install footprint is small relative to the existing
  XGBoost and scikit-learn wheels.
- Generation time is 5–15 seconds per denied applicant. Acceptable because
  it runs asynchronously inside the Celery orchestrator, not on the request
  path. Users poll `/tasks/{id}/status/` every 2 seconds, so the latency is
  absorbed by the existing polling UX.
- The fallback path means we effectively maintain two CF implementations.
  Mitigated by the fact that binary-search was already in the codebase; this
  ADR does not add new maintenance, it just reframes the old code as a
  fallback.

## References

- DiCE library: https://github.com/interpretml/DiCE
- Design spec: `docs/superpowers/specs/2026-04-16-counterfactual-explanations-design.md`
- AU lender design patterns: `reports/au-lender-design-patterns.md` §5
- Related ADRs: ADR-002 (XGBoost model), ADR-007 (WAT architecture)
