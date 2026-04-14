# Australian Lending Platform Research

**Date:** 2026-04-14
**Sources:** 9 Australian lenders (see `docs/superpowers/specs/2026-04-14-au-lending-research-design.md` for rationale)
**Feeds:** sub-project B (ML / synthetic data + XGBoost), sub-project C (code efficiency, stress testing, UX/email)
**Method caveat:** WebFetch was denied in several subagent runs, so extraction for Up, Judo, Alex, Plenti, Wisr, MoneyMe, and Canstar relies on WebSearch result snippets rather than full-page fetches. CBA and NAB were fully fetched. Direct quotes are marked in scratch files under `.tmp/research/`.

## Executive Summary

Australian consumer lenders converge on a small, well-defined set of application inputs and risk signals. Every lender in scope uses **risk-based pricing** (published APR bands span ~7% to ~24%) driven by **Comprehensive Credit Reporting (CCR)** including 24-month Repayment History Information (RHI). Most collect the same application fields: photo ID, employment/income verification (payslips or digital bank-statement retrieval), itemised living expenses, existing debts (with **BNPL increasingly listed explicitly**), loan amount/term/purpose, and residency status. Minimum age is consistently 18; residency is consistently "Australian citizen or permanent resident" with lender-specific visa rules. Minimum income is rarely published — typically replaced by an NCCP "substantial hardship" serviceability test.

The biggest differentiators are **UX and decisioning speed**, not criteria. Fintechs (MoneyMe, Plenti, Alex) offer **soft-pull quotes** (no credit-score impact), 90-second to 5-minute applications, and same-day or instant-hour approvals. Incumbents (CBA, NAB) take 1+ business day post-acceptance and lean on borrowing-power estimators rather than soft quotes. Wisr leads with CCR transparency and a free credit-score lead-gen product. Plenti publishes the clearest risk-based-pricing doctrine. Alex Bank has a customer-visible "advertised vs offered rate" credibility gap we should avoid.

Biggest gaps vs our current synthetic data generator: **BNPL balance**, **savings balance / savings history**, **soft-pull vs hard-pull indicator**, **visa sub-class** (affects loan-term eligibility at CBA), **age-at-loan-maturity**, and **number of recent enquiries in the last 6 months** (we have `enquiries` but not windowed). On the UX side: we should adopt a **soft-quote flow** and **transparent rate-factor disclosure** (which inputs drove this rate) — patterns seen across Plenti, Alex, and MoneyMe.

## Per-Lender Findings

### Commonwealth Bank (CBA)
**Type:** Big Four. **Fetched:** 6 URLs on commbank.com.au.
**Application fields:** full name, ID docs, residency/citizenship with visa sub-class + expiry, employment type, proof of income (3 months salary credits or payslips, 12 months self-employed trading), existing debts via bank statement, loan purpose, amount, term, fixed-vs-variable choice, car-specific docs for auto loans.
**Eligibility:** min_income=null (serviceability-only), min_age=null (18+ assumed), residency="AU citizen/PR; visa holders eligible if visa outlasts loan term by ≥1 month; 417/600 visas ineligible".
**Risk signals:** CCR (Equifax + Experian, 24-month RHI), bank-statement analysis, serviceability, employment stability, visa-term vs loan-term mismatch, hardship flags.
**Rates & fees:** 7.00–22.00% p.a. headline, 8.41–23.29% comparison. Post-fixed reversion SVR 16.00%. Establishment $250, monthly $15, late $20, early-repayment adj $15 (if ≥12 months remain).
**UX:** borrowing-power estimator (pre-qual), personal-loan selector, rate-personalisation disclosure, CommBank Credit Score Hub (free Experian score).
**Gaps:** no published min income, min age, DTI, credit-score cutoff, or decision SLA.

### NAB
**Type:** Big Four. **Fetched:** 6 URLs on nab.com.au + one third-party.
**Application fields:** amount, term, repayment frequency, rate type, full name/DOB/title, driver's licence (used for bureau pull), residency, address+living arrangement (previous if <3yr), 3-year employment history, gross+net income, assets with valuations, current liabilities, itemised expense categories, loan purpose.
**Eligibility:** min_income=null, min_age=18, residency="AU citizen or PR; sole applicant only", near-retirement (63+) triggers additional questioning.
**Risk signals:** CCR + credit score drives pricing, responsible-lending unsuitability test, LTI cap 7 / DTI cap 8× (home/self-employed context), income verification via 2-of-last-3 payslips or bank statements, expense categorisation (implicit HEM).
**Rates & fees:** 7.00–21.00% p.a. headline, 8.41–22.29% comparison. Establishment $250, monthly $15, exit/late/early-repayment $0.
**UX:** rate influenced by banking history with NAB, conditional approval + e-sign via NAB Internet Banking, funds in 1 business day post-acceptance, accordion-style help.
**Gaps:** no published min income, min credit score, serviceability buffer, or initial-decision SLA.

