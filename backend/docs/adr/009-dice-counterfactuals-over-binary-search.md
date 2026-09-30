# ADR 009: DiCE counterfactuals over binary search

## Status

Accepted

## Date

2026-04-16

## Deciders

Neville Zeng

## Context

The existing counterfactual explanation code in
`backend/apps/ml_engine/services/predictor.py` runs a binary search that varies
one feature at a time until the model's prediction flips from "deny" to
"approve." It is fast and deterministic, but two problems make it unsuitable as
the explanation a denied applicant sees:

1. **Single-feature jumps are unrealistically large.** Because the search
   varies only one feature, the change needed to flip the decision is almost
   always an implausible number, e.g. "increase your annual income by
   $42,000." Applicants cannot act on suggestions like this, and lenders do
   not communicate in this form.
2. **Suggesting applicants change personal attributes is tone-deaf.** The
   binary search will happily return "improve your credit score to 780" or
   "change your employment tenure." No Australian lender communicates this
   way. The published guides from Pepper Money, Unloan, and Equifax AU all
   frame improvement in terms of the *loan being requested* (smaller amount,
   longer term, cosigner), not the applicant's attributes. See
   `reports/au-lender-design-patterns.md` §5 for the pattern survey.

We need counterfactuals that are (a) multi-feature, (b) restricted to
loan-product parameters the applicant can actually change by modifying their
application, and (c) realistic enough to publish in a denial letter without
the lender looking robotic.

## Decision

Adopt Microsoft Research's DiCE library (`dice-ml`) with the genetic method to
generate multi-feature counterfactuals, and keep the binary-search
implementation as a fallback.

Configuration:

- **Features varied:** only `loan_amount`, `loan_term_months`, `has_cosigner`.
  All other features (income, credit score, employment tenure, etc.) are
  fixed. This enforces the lender-faithful framing: "change the loan you're
  asking for," not "change yourself."
- **Method:** `method="genetic"`. It produces more realistic and more diverse
  counterfactuals than the random method, and it does not require TensorFlow.
- **Result size:** 3 counterfactuals per denied application, shown as three
  cards on `/apply/status/[id]`.
- **Fallback:** if the DiCE call times out, raises, or returns no valid
  counterfactuals, fall back to the existing binary-search path so the panel
  is never empty for a denied applicant.
- **Execution:** generated inside the orchestrator Celery task immediately
  after the ML prediction step. The result is persisted on
  `LoanDecision.counterfactual_results` and serialised into the loan detail
  response for the frontend panel.

## Alternatives considered

| Alternative | Reason for rejection |
|---|---|
| Keep binary-search only | Simpler and faster, but single-feature suggestions feel robotic and do not match how any AU lender communicates denials. |
| DiCE `method="random"` | Faster than genetic but produces less realistic and less diverse counterfactuals. Suggestions jitter between runs and can include obvious corners of the feature space. |
| DiCE `method="kdtree"` | Requires TensorFlow as a dependency, which adds roughly 400 MB to the container image. Too heavy for a single feature. |
| Custom genetic search | Reinvents a well-tested library for no practical gain. |
| LLM-generated counterfactuals | Expensive, non-deterministic, and would need its own guardrail service to prevent hallucinated numbers in denial letters. |

## Consequences

### Positive

- Counterfactuals are multi-feature and realistic: "reduce the amount to
  $X, extend the term to Y months, add a cosigner" is a suggestion an
  applicant can actually take back to the application form.
- The lender-faithful framing is enforced at the data layer as well as in the
  copy. The model cannot suggest changing income or credit score, because
  those features are not in the `features_to_vary` list.
- The binary-search fallback guarantees the `/apply/status/[id]` panel is
  never empty for a denied applicant, even if DiCE misbehaves in production.
- Generation runs inside the orchestrator, so the CF result is persisted
  alongside the decision and doesn't have to be regenerated on every page
  load.

### Negative

- Adds `dice-ml` as a production dependency (~30 MB, MIT licence, Microsoft
  Research). This is acceptable: the licence is permissive, the maintainer is
  reputable, and the install footprint is small next to the existing XGBoost
  and scikit-learn wheels.
- Generation takes 5-15 seconds per denied applicant. That is acceptable
  because it runs asynchronously inside the Celery orchestrator, off the
  request path. Users poll `/tasks/{id}/status/` every 2 seconds, so the
  existing polling UX absorbs the latency.
- With the fallback path we effectively maintain two CF implementations. The
  binary search was already in the codebase, though, so this ADR adds no new
  maintenance; it only reframes the old code as a fallback.

## References

- DiCE library: https://github.com/interpretml/DiCE
- Design spec: `docs/superpowers/specs/2026-04-16-counterfactual-explanations-design.md`
- AU lender design patterns: `reports/au-lender-design-patterns.md` §5
- Related ADRs: ADR-002 (XGBoost model), ADR-007 (WAT architecture)
