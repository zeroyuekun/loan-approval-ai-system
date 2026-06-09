# ADR 010: Pluggable Email LLM Backend (free Groq option) and the Data-Safety Decision

## Status

Accepted

## Date

2026-06-10

## Context

The decision emails (approval/denial) are written by an LLM. The lending
**decision** itself is deterministic ML (ADR 002) — so the email writer is a
low-stakes, swappable component, not a system dependency. Two pressures meet
here:

1. **Cost.** The default writer is the paid Claude API. For a portfolio /
   demonstrator that should run end-to-end with no spend, paying per email is
   friction.
2. **Data safety.** The emails carry applicant context. Many *free* consumer AI
   tiers (e.g. Google Gemini's free tier, Mistral's free Experiment plan) train
   on submitted prompts and may have humans review them. Routing real borrower
   information to a tier like that is exactly what a real lender must not do.

The naive way to "use free AI" would be to point the email prompt at whatever
free endpoint is cheapest. That is the wrong instinct for a lending system, and
saying *why* it's wrong is the point of this ADR.

## Decision

Make the email LLM backend **pluggable behind a config toggle**, and when a free
hosted option is wanted, use **Groq** specifically — chosen on data-safety
grounds, not just price.

### Why Groq, and not "any free API"

- **Groq's free tier does not train on inference prompts by default** (it retains
  only transient abuse/troubleshooting logs, with optional zero-data-retention).
  That is the deciding factor — it is the free hosted option whose data contract
  is acceptable, whereas free Gemini / free Mistral train on prompts unless you
  manually opt out.
- It is **OpenAI-compatible**, so it reuses the existing forced-tool structured
  output (`{subject, body}`) and supports `temperature=0` + a `seed` for
  reproducibility — keeping the emails as deterministic as practical.

### Defense in depth — three independent reasons this is safe here

1. **Synthetic data.** The system runs entirely on generated, non-real
   applicants (ADR 001; `generate_data` seeds fictional `example.com`
   customers). There is no real client PII in the repo, so nothing personal
   leaves the box even in the worst case.
2. **Minimised prompt surface.** The email prompt already sends only anonymised
   feature summaries and model scores — never raw PII (see
   `docs/compliance/australia.md`, APP 11).
3. **Audited disclosure.** Every cloud call is logged to `APICallLog` with PII
   categories and `destination_country` for Privacy Act APP 8 cross-border
   audit. The Groq backend logs `provider="groq"`.

### Architecture

- A thin adapter, `GroqLLMClient`
  (`backend/apps/email_engine/services/llm_client.py`), duck-types
  `anthropic.Anthropic` (`.messages.create(**kwargs)`). It translates the
  Anthropic-shaped request (forced `submit_email` tool → OpenAI function calling,
  injects `temperature=0` + `seed`) and normalises the OpenAI response back into
  the shape the caller already reads. It raises `anthropic.RateLimitError` on
  HTTP 429 so the existing retry seam is reused, and emits a text block alongside
  the tool block so the existing text-parse fallback covers a malformed tool call
  (smaller models are less reliable at forced tool use).
- The backend is selected by `EMAIL_LLM_BACKEND` (`anthropic` default | `groq`),
  with `EMAIL_LLM_MODEL`, `EMAIL_LLM_SEED`, `GROQ_API_KEY`, `GROQ_BASE_URL`.
- **Everything else is unchanged.** The free model still flows through the same
  `$5/day` budget guard (ADR 006), the same 18-check guardrail battery, the same
  retry loop, and — critically — the same deterministic **template fallback**
  when no key is set or the call fails. Built on `httpx`, which is already a
  dependency, so the swap adds **zero new packages**.
- **Bias detection deliberately stays on the deterministic rules.** The free
  model writes prose; it is not put in charge of the safety-critical compliance
  gate (ADR 003). That keeps the safety floor auditable and model-independent.

## Consequences

### Positive

- The email writer can run at **$0** with no key rotation and no rate-limit risk
  to the demo, while the decision path stays deterministic and free regardless.
- The data-safety reasoning is explicit and defensible: free, but *not* at the
  cost of training a third party on borrower data.
- Provider-agnostic by construction — switching to a no-train paid tier or a
  local/self-hosted model for real production is a config change, not a rewrite.

### Negative

- `llama-3.1-8b-instant` is weaker than Claude at forced tool calls and exact
  figure reproduction; the guardrail + retry + template-fallback chain absorbs
  this, but more emails may fall back or retry than on Claude.
- Groq's `seed` is best-effort, so reproducibility is "near-identical," not
  bitwise — acceptable given temperature 0 and the constrained prompt.
- Two providers' response shapes to keep in parity (mitigated by the adapter and
  its unit tests).

### Production note

For a real deployment with real borrowers, Groq's free tier is **not** the
endpoint to use — switch the same toggle to a no-train paid tier or a
self-hosted model. The free Groq backend is for the synthetic-data demo, where
the data-safety argument above holds.
