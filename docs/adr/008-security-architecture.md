# ADR 008: Security architecture

## Status

Accepted

## Date

2026-04-01

## Context

The system handles sensitive personal and financial information (income, credit scores, employment details, credit report data). Australian Privacy Act obligations and APRA prudential standards require defence-in-depth security controls. The system also accepts user-provided text that goes into LLM prompts, which creates a prompt injection risk.

## Decision

Implement a layered security architecture covering authentication, encryption, input sanitisation, and rate limiting.

### Authentication and authorisation

- **JWT with HttpOnly cookies:** access tokens (60-minute expiry) and refresh tokens (7-day expiry) are stored in HttpOnly, Secure, SameSite=Lax cookies. No tokens go in localStorage, which eliminates XSS token theft.
- **Refresh token rotation:** each refresh issues a new refresh token and blacklists the previous one. Token reuse is detected as a compromise signal.
- **Role-based access control (RBAC):** three roles (`admin`, `officer`, `customer`) with object-level permissions. Customers see only their own applications, officers see all applications, and admins have full access including deletion.
- **Two-factor authentication:** OTP-based 2FA for admin and officer accounts. Customers can optionally enable it.

### Encryption

- **Field-level encryption:** Fernet symmetric encryption for sensitive fields stored at rest. Encryption keys are managed through environment variables and never committed to source control.
- **Transport encryption:** HTTPS is enforced in production through Django's `SECURE_SSL_REDIRECT` and HSTS headers.
- **Password hashing:** Argon2id (memory-hard, resistant to GPU attacks) is the primary hasher, with PBKDF2 as a fallback for legacy compatibility.

### Input sanitisation and prompt security

- **Prompt injection defence:** all user-provided text that enters an LLM prompt passes through a sanitisation layer that strips control characters, excessive whitespace, and known injection patterns. Input is treated as data, not instructions.
- **Content Security Policy:** strict CSP headers block inline scripts and restrict resource loading to whitelisted origins.
- **CSRF protection:** Django's CSRF middleware, with an Axios interceptor injecting the token on all mutating requests.

### Rate limiting

Rate limits are tiered by endpoint sensitivity:

| Tier | Limit | Endpoints |
|------|-------|-----------|
| Auth | 20/min | Login, register, token refresh |
| Standard | 60/min | Application CRUD, status queries |
| Heavy | 10/min | ML prediction, email generation, pipeline orchestration |

### Audit logging

All significant actions (application creation, status changes, model predictions, email sends, pipeline runs) are recorded in `AuditLog` with the user, timestamp, IP address, and action details. Pattern-based filters mask PII in log output for Australian TFNs, Medicare numbers, phone numbers, and email addresses.

## Consequences

### Positive

- Defence in depth: compromising any single layer does not expose the full system.
- JWT in HttpOnly cookies eliminates the most common frontend token theft vector.
- The audit trail supports regulatory compliance requirements (APRA CPG 234, Privacy Act).
- Rate limiting protects the expensive ML and LLM endpoints against abuse.

### Negative

- Fernet encryption adds latency to field reads and writes, which is acceptable at this application's throughput.
- JWT blacklisting requires Redis, an extra infrastructure dependency (though Redis is already present for Celery).
- A strict CSP can break third-party integrations unless it is configured carefully.
- Rotating Fernet keys requires a re-encryption migration, which adds operational complexity.
