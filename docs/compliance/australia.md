# Australian lending compliance

This document describes how the Loan Approval AI System meets Australian regulatory obligations. It is engineering documentation, not legal advice. Production deployment requires sign-off from a licensed Credit Representative and a Privacy Impact Assessment.

## Regulatory frame

| Regime | Scope | Primary obligations reflected in this system |
|--------|-------|---------------------------------------------|
| National Consumer Credit Protection Act 2009 (NCCP) + National Credit Code | Consumer credit | Responsible lending, not-unsuitable assessment, decision audit trail |
| Privacy Act 1988 + Australian Privacy Principles (APPs) | Personal information | Collection notice, use/disclosure limits, retention, security, access/correction |
| Banking Code of Practice (ABA) | ADI members | Plain-English disclosure, hardship handling, denial reason transparency |
| Anti-Money Laundering / CTF Act 2006 | Designated services | Record retention (s 107, s 112); customer account-opening flows not in scope |
| APRA CPG 235 | Data risk management | Prediction log audit trail for model-governance review |

## Responsible lending (NCCP s128 to s131)

The Act requires the lender to make reasonable inquiries into the consumer's requirements, objectives, and financial situation, and to make an assessment that the credit contract is **not unsuitable** before offering or increasing credit.

**How the system reflects this:**

1. **Required inputs.** The `Application` model (`backend/apps/loans/models.py`) captures income, living expenses, existing liabilities, loan purpose, term and amount.

2. **Serviceability calculation.** The calculation applies the APRA 3% rate buffer when computing DTI and the stress-tested monthly repayment. `test_apra_calibration.py` is the regression suite.

3. **Assessment record.** Every decision persists the model version and probability, top SHAP factors, guardrail results, bias pre-screen outcome, final decision, timestamp and operator context. The `AuditLog` model in `backend/apps/loans/models.py` implements this, and `backend/tests/test_audit_fixes.py` exercises it.

4. **Retention.** `python manage.py enforce_retention` (scheduled weekly by Celery beat in `backend/config/celery.py`) implements the retention policy documented in the command header:

   | Data type | Retention | Regulation |
   |-----------|-----------|-----------|
   | Loan applications, audit logs, KYC records, emails, bias reports | 7 years | AML/CTF Act s 107 / s 112, NCCP Act s 174 |
   | Prediction logs | 5 years | APRA CPG 235 |
   | Drift reports | 3 years | Internal governance policy |
   | Soft-deleted records | 90 days | Privacy Act APP 11.2 |

   See `backend/apps/loans/management/commands/enforce_retention.py`.

## Privacy Act / APPs

**APP 1 (open and transparent management):** A Privacy Policy is exposed on the frontend and linked from every data-collection form.

**APP 3 (collection of solicited PI):** The system collects only the data needed for the serviceability assessment. It collects no biometric, health, or political data.

**APP 5 (notification of collection):** Before the first PII field is enabled, the application form shows a collection notice covering identity, purpose, required/optional fields, and withdrawal options.

**APP 6 (use or disclosure):** PII is used only for credit assessment. It is not sold, shared with third parties, or used for marketing without a separate consent flag (currently disabled).

**APP 11 (security of PI):**

- **At rest:** PII fields (TFN, bank account details, income, DoB) are encrypted at the field level with Fernet using `FIELD_ENCRYPTION_KEY`. This is implemented in `backend/apps/accounts/fields.py` and migrations `0007_encrypt_existing_pii.py` and `0009_encrypt_income_dob_fields.py`. Keys are rotated with `python manage.py rotate_encryption_key` (`backend/apps/accounts/management/commands/rotate_encryption_key.py`).
- **In transit:** HTTPS is enforced in production via `SECURE_SSL_REDIRECT=True` and HSTS (see `backend/config/settings/production.py`).
- **In logs:** PII is redacted before log records reach any sink. This is implemented in `backend/config/logging_filters.py`, with a regression test in `backend/tests/test_pii_masking.py`.
- **In prompts to the email LLM:** The email generator sends only anonymised feature summaries, so no raw PII reaches the LLM. The only identifiers in a prompt are the internal `Application.id` and model scores; `backend/apps/email_engine/services/prompts.py` enforces the prompt shape. The backend is selectable (`EMAIL_LLM_BACKEND`). Claude is the default. The optional free Groq backend was chosen specifically because its free tier does not train on prompts (ADR 010), and free tiers that train on prompts are excluded. Cross-border disclosure (APP 8) is audited per call in `APICallLog` (`provider`, `destination_country`).

**APP 12 (access):** Customers can export their data. `backend/tests/test_data_export.py` covers this.

**APP 13 (correction):** Customers can request correction via the account profile endpoint.

## Denial-reason transparency (Banking Code of Practice)

Denial emails generated by `email_engine` include:

- Plain-English top factors driving the decision (SHAP importances translated through the guardrail's approved vocabulary).
- Next steps (review, reapply, contact channels).

They contain **no prohibited apology / disappointment / "sorry" language**. The guardrail rule set in `backend/apps/email_engine/services/` enforces this, and `backend/tests/test_guardrails.py` and `backend/tests/test_guardrails_comprehensive.py` regression-test it.

## Out of scope for this system

- **AFSL / ACL obligations.** Assumed to be held by the deploying organisation.
- **Credit reporting to bureaus.** Integrations with Equifax / illion are not implemented.
- **AML/CTF account opening.** The system processes applications, not deposit accounts. Record-keeping obligations under s 107 / s 112 apply to loan records and are reflected in the retention policy.
- **Hardship assistance portal.** An intake path exists; workflow handover to a Credit Representative is manual.

## Verification

| Obligation | Verified by |
|-----------|-------------|
| Audit trail on every decision | `backend/tests/test_audit_fixes.py` |
| PII encryption at rest | `backend/tests/test_security.py` |
| PII redaction in logs | `backend/tests/test_pii_masking.py` |
| No apology / prohibited language in denials | `backend/tests/test_guardrails.py`, `backend/tests/test_guardrails_comprehensive.py` |
| Retention policy implementation | `backend/apps/loans/management/commands/enforce_retention.py` (follow-up: add a `test_retention_command.py` regression) |
| Australian fixtures / stress test | `backend/tests/test_australian_compliance.py`, `backend/tests/test_apra_calibration.py` |

## Review cadence

Reviewed annually or on regulatory change. Last reviewed: 2026-04-17. Next review due: 2027-04-17.
