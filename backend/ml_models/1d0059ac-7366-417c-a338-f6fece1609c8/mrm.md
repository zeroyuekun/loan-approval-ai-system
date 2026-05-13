# Model Risk Management Dossier — `1d0059ac-7366-417c-a338-f6fece1609c8`
_Generated 2026-05-13T23:11:02Z — Format: APRA CPS 220 / SR 11-7_

## 1. Header

- **Model ID:** `1d0059ac-7366-417c-a338-f6fece1609c8`
- **Algorithm:** XGBoost
- **Version:** 20260507_152903
- **Segment:** `unified`
- **Trained at:** 2026-05-07T15:29:03.471260+00:00
- **Training duration:** unknowns
- **Training samples:** unknown
- **Class balance (positive rate):** unknown
- **Compliance status:** NON-COMPLIANT
  - Fairness 80%-rule fails on: employment_type, state
- **File hash (SHA-256):** `7f3f627dd40f8c0f1de88e5342717ef57a88f532dd0835c9377dd1e5c4dbf7be`

## 2. Purpose & limitations

General-purpose PD estimation across AU retail loan products. Not validated for: business lending, secured non-home lending, applicants outside AU residency, loans > $5M, loans with unusual repayment structures (balloon, interest-only > 5yr).

All scope boundaries above reflect the training distribution. The policy overlay runs in `enforce` mode in this deployment. Out-of-scope predictions are blocked by the overlay and routed to manual underwriter review (see §9 P-codes).

## 3. Data lineage

- **Source:** synthetic (DataGenerator v1 + GMSC real-data benchmark)
- **Synthetic vs real:** synthetic
- **Class balance (positive rate):** unknown
- **Reject-inference usage:** not applied
- **Temporal coverage:** unknown → unknown

Reject-inference is not applied for this version; the accept-only training distribution is a known bias risk and is mitigated through ongoing PSI monitoring (§10) + quarterly challenger retraining.

## 4. Monotonicity constraint table

