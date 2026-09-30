# ADR 010: Pluggable email LLM backend (free Groq option) and the data-safety decision

## Status

Accepted

## Date

2026-06-10

## Context

An LLM writes the decision emails (approval/denial). The lending **decision**
itself comes from deterministic ML (ADR 002), so the email writer is a
low-stakes, swappable component and not a system dependency. Two concerns meet
here:

1. **Cost.** The default writer is the paid Claude API. A portfolio
   demonstrator should run end to end without spending anything, and paying per
   email gets in the way of that.
2. **Data safety.** The emails carry applicant context. Many free consumer AI
   tiers (for example Google Gemini's free tier and Mistral's free Experiment
   plan) train on submitted prompts and may have humans review them. Sending
   real borrower information to a tier like that is exactly what a real lender
   must not do.

The naive way to "use free AI" would be to point the email prompt at whatever
free endpoint is cheapest. For a lending system that is the wrong instinct, and
this ADR exists to record why.

## Decision

Make the email LLM backend pluggable behind a config toggle. When a free hosted
option is wanted, use Groq specifically, chosen on data-safety grounds and not
only on price.

### Why Groq, and not "any free API"

- Groq's free tier does not train on inference prompts by default. It keeps
  only transient abuse/troubleshooting logs, with optional zero data retention.
  That is the deciding factor: it is the free hosted option whose data contract
  is acceptable, whereas free Gemini and free Mistral train on prompts unless
  you opt out manually.
- It is OpenAI-compatible, so it reuses the existing forced-tool structured
  output (`{subject, body}`). It also supports `temperature=0` + a `seed` for
  reproducibility, which keeps the emails as deterministic as is practical.

### Defense in depth: three independent reasons this is safe here

1. **Synthetic data.** The system runs entirely on generated, non-real
   applicants (ADR 001; `generate_data` seeds fictional `example.com`
   customers). There is no real client PII in the repo, so even in the worst
   case nothing personal leaves the box.
2. **Minimised prompt surface.** The email prompt already sends only anonymised
   feature summaries and model scores, never raw PII (see
   `docs/compliance/australia.md`, APP 11).
3. **Audited disclosure.** Every cloud call is logged to `APICallLog` with PII
   categories and `destination_country` for the Privacy Act APP 8 cross-border
   audit. The Groq backend logs `provider="groq"`.

### Architecture

- A thin adapter, `GroqLLMClient`
  (`backend/apps/email_engine/services/llm_client.py`), duck-types
  `anthropic.Anthropic` (`.messages.create(**kwargs)`). It translates the
  Anthropic-shaped request (forced `submit_email` tool → OpenAI function calling,
  injects `temperature=0` + `seed`) and normalises the OpenAI response back into
  the shape the caller already reads. It raises `anthropic.RateLimitError` on
  HTTP 429 so the existing retry seam is reused. It also emits a text block
  alongside the tool block, so the existing text-parse fallback covers a
  malformed tool call (smaller models are less reliable at forced tool use).
- The backend is selected by `EMAIL_LLM_BACKEND` (`anthropic` default | `groq`),
  with `EMAIL_LLM_MODEL`, `EMAIL_LLM_SEED`, `GROQ_API_KEY`, `GROQ_BASE_URL`.
- Everything else is unchanged. The free model still goes through the same
  `$5/day` budget guard (ADR 006), the same 18-check guardrail battery, the same
  retry loop and, most importantly, the same deterministic template fallback
  when no key is set or the call fails. The adapter is built on `httpx`, which
  is already a dependency, so the swap adds no new packages.
- Bias detection deliberately stays on the deterministic rules. The free model
  writes prose and is not put in charge of the safety-critical compliance gate
  (ADR 003). That keeps the safety floor auditable and independent of the model.

### Update (2026-06-10): a local Ollama backend

End-to-end testing of the Groq backend with a real key hit a hard limit. Groq's
free tier caps at 6,000 tokens/min, but the compliance email prompts are ~9k
tokens (they embed the full verbatim template), so every email returned HTTP
413. Free Groq therefore can't be used for these prompts. A local Ollama
backend was added because local inference has no per-minute token cap and the
data never leaves the host.

- The adapter was generalized to `OpenAICompatibleLLMClient` (with a
  `GroqLLMClient` back-compat alias). Groq and Ollama share one client and
  differ only in `base_url`, `model`, auth, and `provider`.
- It is selected by `EMAIL_LLM_BACKEND=ollama` (`OLLAMA_BASE_URL`,
  `OLLAMA_MODEL`, and a dummy `OLLAMA_API_KEY`, since Ollama ignores auth). The
  `ollama` service is an opt-in compose profile. If it isn't running, the email
  path degrades to the template (a connection error → `EmailBackendError` →
  fallback), so the default stack is unaffected.
- **Context window:** Ollama's OpenAI `/v1` endpoint cannot set `num_ctx` per
  request, so the 16k window is baked into a Modelfile (`ollama/Modelfile`,
  built as the `loan-email` model by the `ollama-init` service). Without it, the
  default 4k context would silently truncate the 9k prompt.
- **Forced tool calls:** Ollama's `/v1` ignores `tool_choice`, so a small local
  model may answer in plain text. The adapter's text block and the existing
  text-parse / guardrail / template-fallback chain cover that case.
- **APP 8 correctness:** local inference is on-prem (Australia), so it is not a
  cross-border disclosure. `destination_country` is now derived per provider
  (`ollama` → `AU`; `anthropic`/`groq` → `US`). It was previously hardcoded to
  `"US"`, which would have logged a false cross-border record for local
  inference.

## Consequences

### Positive

- The email writer can run at $0 with no key rotation and no rate-limit risk to
  the demo. The decision path stays deterministic and free either way.
- The data-safety reasoning is explicit and defensible: the email writer is
  free, but not at the cost of a third party training on borrower data.
- It is provider-agnostic by construction. Moving real production to a no-train
  paid tier or a local/self-hosted model is a config change, not a rewrite.

### Negative

- `llama-3.1-8b-instant` is weaker than Claude at forced tool calls and exact
  figure reproduction. The guardrail + retry + template-fallback chain absorbs
  this, but more emails may fall back or retry than on Claude.
- Groq's `seed` is best-effort, so reproducibility is "near-identical," not
  bitwise. That is acceptable given temperature 0 and the constrained prompt.
- Two providers' response shapes have to be kept in parity (mitigated by the
  adapter and its unit tests).
- The local Ollama backend is slow on CPU (~20-60s per email, mostly prompt
  ingestion) and heavy (~5GB model + ~8GB-RAM container). A small local model
  also trips the structured-output guardrails more often, which means more
  template fallbacks. It is an opt-in capability, not the recommended default
  over templates for a demo.

### Production note

For a real deployment with real borrowers, Groq's free tier is not the endpoint
to use. Switch the same toggle to a no-train paid tier or a self-hosted model.
The free Groq backend is for the synthetic-data demo, where the data-safety
argument above holds.
