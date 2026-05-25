# CDR / Open Banking adapter — foundation spec

**Date:** 2026-05-25
**Author:** Architecture review (Claude Opus 4.7) with Neville Zeng
**Status:** Draft — separate plan + multi-PR cycle when scheduled
**Source audit:** [2026-05-25 senior architect audit](2026-05-25-dashboard-persona-refit-design.md#audit-findings-that-motivated-this-spec-verified-2026-05-25)

---

## Problem statement

Australia's Consumer Data Right rollout for **non-bank lenders becomes mandatory in mid-2026**:

- **13 July 2026** — large non-bank lenders must share product data
- **9 November 2026** — initial providers must share consumer data (with consent)
- **10 May 2027** — large providers' consumer-data obligation begins

This system positions itself as "Australian lending" and uses CDR-flavoured features (e.g. `open_banking_transactions_*` in `LoanApplication`), but the actual integration is currently a sandbox adapter:

- `backend/apps/ml_engine/services/open_banking_service.py` (453 LOC) targets Adatree's CDR sandbox + the Open Bank Project. Real httpx calls, real keyword classification — but no production ADR (Accredited Data Recipient) registration, no real consent flow, no data-residency enforcement, no audit trail of consumer consent.
- `backend/apps/ml_engine/services/credit_bureau_service.py` (506 LOC) is similar: real Equifax/Experian sandbox adapter with one minor smell — uses `sandbox-us-api.experian.com` for an "Australian" lender (Experian AU has a different endpoint).

There's no customer-facing consent dialog, no data-minimisation disclosure aligned with APP 5 (Privacy Act), no replay-safe consent record, no kill-switch on revoked consent. The system would not survive an ASIC CDR compliance review.

## Goals

1. Define a clean `CDRAdapter` interface with pluggable backends (sandbox vs. production). The sandbox stays for local dev; production gets a real (or convincingly-scaffolded) ADR/DR flow.
2. Add a customer-facing CDR consent flow that's APP-5-aligned (collection notice, purpose, retention, withdrawal).
3. Add a tamper-evident consent record (which scopes, which timestamp, expiry, revocation events).
4. Wire CDR-derived features into the prediction pipeline with feature-level provenance (which feature came from which CDR data holder).
5. Add a kill-switch: if consent is revoked, the feature snapshot must be evictable.

## Non-goals

- Becoming a real registered ADR. That requires legal/regulatory engagement outside engineering scope. The "production" backend is a convincing scaffold (real OAuth2 dance, real DR flow shape, mock data holders) — not a live ASIC-accredited connection.
- Replacing the existing sandbox flow for local dev. That stays as the "Sandbox" backend.
- CDR product data sharing (the lender-side obligation). This spec focuses on consumer data consumption.
- Frontend redesign of the application form beyond adding the consent step.

## Target architecture

```
backend/apps/ml_engine/services/external/        # see decomposition spec
├── cdr/
│   ├── __init__.py
│   ├── adapter.py              # CDRAdapter ABC + factory
│   ├── sandbox.py              # Adatree sandbox + Open Bank Project — existing logic
│   ├── production.py           # OAuth2/DR flow scaffold (mock data holders)
│   ├── consent.py              # ConsentRecord ORM + lifecycle helpers
│   └── feature_provenance.py   # tags which features came from which DH
```

Two new Django models:

```python
class CDRConsent(models.Model):
    """Tamper-evident customer consent for CDR data sharing. One per
    (customer, data_holder, scope_set, granted_at) tuple."""
    customer = ForeignKey(User, on_delete=PROTECT)
    data_holder = CharField(50)              # e.g. "anz-au"
    scopes = JSONField()                     # ["accounts:read", "transactions:read", "balance:read"]
    granted_at = DateTimeField()
    expires_at = DateTimeField()             # ASIC: max 12 months
    revoked_at = DateTimeField(null=True)
    purpose = TextField()                    # APP 5: why we want it, in plain English
    retention_policy = JSONField()           # APP 11: how long, where
    hash_chain_prev = CharField(64)          # tamper-evidence (see security spec)
    hash_chain_self = CharField(64)


class CDRDataSnapshot(models.Model):
    """The actual CDR payload pulled under consent. Encrypted at rest.
    Evictable when consent revoked."""
    consent = ForeignKey(CDRConsent, on_delete=PROTECT)
    pulled_at = DateTimeField()
    raw_payload_enc = EncryptedTextField()   # Fernet-encrypted (see security spec for KMS)
    derived_features = JSONField()           # the OpenBankingProfile fields used by the model
    evicted_at = DateTimeField(null=True)
```

## PR sequencing (4 PRs)

| PR | Scope | Risk | Why |
|---|---|---|---|
| 1 | Extract `CDRAdapter` interface; refactor existing `open_banking_service.py` into sandbox backend; no behaviour change | Low | Establishes the interface boundary without touching consumers |
| 2 | Add `CDRConsent` + `CDRDataSnapshot` models, migrations, admin views | Medium | Net-new DB schema, needs careful migration testing on a populated DB |
| 3 | Customer-facing consent dialog on `/apply` (collection notice, scope selection, purpose, withdrawal link) + minimal admin revocation UI | Medium | First customer-facing UX in this work; requires careful copy |
| 4 | Wire CDR features into the prediction pipeline with provenance tagging; add the eviction flow on revocation | High | Touches the hot prediction path |

Each PR ships green:
- `pytest apps/ml_engine/` and the wider backend suite stay green at every commit.
- Frontend tests stay green.
- Migrations are reversible.

## Acceptance per PR

**PR-1 (interface):** `CDRAdapter` ABC exists; sandbox subclass passes all the existing behavioural tests for `open_banking_service`; no caller changes required (re-export shim handles old import paths).

**PR-2 (models):** Migrations apply forward and backward cleanly on a populated DB; admin can create/list/revoke `CDRConsent` rows.

**PR-3 (consent UX):** Customer-facing collection-notice page renders pre-form; consent is required (no skip-path) for CDR data fetching; a regression test verifies `CDRConsent` row is written on form submit with all required APP-5 fields populated; admin revocation UI deletes the corresponding `CDRDataSnapshot` rows.

**PR-4 (pipeline wiring):** A denied / approved decision now records which features came from CDR vs. user-input vs. credit bureau; revoking consent triggers eviction of the cached snapshot and forces a re-pull on next score.

## Compliance grounding

| Regime | Section | What this spec satisfies |
|---|---|---|
| Privacy Act | APP 1 — open management | Privacy policy linked from consent dialog |
| Privacy Act | APP 3 — collection of solicited PI | Only requested scopes ingested |
| Privacy Act | APP 5 — notification at collection | Consent dialog displays purpose + retention before granting |
| Privacy Act | APP 6 — use & disclosure | `derived_features` JSONField fixes what the data was used for |
| Privacy Act | APP 8 — cross-border disclosure | (Out of scope here — addressed in security spec via `APICallLog`) |
| Privacy Act | APP 11 — security of PI | Snapshot encrypted at rest (uses KMS abstraction from security spec) |
| Privacy Act | APP 12 — access | Customer can export consent history + derived features |
| Privacy Act | APP 13 — correction | Customer can revoke + re-grant |
| CDR Rules | Schedule 1 — consent | One consent per (DH, scope, time) tuple; 12-month max expiry |
| NCCP s128 | Reasonable inquiries | Pipeline marks which features were CDR-sourced |

## Risks

- **The "production" backend is a scaffold, not real ADR accreditation.** README + compliance docs MUST clearly say this. Otherwise it's misleading.
- **PII surface expansion.** CDR payloads include far more PII than the existing application form. Encryption + retention + audit are non-negotiable. Depends on the security gap-closure spec landing first (specifically: KMS abstraction + hash-chained audit log).
- **Migration on a populated DB.** New tables only, no schema changes to existing tables → low risk.
- **Customer trust UX.** A clumsy consent dialog kills the funnel. Mitigation: copy review before PR-3 lands.

## Dependencies on other foundation specs

- **`external/` subpackage exists** — see the [ml_engine decomposition spec](2026-05-25-ml-engine-decomposition-design.md). PR-1 of CDR work depends on PR-1 of decomposition landing first.
- **KMS abstraction + hash-chained audit log** — see the [security gap-closure spec](2026-05-25-security-gap-closure-design.md). PR-2 (consent model) uses the hash-chain; PR-4 (snapshot encryption) uses KMS-backed Fernet.

## What this lays foundation for

- A credible "this person understands Australian lending" signal for hirers — the CDR mandate is the single biggest regulatory shift in AU consumer finance in years.
- A future "production CDR enablement" turn that swaps the mock data holders for real ones, once the engineering organisation is ASIC-accredited.
- The pre-condition for actually selling the system to a non-bank lender after July 2026 — without CDR they can't legally operate at scale.