| Feature | Sign | Rationale |
|---|---|---|
| `annual_income` | +1 (↑) | Higher income increases serviceability — core AU responsible-lending assumption. |
| `avg_monthly_savings_rate` | +1 (↑) | Positive savings rate demonstrates cash-flow surplus. |
| `consumer_confidence` | +1 (↑) | Higher macro confidence lowers tail-event probability during loan term. |
| `credit_history_months` | +1 (↑) | More history = thicker file; thin files penalised across AU bureaux. |
| `credit_score` | +1 (↑) | Higher Equifax score indicates lower historical default probability. |
| `debt_service_coverage` | +1 (↑) | DSCR > 1 means income covers repayments with buffer; linear in safety. |
| `deposit_amount` | +1 (↑) | Larger deposit reduces LVR and demonstrates savings discipline. |
| `deposit_ratio` | +1 (↑) | deposit / loan_amount — direct proxy for equity skin-in-the-game. |
| `document_consistency_score` | +1 (↑) | Consistent docs = lower fraud risk; monotone in data quality. |
| `employment_length` | +1 (↑) | Longer tenure proxies income stability; CBA/NAB scorecards apply length floors. |
| `financial_literacy_score` | +1 (↑) | Higher literacy = better decision making; TMD-aligned protective factor. |
| `has_cosigner` | +1 (↑) | Guarantor increases recovery pool; monotonically safer. |
| `hem_surplus` | +1 (↑) | Income − HEM floor; larger surplus = more serviceability headroom. |
| `income_per_dependant` | +1 (↑) | More income per dependant = more discretionary buffer. |
| `income_source_count` | +1 (↑) | Income diversification reduces concentration risk on a single employer. |
| `income_verification_score` | +1 (↑) | CDR/Basiq-confirmed income is strictly safer than self-attested. |
| `is_existing_customer` | +1 (↑) | Known customer behaviour is strictly more informative than acquired-unknown. |
| `log_annual_income` | +1 (↑) | Log transform of annual_income; monotone transform, same sign as source. |
| `months_since_last_default` | +1 (↑) | Longer since default = more recovery evidence; monotone in safety. |
| `net_monthly_surplus` | +1 (↑) | Income − expenses; foundational serviceability quantity. |
| `prepayment_buffer_months` | +1 (↑) | Months of repayments already paid ahead reduces imminent default risk. |
| `property_value` | +1 (↑) | Higher collateral value reduces LGD for secured lending (APS 112). |
| `rent_payment_regularity` | +1 (↑) | Consistent rent payments predict mortgage payment consistency. |
| `salary_credit_regularity` | +1 (↑) | Regular salary credits confirm employment reality, reduce income-fabrication risk. |
| `savings_balance` | +1 (↑) | Larger liquid buffer lowers short-term default risk during shocks. |
| `savings_to_loan_ratio` | +1 (↑) | More savings relative to loan = more shock-absorption capacity. |
| `serviceability_ratio` | +1 (↑) | Aggregated serviceability score; direction matches individual drivers. |
| `uncommitted_monthly_income` | +1 (↑) | After fixed commitments; larger = more affordability buffer. |
| `utility_payment_regularity` | +1 (↑) | Consistent utility payments are a cheap positive signal in thin files. |
| `bnpl_active_count` | −1 (↓) | Active BNPL accounts duplicate num_bnpl_accounts signal; same sign. |
| `bnpl_late_payments_12m` | −1 (↓) | BNPL late payments predict revolving-credit late payments. |
| `bnpl_monthly_commitment` | −1 (↓) | Monthly BNPL scheduled repayments; direct expense. |
| `bnpl_total_limit` | −1 (↓) | Total BNPL exposure; larger = more hidden serviceability drag. |
| `bnpl_utilization_pct` | −1 (↓) | BNPL used ÷ limit; high use signals liquidity stress. |
| `bureau_risk_score` | −1 (↓) | Higher bureau risk score = more recently adverse activity. |
| `cash_advance_count_12m` | −1 (↓) | Cash advances indicate short-term liquidity stress; high rate-cost. |
| `credit_card_burden` | −1 (↓) | Derived: card limits / income; same direction as limits. |
| `credit_utilization_pct` | −1 (↓) | Above 70% utilisation is a top-3 bureau-score negative in AU. |
| `days_in_overdraft_12m` | −1 (↓) | More days negative = tighter cash-flow margin; monotone worse. |
| `days_negative_balance_90d` | −1 (↓) | Recent days in negative balance = cashflow fragility. |
| `debt_to_income` | −1 (↓) | APRA limits above DTI=6; higher = less serviceability (APS 220 focus). |
| `effective_loan_amount` | −1 (↓) | Loan + LMI (what actually appears on the mortgage); same direction as loan_amount. |
| `enquiry_intensity` | −1 (↓) | Enquiries per open account; high velocity = shopping-for-credit stress. |
| `essential_to_total_spend` | −1 (↓) | Higher essentials ratio = less discretionary buffer to cut. |
| `existing_credit_card_limit` | −1 (↓) | More unused revolving limit inflates stressed serviceability commitments. |
| `expense_to_income` | −1 (↓) | Mechanical ratio; more expense per dollar of income = less slack. |
| `gambling_spend_ratio` | −1 (↓) | Gambling share of spend is a direct negative; mirrors AFCA guidance. |
| `gambling_transaction_flag` | −1 (↓) | AFCA 2023: gambling spend is a responsible-lending red flag. |
| `has_bankruptcy` | −1 (↓) | Bankruptcy is a hard-fail predictor historically; monotone worse. |
| `hecs_debt_balance` | −1 (↓) | HECS balance proxies future HELP repayment; higher = more drag. |
| `help_repayment_monthly` | −1 (↓) | HELP/HECS repayment reduces post-tax serviceability income. |
| `hem_gap` | −1 (↓) | Negative gap means HEM > income (hard-fail); magnitude monotonic in severity. |
| `income_verification_gap` | −1 (↓) | Mismatch between stated and verified income; higher = higher fraud risk. |
| `lmi_premium` | −1 (↓) | LMI charged only above 80% LVR; higher = higher-LVR loan = riskier. |
| `loan_amount` | −1 (↓) | Larger loans = larger repayment shocks under stress. |
| `loan_to_income` | −1 (↓) | Higher LTI = less room for income shocks; NAB LTI cap 9×. |
| `log_loan_amount` | −1 (↓) | Log transform of loan_amount; monotone transform, same sign. |
| `lvr` | −1 (↓) | Key secured-lending risk variable; APRA flags LVR > 80% and LMI-required bands. |
| `lvr_x_dti` | −1 (↓) | Interaction of two negative drivers; sign is the product: negative. |
| `monthly_expenses` | −1 (↓) | Higher declared expenses reduce serviceability surplus. |
| `monthly_rent` | −1 (↓) | Current rent is effectively baseline housing commitment; larger = less surplus. |
| `num_bnpl_accounts` | −1 (↓) | More BNPL accounts = more hidden commitments (CCR gap; 2024 ASIC concern). |
| `num_credit_enquiries_6m` | −1 (↓) | Shopping intensity signals financial stress; > 6 enquiries is a red flag. |
| `num_defaults_5yr` | −1 (↓) | Historical defaults are the strongest negative signal in bureau scoring. |
| `num_dishonours_12m` | −1 (↓) | Dishonours indicate cash-flow failures; AFCA/Basiq flags these as leading indicators. |
| `num_hardship_flags` | −1 (↓) | AFCA/ASIC 2023 guidance: hardship history is materially negative. |
| `num_late_payments_24m` | −1 (↓) | CCR-era late payments directly predict future default. |
| `number_of_dependants` | −1 (↓) | More dependants = more baseline expenses (HEM scales with dependants). |
| `overdraft_frequency_90d` | −1 (↓) | Frequent overdraft = recurring cash-flow fragility. |
| `postcode_default_rate` | −1 (↓) | Geographic concentration risk; higher area default rate = worse tail. |
| `stress_index` | −1 (↓) | Aggregated stress score; direction matches its component drivers. |
| `stressed_dsr` | −1 (↓) | DSR at stressed rate; higher = less buffer against RBA hikes (APS 220). |
| `stressed_repayment` | −1 (↓) | Repayment at assessed-rate; higher = more monthly burden under stress. |
| `subscription_burden` | −1 (↓) | Sticky subscriptions reduce flex to cut expenses under stress. |
| `unemployment_rate` | −1 (↓) | Macro unemployment tail-risk correlates with individual default. |
| `worst_arrears_months` | −1 (↓) | More months in arrears = stronger recent negative evidence. |
| `worst_late_payment_days` | −1 (↓) | Severity of worst late-payment episode; more days = worse. |