### Up Bank
**Type:** Neobank (Bendigo & Adelaide Bank backed).
**Headline finding:** **No consumer personal loan product.** Only lending product is Up Home (residential mortgages, partnered with Bendigo + Tiimely). Findings below are home-loan-derived proxy.
**Application fields (home):** ID, personal/partner details, property (postcode-gated to urban centres), income + type (salaried vs casual/irregular), expenses, deposit size.
**Eligibility:** published fields nulled; property postcode filter is the primary gate.
**Risk signals:** credit check, serviceability, spending analysis, income-type segmentation, robot+human hybrid verification, NCCP unsuitability test.
**Rates & fees:** specific APR not extracted; notable **fee posture: $0 application, $0 setup, $0 monthly/annual, $0 redraw, $0 discharge**. "Both new and existing Upsiders get the same variable rate" (no loyalty tax).
**UX:** fully in-app application, postcode-first eligibility, plain-English copy, auto-generated loan docs, casual "Upsiders" tone.
**Gaps:** no personal loan product; WebFetch denied so numeric rates not captured.

### Judo Bank
**Type:** Neobank (SME-focused).
**Headline finding:** **No consumer personal loan product.** $250k minimum for Business Loans, Lines of Credit, Equipment Loans, Bank Guarantees, Acquisition Loans. Home loans restricted to Judo business customers.
**Application fields (SME):** government photo ID, source-of-funds docs, P&L + balance sheet + cash-flow projections, existing debt obligations, ABN (Trusts/Incorporated Associations), trust deed, business plan.
**Risk signals:** character-first relationship-led underwriting, cashflow analysis, serviceability of existing debt, collateral posture (52% fully secured, 33% partially, 15% balance-sheet).
**Rates & fees:** relationship-priced, not published; comparison-rate concept N/A to business lending.
**UX:** dedicated relationship banker, no self-serve online application, broker channel drives growth.
**Gaps:** consumer-credit fields mostly N/A; WebFetch denied.

### Alex Bank
**Type:** Neobank. **Fetched:** 8 URLs via search snippets (WebFetch denied).
**Application fields:** DOB, residency, AU photo ID (licence/passport), BSB+account, camera-based ID verification, income, amount ($2.1k–$30k), term (6mo–5yr), purpose.
**Eligibility:** min_age=18, residency="AU citizen or PR, resident in AU at application", min_income=null but "regular income" required, **no prior bankruptcy**, **not >67 at maturity** (age-at-maturity gate), "higher than average credit scores".
**Risk signals:** credit history + score, transactional behaviour (open-banking style), employment stability, loan purpose, term, serviceability, age-at-maturity cap, bankruptcy exclusion.
**Rates & fees:** fully personalised (no posted range); example 5.45% p.a. comparison for a $30k/3yr excellent-credit scenario. $295 establishment, $0 ongoing, $0 early-repayment.
**UX:** 5-minute application, 1-business-day decision, transparent rate-factor disclosure, digital camera ID, Qantas Points tie-in. **Credibility risk:** Trustpilot reviews cite advertised-vs-offered rate gap — a transparency lesson for our system.
**Gaps:** exact APR range, DTI, min income, TMD detail.

### Plenti
**Type:** Marketplace specialist. **Fetched:** 8 URLs via snippets.
**Application fields:** purpose, amount ($5k–$65k unsecured, up to $75k advertised), term (1–7yr fixed, 1–2yr variable), DOB, residency, annual income, employment type (self-employed accepted with extra checks), AU licence/passport, income docs (bank statements or tax returns), CCR consent.
**Eligibility:** min_income=$25,000, min_age=18, residency="AU citizen or PR", "good credit history" required.
**Risk signals:** CCR (positive + negative), full repayment history, income stability (explicit: "unstable income will be charged higher rates"), existing debts, credit score → approval/size/rate, bank-statement review, self-employed flag.
**Rates & fees:** 6.17–24.09% p.a. headline, 6.17–25.08% comparison. Establishment $0–$599 by risk profile, variable Credit Assistance Fee, $0 monthly, $0 early-repayment.
**UX:** **RateEstimate soft-pull quote** (no credit-score impact), explicit risk-based-pricing doctrine page, "Rate Promise" marketing, CCR positive-framing copy, 3-step application framing, self-service eligibility FAQ.
**Gaps:** decision SLA, published credit-grade bands, DTI threshold, credit-score cutoff.

