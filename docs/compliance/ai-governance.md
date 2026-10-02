# AI regulation and LLM provider governance

This page covers regulatory deadlines that apply to automated credit decisions and the governance of the external LLM provider. The vulnerability disclosure policy and the list of security controls are in the root [SECURITY.md](../../SECURITY.md). The security design is in [ADR 008](../adr/008-security-architecture.md). Australian lending obligations are in [australia.md](australia.md).

## Upcoming regulatory deadlines

### Privacy Act 1988: automated decision disclosure (10 December 2026)
The Privacy and Other Legislation Amendment Act 2024 requires APP entities to disclose
in privacy policies where computer programs use personal information to make decisions
that could "significantly affect the rights or interests of an individual."

**Penalties:** Up to $50,000,000 for bodies corporate, or 3x benefit obtained, or 30%
of adjusted turnover (whichever is greater).

**Status:** This system's credit decisions are automated and will require disclosure.
The privacy policy must list the types of personal information used, the nature of the
automated decisions, and the mechanism for human review.

### EU AI Act: high-risk AI classification (2 August 2026)
Credit scoring is classified as high-risk AI under Annex III, Point 5(b) of
Regulation (EU) 2024/1689. Requirements include a risk management system, data
governance, technical documentation, record-keeping, transparency, human oversight,
and accuracy/robustness/cybersecurity.

**Status:** If the system serves EU customers, a conformity assessment is required by August 2026.

### ASIC REP 798: AI governance expectations (active)
ASIC's October 2024 report found nearly half of licensees lacked policies addressing
consumer fairness or algorithmic bias. Credit scoring AI was flagged as requiring
transparent, explainable governance arrangements.

**References:**
- Privacy Act amendments: legislation.gov.au/C2024A00128
- EU AI Act: eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=OJ:L_202401689
- ASIC REP 798: asic.gov.au (report published 29 October 2024)

## Third-party AI provider governance

This system uses an external LLM for email generation and bias analysis. The default
is Anthropic's Claude API; an optional free, OpenAI-compatible Groq backend can be
selected via `EMAIL_LLM_BACKEND` (see ADR 010). Under APRA CPS 230 (effective
1 July 2025), entities remain responsible for managing risks associated with service
providers.

**Controls in place:**
- API call budget limits ($5/day, 500 calls/day), applied to whichever backend is active
- Circuit breaker (3 failures -> 600s cooldown)
- Template fallback when the LLM is unavailable or no key is configured
- No customer PII is sent to the LLM, only anonymised financial context
- Audit logging of all LLM interactions, including `provider` and `destination_country` (APP 8)

**Provider-selection governance (ADR 010):** Groq was chosen as the free backend
because its free tier does **not** train on submitted prompts. Free tiers that do
train on prompts (e.g. Gemini/Mistral free) are deliberately excluded. The whole
system also runs on synthetic data, with no real borrower PII anywhere. The toggle,
budget guard, guardrails and template fallback form the same chain on every backend,
so moving real production to a no-train paid tier or a self-hosted model is a config
change.

CPS 230 is technology-agnostic and does not specifically mention AI/ML. Material
service providers still require formal agreements and monitoring.