## 5. Performance

Evaluated on hold-out test set (20% of training data):

- **AUC-ROC:** 0.8709
- **KS statistic:** 0.6420
- **Brier score (pointwise):** 0.1371
- **ECE (15-bin):** 0.0337

**Temporal cross-validation:** not recorded

**Baseline logistic-regression gap:** not measured

KS > 0.30 and AUC > 0.75 are the regulator-expected performance floor for AU retail-credit scorecards. Champion-challenger promotion gates exist in `model_selector.py` (PSI, calibration, KS); the current activation path in `tasks.py` activates new models directly, so confirm pre-promotion review for production deployments before relying on these gates.

## 6. Calibration report

| Decile | Actual default rate | Cumulative rate | Lift | n |
|---|---|---|---|---|
| 1 | 0.1227 | 0.1227 | 0.2169 | 864 |
| 2 | 0.2060 | 0.1644 | 0.3642 | 864 |
| 3 | 0.2627 | 0.1971 | 0.4645 | 864 |
| 4 | 0.2697 | 0.2153 | 0.4768 | 864 |
| 5 | 0.3889 | 0.2500 | 0.6875 | 864 |
| 6 | 0.7014 | 0.3252 | 1.2400 | 864 |
| 7 | 0.8773 | 0.4041 | 1.5511 | 864 |
| 8 | 0.9259 | 0.4693 | 1.6370 | 864 |
| 9 | 0.9479 | 0.5225 | 1.6759 | 864 |
| 10 | 0.9537 | 0.5656 | 1.6861 | 864 |

