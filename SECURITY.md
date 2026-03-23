# Security Policy

## Reporting Security Issues

Report security vulnerabilities by emailing **security@aussieloanai.dev** with a description of the issue, steps to reproduce, and any relevant logs or screenshots.

- **Acknowledgment:** within 72 hours
- **Initial assessment:** within 5 business days
- **Resolution target:** critical issues within 14 days, others within 30 days

Do not open public GitHub issues for security vulnerabilities. Use responsible disclosure and allow time for a fix before any public discussion.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes — active development, receives all security patches |
| < 0.1   | No        |

## Security Controls in Place

### Authentication and Access Control

- JWT tokens stored in **HttpOnly cookies** (not localStorage) with `SameSite=Lax` and `Secure` flag in production
- CSRF protection enabled with trusted origins locked to the frontend
- Passwords hashed with **Argon2** (PBKDF2 fallback)
- Three roles (admin, officer, customer) with permission checks on every endpoint
- Token rotation: 60-minute access tokens, 7-day refresh tokens with rotation and blacklisting
- Progressive account lockout: 1 min, 5 min, 30 min, 1440 min after consecutive failed logins

### Rate Limiting

- Anonymous: 20 requests/min
- Authenticated: 60 requests/min
- Pipeline orchestration: 60 requests/hour

### Encryption

- **At rest:** Field-level Fernet encryption for PII (date of birth, identity document numbers)
- **In transit:** TLS enforced in production via HSTS (1 year, includeSubDomains, preload) and `SECURE_SSL_REDIRECT`

### Static Analysis and Dependency Auditing

- **Bandit** SAST scan runs on every push and pull request in CI
- **pip-audit** checks Python dependencies for known vulnerabilities in CI
- **npm audit** checks frontend dependencies for known vulnerabilities in CI

### Additional Headers

- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- CORS locked to configured frontend origins only

## Data Handling

- All secrets stored in `.env` at the project root — never committed to version control
- PII fields encrypted at rest with Fernet symmetric encryption
- Customer identity fields (name, DOB, ID numbers) are locked after initial submission under AML/CTF Act 2006
- ID numbers are masked in the frontend UI
- Prompt injection defences applied to all user-supplied text entering LLM prompts

## Scope

**In scope:** Backend API, authentication and authorisation, data handling and encryption, ML prediction pipeline, email generation guardrails, bias detection pipeline, CI security scans.

**Out of scope:** Third-party services (Anthropic API, Gmail SMTP), the underlying Docker/OS infrastructure, denial-of-service attacks against development environments, social engineering.
