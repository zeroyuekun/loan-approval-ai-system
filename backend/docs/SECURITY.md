# Security policy

## Reporting security issues

Report security vulnerabilities by emailing **security@aussieloanai.dev** with a description of the issue, steps to reproduce, and any relevant logs or screenshots.

- Acknowledgment: within 72 hours
- Initial assessment: within 5 business days
- Resolution target: critical issues within 14 days, others within 30 days

Do not open public GitHub issues for security vulnerabilities. Use responsible disclosure and allow time for a fix before any public discussion.

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes (active development, receives all security patches) |
| < 0.1   | No        |

## Security controls in place

### Authentication and access control

- JWT tokens stored in HttpOnly cookies (not localStorage) with `SameSite=Lax` and `Secure` flag in production
- CSRF protection enabled with trusted origins locked to the frontend
- Passwords hashed with Argon2 (PBKDF2 fallback)
- Three roles (admin, officer, customer) with permission checks on every endpoint
- Token rotation: 60-minute access tokens, 7-day refresh tokens with rotation and blacklisting
- Progressive account lockout: 1 min, 5 min, 30 min, 1440 min after consecutive failed logins

### Rate limiting

- Anonymous: 20 requests/min
- Authenticated: 60 requests/min
- Pipeline orchestration: 60 requests/hour

### Encryption

- At rest: field-level Fernet encryption for PII (date of birth, identity document numbers)
- In transit: TLS enforced in production via HSTS (1 year, includeSubDomains, preload) and `SECURE_SSL_REDIRECT`

### Static analysis and dependency auditing

- Bandit SAST scan runs on every push and pull request in CI
- pip-audit checks Python dependencies for known vulnerabilities in CI
- npm audit checks frontend dependencies for known vulnerabilities in CI

### Additional headers

- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- CORS locked to configured frontend origins only

## Data handling

- All secrets are stored in `.env` at the project root and never committed to version control
- PII fields encrypted at rest with Fernet symmetric encryption
- Customer identity fields (name, DOB, ID numbers) are locked after initial submission under AML/CTF Act 2006
- ID numbers are masked in the frontend UI
- Prompt injection defences applied to all user-supplied text entering LLM prompts

## Scope

**In scope:** Backend API, authentication and authorisation, data handling and encryption, ML prediction pipeline, email generation guardrails, bias detection pipeline, CI security scans.

**Out of scope:** Third-party services (Anthropic API, Gmail SMTP), the underlying Docker/OS infrastructure, denial-of-service attacks against development environments, social engineering.

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
