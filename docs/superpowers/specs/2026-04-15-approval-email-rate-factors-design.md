# Approval Email Rate Factors — Design

**Date:** 2026-04-15
**Source:** Sub-project A research — Plenti, Alex Bank, MoneyMe all surface positive rate drivers in their approval / personalised-rate disclosures.
**Out of scope:** Pricing calculation, denial path, quantitative disclosures, new emails.

## Goal

Approved loan emails name the 2–3 top factors that drove the approved rate, in qualitative terms. Mirror of the denial-email policy-reason work committed earlier this session (`47c3809`).

## Architecture

- New `_format_approval_factors(shap_values, feature_importances)` helper in `email_generator.py`, mirror of `_format_denial_reasons`.
- New `APPROVAL_FACTOR_MAP` constant mapping feature name → positive phrase (e.g. `"credit_score": "strong credit history"`).
- `APPROVAL_EMAIL_PROMPT` in `prompts.py` gains an `{approval_factors}` placeholder.
- Fallback `generate_approval_template` accepts `approval_factors` and includes it in the plain-text template.
- Both call sites in `email_generator.py` pass `decision.shap_values` / `decision.feature_importances` through.

## Rules

- Pick features with **positive** SHAP contribution (pushed toward approval). Rank by absolute magnitude. Take top 3.
- If no SHAP values, fall back to feature_importances (top 3 by weight).
- If both are empty, return empty string — prompt is instructed to naturally omit the sentence.
- Unknown feature names map to `"an aspect of your financial profile"`.

## Graceful degradation

Approval emails generated before this change have no `approval_factors` context key. The prompt's existing structure stays valid when the placeholder is empty.

## Tests

1. Positive SHAP on `credit_score` + `employment_length` → output includes both mapped phrases
2. Empty SHAP and empty feature_importances → empty factors string
3. All SHAP negative (borderline approval) → empty factors string
4. Unknown feature name → falls back to generic phrase
5. Existing approval-email tests continue to pass (regression check)

## Deliverables

- Modify: `backend/apps/email_engine/services/email_generator.py` (helper + map + 2 call sites)
- Modify: `backend/apps/email_engine/services/prompts.py` (add `{approval_factors}` placeholder)
- Modify: `backend/apps/email_engine/services/template_fallback.py` (extend `generate_approval_template`)
- Create: `backend/tests/test_approval_reasons_factors.py` (4 unit tests)