## 7. PSI by feature

| Feature | PSI (train vs test) | Status |
|---|---|---|
| `rate_stress_buffer` | 0.1761 | ⚠ moderate drift |
| `dti_x_rate_sensitivity` | 0.1532 | ⚠ moderate drift |
| `credit_history_months` | 0.1283 | ⚠ moderate drift |
| `debt_service_coverage` | 0.0021 | stable |
| `net_monthly_surplus` | 0.0020 | stable |
| `stressed_repayment` | 0.0018 | stable |
| `hem_surplus` | 0.0017 | stable |
| `debt_to_income` | 0.0016 | stable |
| `monthly_repayment_ratio` | 0.0013 | stable |
| `uncommitted_monthly_income` | 0.0013 | stable |
| `loan_amount` | 0.0012 | stable |
| `log_loan_amount` | 0.0012 | stable |
| `deposit_x_income_stability` | 0.0012 | stable |
| `stress_index` | 0.0011 | stable |
| `credit_x_employment` | 0.0011 | stable |
| `stressed_dsr` | 0.0010 | stable |
| `deposit_amount` | 0.0010 | stable |
| `loan_to_income` | 0.0010 | stable |
| `savings_to_loan_ratio` | 0.0010 | stable |
| `credit_score` | 0.0009 | stable |
| `credit_score_x_tenure` | 0.0009 | stable |
| `lvr_x_property_growth` | 0.0008 | stable |
| `income_credit_interaction` | 0.0008 | stable |
| `deposit_ratio` | 0.0007 | stable |
| `employment_stability` | 0.0005 | stable |
| `existing_property_count` | 0.0004 | stable |
| `loan_term_months` | 0.0003 | stable |
| `lvr` | 0.0002 | stable |
| `employment_length` | 0.0002 | stable |
| `lvr_x_dti` | 0.0001 | stable |
| `property_value` | 0.0001 | stable |
| `worst_late_payment_days` | 0.0001 | stable |
| `state_NT` | 0.0000 | stable |
| `state_SA` | 0.0000 | stable |
| `state_WA` | 0.0000 | stable |
| `state_ACT` | 0.0000 | stable |
| `state_NSW` | 0.0000 | stable |
| `state_QLD` | 0.0000 | stable |
| `state_TAS` | 0.0000 | stable |
| `state_VIC` | 0.0000 | stable |
| `purpose_auto` | 0.0000 | stable |
| `purpose_home` | 0.0000 | stable |
| `has_bankruptcy` | 0.0000 | stable |
| `num_defaults_5yr` | 0.0000 | stable |
| `purpose_business` | 0.0000 | stable |
| `purpose_personal` | 0.0000 | stable |
| `industry_anzsic_A` | 0.0000 | stable |
| `industry_anzsic_B` | 0.0000 | stable |
| `industry_anzsic_C` | 0.0000 | stable |
| `industry_anzsic_E` | 0.0000 | stable |
| `industry_anzsic_G` | 0.0000 | stable |
| `industry_anzsic_H` | 0.0000 | stable |
| `industry_anzsic_I` | 0.0000 | stable |
| `industry_anzsic_J` | 0.0000 | stable |
| `industry_anzsic_K` | 0.0000 | stable |
| `industry_anzsic_M` | 0.0000 | stable |
| `industry_anzsic_N` | 0.0000 | stable |
| `industry_anzsic_O` | 0.0000 | stable |
| `industry_anzsic_P` | 0.0000 | stable |
| `industry_anzsic_Q` | 0.0000 | stable |
| `industry_anzsic_S` | 0.0000 | stable |
| `purpose_education` | 0.0000 | stable |
| `home_ownership_own` | 0.0000 | stable |
| `home_ownership_rent` | 0.0000 | stable |
| `applicant_type_couple` | 0.0000 | stable |
| `applicant_type_single` | 0.0000 | stable |
| `savings_trend_3m_flat` | 0.0000 | stable |
| `cash_advance_count_12m` | 0.0000 | stable |
| `industry_risk_tier_low` | 0.0000 | stable |
| `home_ownership_mortgage` | 0.0000 | stable |
| `industry_risk_tier_high` | 0.0000 | stable |
| `employment_type_contract` | 0.0000 | stable |
| `industry_risk_tier_medium` | 0.0000 | stable |
| `savings_trend_3m_negative` | 0.0000 | stable |
| `savings_trend_3m_positive` | 0.0000 | stable |
| `employment_type_payg_casual` | 0.0000 | stable |
| `industry_risk_tier_very_high` | 0.0000 | stable |
| `employment_type_self_employed` | 0.0000 | stable |
| `employment_type_payg_permanent` | 0.0000 | stable |

