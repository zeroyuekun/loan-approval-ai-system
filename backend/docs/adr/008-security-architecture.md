# ADR 008: Security Architecture

## Status

Accepted

## Date

2026-04-01

## Context

The loan approval system handles sensitive personal and financial information (income, credit scores, employment details, credit report data). Australian Privacy Act obligations and APRA prudential standards require defence-in-depth security controls. The system also accepts user-provided text that enters LLM prompts, creating prompt injection risk.

## Decision

Implement a layered security architecture covering authentication, encryption, input sanitisation, and rate limiting.

### Authentication and Authorisation

- **JWT with HttpOnly cookies:** Access tokens (60-minute expiry) and refresh tokens (7-day expiry) stored in HttpOnly, Secure, SameSite=Lax cookies. No tokens in localStorage — eliminates XSS token theft.
- **Refresh token rotation:** Each refresh generates a new refresh token and blacklists the previous one. Detects token reuse as a compromise signal.
- **Role-based access control (RBAC):** Three roles — `admin`, `officer`, `customer` — with object-level permissions. Customers see only their own applications; officers see all applications; admins have full access including deletion.
- **Two-factor authentication:** OTP-based 2FA for admin and officer accounts. Customers can optionally enable it.

### Encryption

- **Field-level encryption:** Fernet symmetric encryption for sensitive fields stored at rest. Encryption keys managed via environment variables, never committed to source control.
- **Transport encryption:** HTTPS enforced in production via Django's `SECURE_SSL_REDIRECT` and HSTS headers.
- **Password hashing:** Argon2id (memory-hard, resistant to GPU attacks) as the primary hasher, with PBKDF2 as fallback for legacy compatibility.

### Input Sanitisation and Prompt Security

- **Prompt injection defence:** All user-provided text entering LLM prompts passes through a sanitisation layer that strips control characters, excessive whitespace, and known injection patterns. Input is treated as data, not instructions.
- **Content Security Policy:** Strict CSP headers prevent inline scripts, restricting resource loading to whitelisted origins.
- **CSRF protection:** Django's CSRF middleware with token injection on all mutating requests via Axios interceptor.

### Rate Limiting

Tiered rate limiting based on endpoint sensitivity:

| Tier | Limit | Endpoints |
|------|-------|-----------|
| Auth | 20/min | Login, register, token refresh |
| Standard | 60/min | Application CRUD, status queries |
| Heavy | 10/min | ML prediction, email generation, pipeline orchestration |

### Audit Logging

All significant actions (application creation, status changes, model predictions, email sends, pipeline runs) are recorded in `AuditLog` with user, timestamp, IP address, and action details. PII is masked in log output using pattern-based filters for Australian TFN, Medicare numbers, phone numbers, and email addresses.

## Consequences

### Positive

- Defence in depth — compromise of any single layer does not expose the full system
- JWT in HttpOnly cookies eliminates the most common frontend token theft vector
- Audit trail supports regulatory compliance requirements (APRA CPG 234, Privacy Act)
- Rate limiting protects against abuse of expensive ML and LLM endpoints

### Negative

- Fernet encryption adds latency to field reads/writes — acceptable for this application's throughput
- JWT blacklisting requires Redis — adds an infrastructure dependency (already present for Celery)
- Strict CSP can break third-party integrations if not carefully configured
- Key rotation for Fernet requires a re-encryption migration — operational complexity
