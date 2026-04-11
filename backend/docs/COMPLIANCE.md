# Compliance Mapping

This document is an **index**, not an encyclopedia. It maps the regulations the system was designed against to the specific code, tests, or documents that implement them. Deep rationales live in [MODEL_CARD.md](MODEL_CARD.md), the [ADRs](adr/), and [SECURITY.md](SECURITY.md) — this file links out rather than repeating them.

It is a best-effort mapping for a portfolio project. None of it has been reviewed by a compliance professional.

## Quick reference

| Regulation | Status | Obligation | Where it lives |
|---|---|---|---|
| APRA CPG 235 — Model risk management | Active | Directional consistency, governance, data quality, drift monitoring | [ADR-002](adr/002-xgboost-with-monotonic-constraints.md) (monotonic constraints); [MODEL_CARD.md](MODEL_CARD.md) (governance); [`drift_monitor.py`](../apps/ml_engine/services/drift_monitor.py) (PSI/CSI) |
| APRA CPS 230 — Operational resilience | Active (eff. Jul 2025) | Critical-service mapping, third-party AI risk, business continuity | [SECURITY.md](SECURITY.md) (third-party AI governance); [ADR-006](adr/006-template-first-email-with-cost-cap.md) (template fallback); healthchecks on all 8 core services |
| NCCP Act 2009 — Responsible lending | Active | Reasonable inquiries, serviceability assessment, affordability | [MODEL_CARD.md](MODEL_CARD.md) (HEM benchmarks, APRA buffer rate, income shading); [`underwriting_engine.py`](../apps/ml_engine/services/underwriting_engine.py) |
| ASIC RG 209 — Responsible lending conduct | Active | Decision transparency, adverse action reasons | [MODEL_CARD.md](MODEL_CARD.md) (reason code section); [`adverse_action.py`](../apps/ml_engine/services/adverse_action.py) |
| CFPB Circular 2022-03 — Adverse action under complex algorithms | Active (US reference) | Specific reasons, not broad-bucket codes | [`adverse_action.py`](../apps/ml_engine/services/adverse_action.py) — top-4 SHAP reasons + counterfactuals; R01–R20 code map in [MODEL_CARD.md](MODEL_CARD.md) |
| EEOC 4/5 rule — Disparate impact | Active (US reference) | Monitor fairness across protected attributes | [MODEL_CARD.md](MODEL_CARD.md) fairness section; `ML_FAIRNESS_TARGET_DI = 0.80` in [`base.py`](../config/settings/base.py); fairness reweighting in [`trainer.py`](../apps/ml_engine/services/trainer.py) |
| Privacy Act 1988 — Automated decision disclosure | **Pending (Dec 10, 2026)** | Disclose auto-decision use, personal info categories, human review mechanism | [SECURITY.md](SECURITY.md) — deadline tracked. **Gaps flagged below.** |
| EU AI Act Annex III — High-risk credit scoring | **Pending (Aug 2, 2026)** | Bias detection, explainability, governance, documentation | [MODEL_CARD.md](MODEL_CARD.md) + [SECURITY.md](SECURITY.md); only relevant if serving EU customers |
| Racial / Sex / Age Discrimination Acts | Active | No discriminatory customer communication | [ADR-003](adr/003-hybrid-bias-detection.md) — three-layer bias detection on generated emails |
| Banking Code of Practice 2025 | Active | Plain-English decision explanations, hardship signposting | Guardrail layer in [`email_engine/`](../apps/email_engine/); 10 deterministic checks before any LLM email ships |
| AML/CTF Act 2006 | Active | KYC, ongoing due diligence, 7-year retention | `KYCVerification` model; soft-delete retention; Fernet field-level PII encryption (see [ADR-008](adr/008-security-architecture.md)) |

## Implementation notes

The five areas below are where compliance shapes day-to-day code decisions. Each links to the primary artefact; read those for detail.

### Responsible lending → monotonic constraints

APRA CPG 235 and ASIC RG 209 both expect models to behave in a way that is *directionally consistent with economic intuition*: more income should never raise default probability, more prior defaults should never reduce it. XGBoost supports this via per-feature monotonic constraints. Thirty-three features in the model are constrained. The rationale, the feature-by-feature direction choices, and the training-time consequence (slight AUC drag in exchange for regulator-friendly behaviour) are in [ADR-002](adr/002-xgboost-with-monotonic-constraints.md).

### Adverse action → SHAP reason codes