## 8. Fairness audit

| Protected attribute | DI ratio | 80%-rule passes |
|---|---|---|
| `state` | 0.7736 | False |
| `applicant_type` | 0.8956 | True |
| `employment_type` | 0.7206 | False |

Cross-reference `intersectional_fairness.py` output in `training_metadata.intersectional_fairness` for two-way slices.

## 9. Policy overlay reference

| Code | Severity | Description |
|---|---|---|
| P01 | hard_fail | Non-resident / ineligible visa (bridging/student/tourist) — decline |
| P02 | hard_fail | Applicant age < 18 or age at maturity > 75 |
| P03 | hard_fail | Undischarged bankruptcy or within 7yr window — decline |
| P04 | hard_fail | Active ATO tax-debt default flag — decline |
| P05 | hard_fail | Credit score below floor 450 — decline |
| P06 | hard_fail | LVR > 95% owner-occupier or ≥ 100% any — decline |
| P07 | hard_fail | DTI exceeds APRA intervention ceiling 8.0× — decline |
| P08 | refer | LTI > 9× — refer to manual underwriting |
| P09 | refer | Postcode default rate > 8% — geographic concentration review |
| P10 | refer | Self-employed with < 24mo trading history — refer |
| P11 | refer | Hardship flag(s) on file — AFCA 2023 mandates human review |
| P12 | refer | Personal loan > $50k TMD band — refer to TMD-aware underwriting |

Current overlay mode is read from `CREDIT_POLICY_OVERLAY_MODE` (off / shadow / enforce). See §2 for the mode this dossier was generated under.

## 10. Ongoing monitoring plan

- **Retraining cadence:** every 90 days minimum.
- **Minimum fresh samples before retrain:** 10000
- **PSI alert threshold:** 0.25 (per-feature); cumulative PSI > 0.5 triggers retrain.
- **ECE re-validation cadence:** quarterly.
- **KS regression trigger:** drop > 5pp vs champion baseline triggers retrain.
- **Fairness audit cadence:** every training run pre-promotion (see fairness_gate.py).
- **Drift dashboard:** `/api/v1/ml/models/active/drift/` (weekly DriftReport cron).

## 11. Change log

Comparison vs previous ModelVersion on segment `unified`: `25356f34-dfb4-4a7c-882c-754a90183ee6` (v20260508_194730).

- **AUC-ROC:** 0.8709 vs 0.8709 (→0.0000)
- **KS:** 0.6420 vs 0.6420 (→0.0000)
- **Brier:** 0.1371 vs 0.1371 (→0.0000)
- **ECE:** 0.0337 vs 0.0337 (→0.0000)
