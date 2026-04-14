# ML Gap Coverage Audit

**Date:** 2026-04-14
**Source:** `docs/research/findings.json#/consolidated/gaps_in_our_model`
**Purpose:** Map each research-identified gap to either an existing field in the synthetic data generator or an explicit "deferred" decision.

## Why this document exists

Sub-project A's research report identified 9 "gaps in our model" based on a name-based comparison against the generator. A deeper semantic inspection of `backend/apps/ml_engine/services/data_generator.py` shows that most of those gaps are already covered in richer form than the research named them. This audit is the honest record.

## Coverage table

| Research gap | Status | Existing generator fields / Notes |
|---|---|---|
| `bnpl_balance` | **Covered** | `num_bnpl_accounts` (line 1149), `bnpl_active_count` (1165), `bnpl_total_limit` (1175), `bnpl_utilization_pct` (1176), `bnpl_late_payments_12m` (1177), `bnpl_monthly_commitment` (1178), plus derived `bnpl_to_income_ratio` (1230). |
| `savings_balance_months` | **Covered** | `savings_balance` (1152), `avg_monthly_savings_rate` (1155), `savings_trend_3m` (1161), plus derived `savings_to_loan_ratio` (1219). |
| `rhi_24_month_vector_or_on_time_late_counts` | **Covered** | `num_late_payments_24m` (1168) is the late-month count over a 24-month window. `on_time` is the complement (`24 - num_late_payments_24m`); adding it explicitly is redundant — the model can learn it from the existing feature. `worst_late_payment_days` (1169) adds severity. |
| `enquiries_last_6_months_windowed` | **Covered** | `num_credit_enquiries_6m` (1144) is already the 6-month windowed count. |
| `age_at_loan_maturity` | **Deferred** | Derivable from existing `age_proxy` + `loan_term_months`. Intended use is a **policy rule** (Alex Bank's 67-cap), not an ML feature. Belongs in the approval decisioning layer, not the data generator. |
| `visa_subclass_and_expiry_gap` | **Deferred** | Genuinely missing from the generator. Intended use is a **policy gate** (CBA's "visa must outlast loan term by ≥1 month"), not an ML feature. Low base rate in the non-citizen/non-PR applicant pool, and the research confirms citizen/PR is the dominant case. Revisit if/when non-citizen flows become a product focus. |
| `self_employed_trading_years` | **Partially covered** | `employment_type == "self_employed"` (line 48) and `employment_length` (line 610) exist separately. An explicit self-employed trading-years feature would be a derived field with the same information the model already receives via those two columns. Not worth adding. |
| `financial_hardship_flag` | **Covered** | `ccr_num_hardship_flags` (generated line ~975), reflects CCR FHI. Already exposed in the output. |
| `soft_pull_vs_hard_pull_indicator` | **Deferred** | Belongs to the **application flow**, not the data generator or model. Covered in sub-project C scope as a UX recommendation (add a soft-pull rate-quote endpoint). |

## Conclusion

- **6 of 9** research-identified gaps are already covered, most in richer form than the research named them.
- **2 of 9** (age-at-maturity, visa) are better modelled as deterministic policy rules than ML features, and are deferred.
- **1 of 9** (soft-pull indicator) belongs to the application-flow layer and is already queued as a sub-project C UX recommendation.

The generator does not need new features at this time. Sub-project B is closed without feature additions; the value delivered by the research phase was **confirming coverage**, not **exposing missing features**.

## Implications for downstream work

- **Sub-project B (ML):** No feature additions. No retraining triggered by gap analysis. Future ML work should target calibration, hyperparameter tuning, or policy-rule layer rather than synthetic-data feature expansion.
- **Sub-project C (code / UX):** UX recommendations in `docs/research/2026-04-14-au-lending-research.md` tagged `[→ C]` remain actionable and independent of this audit.