The NCCP Act (AU), Banking Code of Practice, and CFPB Circular 2022-03 (referenced for the US practice) all require decision explanations that are *specific* — not "credit history", but "three credit enquiries in the last six months, two above your historical monthly average". The system uses SHAP values from the uncalibrated XGBoost model, ranks per-feature contributions for the denied applicant, and maps the top four to plain-English reason codes (R01–R20). Counterfactuals (e.g. "reapply once your DTI is below 40%") are generated alongside. The full reason-code catalogue and SHAP stability caveat live in [MODEL_CARD.md](MODEL_CARD.md); implementation is in [`adverse_action.py`](../apps/ml_engine/services/adverse_action.py) and the SHAP → reason mapping in [`email_generator.py`](../apps/email_engine/services/email_generator.py).

### Fairness → disparate impact gates

The EEOC 4/5 rule (0.80 disparate impact ratio floor) is the industry-standard fairness threshold. Training runs evaluate disparate impact across `employment_type`, `applicant_type`, and `state`, and apply fairness reweighting if the ratio drops below the target. The threshold is configurable via `ML_FAIRNESS_TARGET_DI` in [`base.py`](../config/settings/base.py). Intersectional testing (combinations of protected attributes) is documented in [MODEL_CARD.md](MODEL_CARD.md).

### Communication bias → three-layer detection

Fairness in the *model* is not the same as fairness in the *communication*. Even a perfectly calibrated model can ship discriminatory-sounding denial letters if the LLM drifts. [ADR-003](adr/003-hybrid-bias-detection.md) describes the three-layer pipeline: deterministic regex against a banned-phrase list, then a contextual LLM review for tone, then human escalation for anything the LLM is unsure about. The thresholds, escalation routing, and cost model are all in the ADR.

### Third-party AI governance → APRA CPS 230

CPS 230 treats third-party AI providers as a critical operational dependency that must survive provider outages, spend overruns, and reputational incidents. The system implements this with a daily spend cap ($5/day in [ADR-006](adr/006-template-first-email-with-cost-cap.md)), a template-first strategy so the happy path does not depend on Claude at all, and circuit-breaker behaviour when the Anthropic API errors. [SECURITY.md](SECURITY.md) has the third-party AI section.

## Known gaps against pending deadlines

### Privacy Act automated decision disclosure (effective 10 December 2026)

The Privacy Act reforms require organisations using automated decision-making to disclose that use, the kinds of personal information involved, and the availability of human review. [SECURITY.md](SECURITY.md) tracks the deadline. Current gaps in *this* codebase against that obligation:

- No public privacy policy artefact (this is a portfolio project, not a customer-facing service)
- Human review mechanism exists (bias-detection escalation) but is not surfaced to the applicant in the email template
- The privacy policy template would need to list: credit score, income, employment, asset data, credit bureau data, behavioural signals — all categories the current model consumes

A production deployment would need: a privacy policy section, an opt-out mechanism for fully-automated decisions, and a review-request endpoint. None of those exist today. They are not hard to add — they are simply out of scope for a portfolio project.

### EU AI Act Annex III (effective 2 August 2026)

Credit scoring is explicitly Annex III (high-risk). The documentation, fairness, and explainability obligations are *already mostly met* by this project (model card, SHAP reasons, monotonic constraints, fairness gates). Two things would still need to be done before serving EU customers: a conformity self-assessment and a public-facing algorithmic transparency statement. Again, out of scope for a portfolio build, but not blocked by the architecture.

## What this system deliberately does not cover

- Real credit bureau data — the system is trained on synthetic data calibrated against APRA/ABS/ATO/Equifax statistics. See the Limitations section in the root [README](../../README.md).
- Post-origination monitoring and collections — the scope ends at the approval decision.
- Broker channel conduct — all applicants come through the "direct" channel.
- Hardship assistance workflows — signposted in denial letters but not implemented as a separate flow.
- APRA stress testing integration — the model has an internal +3% rate buffer, but there is no pipeline to ingest official APRA scenarios.

## Maintenance

When the referenced regulations or deadlines change, update in this order:

1. This file (quick-reference table)
2. [SECURITY.md](SECURITY.md) if the change affects data handling or AI governance
3. [MODEL_CARD.md](MODEL_CARD.md) if the change affects model-level obligations
4. The relevant ADR if the change affects an architectural decision

Do not duplicate content across those four files — cross-link instead.