### Wisr
**Type:** Specialist (CCR-focused). **Fetched:** 10 URLs via snippets.
**Application fields:** 2x ID (licence/passport/Medicare), 3–5 years employment history, bank statements, **debts including BNPL explicitly**, itemised living expenses, amount+purpose.
**Eligibility:** min_income=$25,000, min_age=18, residency=AU, "good credit standing".
**Risk signals:** **CCR is central** (dedicated explainer page), RHI ("green ticks"), Financial Hardship Information (FHI) reporting, credit-score tiered pricing, DTI, serviceability/surplus-cash, bank-statement analysis, **BNPL balances as first-class debt input**, HEM-style expense itemisation.
**Rates & fees:** 6.94–24.74% p.a. headline. Establishment $595 (unsecured), $605/$655 (motorcycle), dishonour $15, late $30, $0 early-repayment.
**UX:** free credit-score tool (lead gen), Smart Guides content marketing, purpose-specific landing pages, calculator on product page, Supporting Documents Checklist up-front, aspirational "Power Your Possible" tone, no apology/deficit language.
**Gaps:** decision SLA, comparison-rate max, credit-score cutoff.

### MoneyMe
**Type:** Specialist (instant-decision fintech). **Fetched:** 6 URLs via snippets.
**Application fields:** mobile, email, personal details, approximate income, approximate expenses, existing bills, employment status, **digital bank-statement retrieval** (no uploads).
**Eligibility:** min_income=null (only "employed/working in AU"), min_age=18, residency="AU citizen, NZ citizen, or AU PR", credit-file marks not auto-decline; bankruptcy + debt agreement auto-decline.
**Risk signals:** **proprietary "MoneyMe Loan Rating"**, credit check, bankruptcy/debt-agreement flags, serviceability, bank-statement transaction analysis (CDR-style), income-vs-expense comparison, risk-based pricing.
**Rates & fees:** min 5.99% p.a. headline, min 6.70% comparison (max not published). Establishment $395 or $495 tiered (**$0 for excellent credit**), monthly $10, $0 early-repayment, $0 exit. Unsecured up to $70k.
**UX:** **90-second online quote** (soft-pull), instant approval in business hours, same-day funding, no paperwork (digital bank-statement retrieval), mobile-first, explicit fee-tier transparency, app-managed servicing.
**Gaps:** max APR, weights of proprietary rating, DTI cut-offs, CCR explicit confirmation.

### Canstar (comparison site)
**Type:** Comparison. **Fetched:** 6 URLs via snippets.
**Canonical AU application fields:** photo ID, PAYG payslips, bank statements, employment details, assets, existing debts, living expenses, self-employed tax return, loan purpose, single-vs-joint + dependants.
**Market eligibility:** no standard min income, min_age=18, residency="AU citizen or PR (visa lender-specific)", "reliable record as a borrower".
**Market risk signals:** serviceability, DTI, credit defaults, payments >14 days overdue, savings history, loan purpose, multiple recent applications, CCR (mandatory for Big 4 since 2018/2021).
**Market rates (Apr 2026):** 5.76–12.99% p.a. featured headlines; comparison up to ~24.03% p.a.; basis $10k/3yr unsecured. Establishment $0–$1,200, ongoing mostly $0, some $60/yr (Bendigo, HSBC).
**UX narrative:** decision in "a few days", conditional approval with doc follow-ups, rate personalisation, pre-approval as distinct product, secured/unsecured + fixed/variable as primary axes, guarantor as eligibility enhancer.
**Gaps:** no universal min-income; no quantitative DTI or HEM thresholds published.

## Consolidated Findings

### Common application fields (present in ≥5 of 7 personal-loan lenders: CBA, NAB, Alex, Plenti, Wisr, MoneyMe + Canstar canon)
- Photo ID (licence/passport) — 7/7
- Loan amount + term + purpose — 7/7
- Income amount — 7/7
- Living expenses (itemised) — 6/7
- Existing debts/liabilities — 7/7
- Bank statements (directly uploaded or digitally retrieved) — 6/7
- Residency/citizenship + age — 7/7
- Employment type + employment history — 6/7

### Common risk signals (present in ≥5 of 7)
- Comprehensive Credit Reporting (CCR) / RHI — 6/7 (Wisr, Plenti, CBA, NAB, Alex implicit, Canstar confirms Big 4 mandatory; MoneyMe not explicit)
- Risk-based pricing (personalised APR) — 7/7
- Serviceability / NCCP unsuitability test — 7/7
- Bank-statement / transaction analysis — 6/7
- Credit score tiered pricing — 6/7
- Employment stability — 6/7
- Loan purpose as risk factor — 6/7

### Gaps in our current synthetic data
Our generator (`backend/apps/ml_engine/services/data_generator.py`) includes income, employment type, dependants, state, ANZSIC industry, credit score, DTI, loan amount/term/purpose, home ownership, property value, LVR, deposit, monthly expenses, credit-card limit, rent, HECS, enquiries, arrears, defaults, bankruptcy, property count, RBA cash rate, unemployment, consumer confidence.

