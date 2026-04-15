# Australian Privacy Principles (APP) — Compliance Matrix

**Last reviewed:** 2026-04-15
**Next review due:** 2026-10-15
**Scope:** This project's codebase as of `master` HEAD. This is an observational map, not legal advice.

| APP | Principle | Coverage | Code pointer | Gap |
|-----|-----------|----------|--------------|-----|
| 1 | Open and transparent management of personal information | Covered | `frontend/src/app/rights/page.tsx` — privacy section; this document | None known |
| 2 | Anonymity and pseudonymity | Partial | `apps/ml_engine` quote endpoint allows unauthenticated rate estimates | Anonymous full-application flow not supported; authentication is required to submit |
| 3 | Collection of solicited personal information | Covered | `apps/loans/models.py`, `apps/accounts/models.py`; purposes documented in `/rights` | None known |
| 4 | Dealing with unsolicited personal information | Partial | No inbound unsolicited-data channel beyond support email | Policy for destroy/de-identify is not yet formalised |
| 5 | Notification of collection | Covered | Application flow shows privacy-collection notice at form start; `/rights` details use | Notification at the time of collection relies on the frontend; server-side receipt audit could be stronger |
| 6 | Use or disclosure of personal information | Covered | `apps/ml_engine.services.pii_masking`, field-level encryption (`FIELD_ENCRYPTION_KEY`) | Disclosure register not yet published as a doc |
| 7 | Direct marketing | Covered | `apps/email_engine.services.lifecycle` honours opt-out; `BiasScoreBadge` gates marketing emails | Preference-centre UI not exposed to customers; opt-out is email-link-based only |
| 8 | Cross-border disclosure | Partial | Infra choices (Fly.io `primary_region=syd`, AU-region Vercel) minimise transfer | Any third-party call (Claude API, credit-bureau stub) crosses borders; documented but no contractual clause list yet |
| 9 | Adoption, use or disclosure of government related identifiers | Covered | No TFN collected; no Medicare collected; identity verification uses licence/passport per KYC flow | None known |
| 10 | Quality of personal information | Covered | `apps/accounts.services.address_service` validates; loan-app validation via Zod | No scheduled data-refresh job for long-lived records |
| 11 | Security of personal information | Covered | Field-level encryption, TLS, Argon2 password hashing, Sentry (PII scrubber on), CSP, gitleaks, ZAP DAST in CI | Penetration-test report not published; bug bounty programme absent |
| 12 | Access to personal information | Partial | Customer profile endpoint exposes own data (`/api/v1/accounts/me/`) | Formal "subject access request" workflow and SLA not documented |
| 13 | Correction of personal information | Partial | Customer can edit profile fields | No explicit "request correction of inferred data" flow for model outputs |

## Legend

- **Covered** — implementation present and tested; gap column lists any residual concern for completeness.
- **Partial** — a meaningful implementation exists but is not comprehensive; the gap column lists the specific residual work.
- **Not covered** — would appear as "No" in Coverage. None at this review.

## Related documents

- `docs/security/threat-model.md`
- `frontend/src/app/rights/page.tsx`
- ADR-0001 (WAT framework boundary) — regulatory inquiries flow via workflows