Missing or weakly represented vs real AU lender criteria:

1. **BNPL balance** — Wisr explicitly, likely material in post-2019 AU market; absent from generator.
2. **Savings balance / savings history** — Canstar lists "savings history" as a denial signal; absent.
3. **24-month RHI (green ticks) vector** — we have aggregated arrears/defaults; real lenders consume month-by-month RHI.
4. **Visa sub-class + visa-expiry vs loan-term gap** — CBA uses this directly for eligibility; absent.
5. **Age-at-loan-maturity** — Alex Bank's 67-cap rule; not derivable without maturity date.
6. **Recent enquiries windowed (last 6 months)** — we have total enquiries; timing matters per Canstar.
7. **Soft-pull vs hard-pull flag on record** — neobank UX pattern; absent.
8. **Self-employed trading years** (distinct from employment_length); CBA requires ≥12 months.
9. **Financial Hardship Information (FHI) flag** — Wisr reports this; absent.

### UX / copy patterns worth adopting
- Soft-pull rate quote with no credit-score impact (MoneyMe 90s, Plenti RateEstimate, Alex)
- Transparent rate-factor disclosure ("your rate depends on: X, Y, Z") — Plenti, Alex, Wisr
- Supporting-Documents Checklist shown upfront — Wisr
- CCR positive-framing copy — Plenti, Wisr
- Fee-tier transparency (e.g. "$0 establishment for excellent credit") — MoneyMe
- Borrowing-power estimator before funnel entry — CBA
- Plain-English, no-apology, no-deficit language — Up, Wisr (aligns with our existing memory feedback)
- Avoid advertised-vs-offered rate gap that hurt Alex Bank's Trustpilot reviews

## Recommendations

Every item tagged `[→ B]` (ML / synthetic data) or `[→ C]` (code / UX / email / stress test).

- `[→ B]` Add `bnpl_balance` feature to data generator, correlated with age (higher in <35), income (inverse), and credit utilisation. Train XGBoost with it as a feature.
- `[→ B]` Add `savings_balance_months` (months of expenses in savings) feature. Canstar explicitly calls savings history a denial signal.
- `[→ B]` Add `rhi_24_month_vector` or at minimum `months_on_time_last_24` and `months_late_last_24`, distinct from aggregated arrears. This matches how Big 4 actually consume RHI.
- `[→ B]` Add `enquiries_last_6_months` alongside existing total-enquiries; real lenders penalise short-window application clustering.
- `[→ B]` Add `age_at_loan_maturity` (derived from age + term) and bake an Alex-style 67-cap as a **policy rule** in the approval decisioning (not a model feature), surfaced in reason codes.
- `[→ B]` Add `visa_subclass` + `visa_expiry_months_after_loan_term` with CBA's rule (expiry must exceed loan term by ≥1 month); apply as eligibility gate for non-citizen/non-PR applicants.
- `[→ B]` Add `self_employed_trading_years` distinct from `employment_length`; enforce CBA's ≥12-month threshold as a feature or gate for self-employed applicants.
- `[→ B]` Add `financial_hardship_flag` (binary, Wisr's FHI concept) as a feature; rare (~1–2% base rate) with strong negative effect.
- `[→ B]` Re-calibrate synthetic APR distribution to match observed AU market: min ~6–7% for excellent credit, max ~24–25% comparison rate. Verify our generated `loan_interest_rate` (if any) falls in this band.
- `[→ B]` Document these additions in a synthetic-data-schema spec and version-bump the data generator.
- `[→ C]` Add a **soft-pull rate quote** endpoint that returns a personalised rate without running the full model / scoring pipeline, matching MoneyMe's 90-second quote pattern.
- `[→ C]` Add **transparent rate-factor disclosure** to the approval email and the UI: "Your rate was driven by: credit score tier X, DTI Y, employment stability Z." Reuses existing reason-code infrastructure.
- `[→ C]` Add a **Supporting Documents Checklist** screen up-front in the frontend application flow (Wisr pattern).
- `[→ C]` Add a **borrowing-power estimator** component (CBA pattern) as a pre-application engagement tool.
- `[→ C]` Ensure email copy stays aligned with existing no-apology-language rule (memory already enforces this) — research confirms this is the AU neobank standard.
- `[→ C]` For stress testing, prioritise: (1) soft-quote endpoint under burst load (will be highest-traffic), (2) ML scoring under p99 latency targets, (3) orchestrator Celery queue saturation.
- `[→ C]` Consider a fee-tier model where establishment fee is $0 for excellent-credit segments (MoneyMe pattern) — surfaces as a product decision, not a code one, but the code needs to support tiered fees.
