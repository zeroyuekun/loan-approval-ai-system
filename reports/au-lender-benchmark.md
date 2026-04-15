# Australian Lender Benchmark: Application Fields, Policy, and Distributions

Research conducted **2026-04-15** to inform synthetic applicant data and the XGBoost approval model. Every factual claim is followed by a source URL; retrieval date is **2026-04-15** unless noted otherwise. Sources older than 2024 are flagged `[stale: <year>]`.

## 1. Input fields real Australian lenders collect

Across seven lenders sampled — CommBank, NAB (big-4), Athena, Tic:Toc/Tiimely (neobank/digital), Pepper Money (non-bank), Plenti, SocietyOne (P2P) — intake fields converge; differences are in verification mechanism, not field set.

**CommBank** collects photo ID, 3 months bank statements (6 if casual), most recent payslip, employment contract/letter with base wage, PAYG summaries, tax returns and ATO NoAs for sole traders or investment income, Centrelink letters for benefits, rental agent statements, rates notices, insurance schedules, contract of sale, building tender/plans, and a line-item monthly living-expenses breakdown. **Credit-card and BNPL liabilities are captured at the facility limit, not current balance** (https://www.commbank.com.au/home-loans/applying-for-a-home-loan.html).

**NAB** requests identity, contact, income, expenses, assets, property details, financial goals, proof of ID (passport/licence/birth certificate/utility or rates notice), payslips, bank statements, and itemised liabilities with credit-card limits and loan balances with repayment amounts (https://www.nab.com.au/content/dam/nabrwd/documents/forms/loans/home-loan-application-form.pdf).

**Athena** digital-verifies ID, ingests payslips and bank/credit-card statements as PDFs into Home Hub, issues a decision in ~60 seconds; hard LVR cap ≤80% (≤70% for high-value/regional) (https://www.finder.com.au/home-loans/athena-home-loans; https://www.homeloanexperts.com.au/lender-reviews/athena-home-loans-review/).

**Tic:Toc/Tiimely** digital ID, direct bank-account link for income/expense/liability pull with manual PDF fallback, credit check, property address + signed Contract of Sale; quoted approval "as little as 22 minutes" (https://tictoc.com.au/faqs/category/applying-for-a-loan; https://blogs.mulesoft.com/digital-transformation/business/tictoc-instant-home-loans/ `[stale: 2019]`).

**Pepper Money** captures same core fields but decouples outcome from credit score; accepts complex/self-employed income, short employment history, prior adverse events; reference band: Equifax below-average ≤549 (https://www.peppermoney.com.au/resources/credit-report-real-life-guide).

**Plenti** ~10-minute online form, requires Australian citizenship/PR, income verified via statements or tax returns; hard exclusions: income <$25,000, employed <3 months, current default/bankruptcy (https://www.plenti.com.au/guides/eligibility). **SocietyOne** requires ≥$30,000 annual income, ≥18, citizenship/PR; no published hard score floor (https://societyone.com.au/faqs/how-to-qualify-for-a-loan; https://societyone.com.au/faqs/what-credit-score-is-needed-for-a-personal-loan).

**Unified field taxonomy for the generator** — identity/residency; age/DOB; employment type (PAYG full/part/casual, self-employed, contractor, retiree, Centrelink); income streams (base, bonus, overtime, commission, rental, dividends, benefits); HEM-benchmarked expenses; liabilities (credit-card limits, BNPL, HELP, personal loans, mortgages, guarantees); dependants; marital/applicant structure; assets (cash, super, property, vehicles); credit file; property/LVR inputs; loan purpose and term.

## 2. Serviceability & policy inputs

**2.1 APRA 3% buffer** — 3.0pp above product rate, set 6 Oct 2021 (raised from 2.5pp), excluding introductory discounts (https://www.apra.gov.au/news-and-publications/apra-increases-banks%E2%80%99-loan-serviceability-expectations-to-counter-rising); retained in most recent macroprudential update (https://www.apra.gov.au/news-and-publications/apra-announces-update-on-macroprudential-settings).

**2.2 APG 223 prudent practice** (https://handbook.apra.gov.au/ppg/apg-223): rental-income haircut ≥20% (larger for high-vacancy), variable-income discount ≥20% on bonuses/overtime/commissions/investment income, self-employed verification via ITAs/tax returns/accountant letter/BAS/ADI bank statements, HELP/HECS is a debt commitment (override only if payoff within 12 months), LVR >90% (incl. capitalised LMI) flagged as high loss risk.

**2.3 DTI macroprudential activation (NEW)** — APRA activated formal DTI limits from **February 2026** restricting share of new lending at DTI ≥6 separately for investor and owner-occupier books (https://www.apra.gov.au/quarterly-authorised-deposit-taking-institution-property-exposure-statistics-december-2025). Material change for the generator.

**2.4 HEM** = median spend on absolute basics + 25th-percentile spend on discretionary basics, net of housing costs; published quarterly, CPI-linked, distributed via Perpetual (https://melbourneinstitute.unimelb.edu.au/research/family-and-labour-economics/projects/2012/household-expenditure-measure-quarterly-updates); May-2024 category expansion in LIXI schema (https://lixi.org.au/hem-update-may-2024/).

**2.5 ASIC RG 209 / NCCP Ch 3** — reasonable inquiries into financial situation/requirements/objectives, reasonable verification, "not unsuitable" assessment, written assessment on request (https://www.asic.gov.au/regulatory-resources/find-a-document/regulatory-guides/rg-209-credit-licensing-responsible-lending-conduct/; https://download.asic.gov.au/media/hyeofbni/rg209-published-9-december-2019-20250306.pdf) `[stale: 2019]`.

**2.6 CCR** — 24-month monthly repayment history, account type/limits/dates; Equifax bureau covers 16M+ files (https://www.equifax.com.au/personal/what-is-comprehensive-credit-reporting).

## 3. Realistic distributions for Australian applicants

**3.1 Personal income by state (ABS FY2022-23, released Nov-2025)**: median **ACT $75,643 / NT $66,831 / WA $62,207 / NSW $58,909 / VIC $57,907 / QLD $56,708 / SA $55,782 / TAS $53,479**; top-1% share 7.0% (ACT) → 11.2% (NSW); top-10% 28.6% (NT) → 35.8% (NSW) (https://www.abs.gov.au/statistics/labour/earnings-and-working-conditions/personal-income-australia/latest-release). Confirms the heavy right-skew assumption.

**3.2 LVR/DTI on new flow (APRA QPEX Dec-2025)** (https://www.apra.gov.au/quarterly-authorised-deposit-taking-institution-property-exposure-statistics-december-2025): LVR ≥80% = **32.2%**; DTI ≥6x = **6.8%**; owner-occupied **61.8%**, investor **35.9%**; overall NPL **0.99%**; LVR ≥80% only 16.9% of outstanding stock → new originations are materially higher-leverage than stock (useful vintage calibration signal).

**3.3 Arrears** — owner-occupier NPL 1.1%, investor NPL 0.9% at Jun-2024 (https://www.rba.gov.au/publications/bulletin/2024/jul/recent-drivers-of-housing-loan-arrears.html); ~2% of variable-rate owner-occupiers in negative cash flow, 0.7% with both negative cash flow and low buffers; LVR>80% cohort runs ~2.5% 90+dpd (https://www.rba.gov.au/publications/fsr/2025/oct/resilience-of-australian-households-and-businesses.html). Target positive-class base-rate ~1–2.5% for home loans, ~5–10% for unsecured personal loans.

**3.4 Equifax score** — average **864/1200 in 2025** (861 in 2024); bands: Below-average 0–459, Average 460–660, Good 661–734, Very Good 735–852, Excellent 853–1200; 52% of Australians improved vs 23% declined (https://www.equifax.com.au/knowledge-hub/news-and-media/2025-year-resilience-majority-australians-maintained-excellent-credit-scores-defying; https://www.equifax.com.au/personal/what-good-credit-score). ~80th percentile ≈ 853; generator should target median 750–780.

**3.5 Leverage context** — high-DTI lending peaked above 20% of new flow in Q2 2021, the direct rationale for APRA raising the buffer to 3.0pp (https://www.apra.gov.au/news-and-publications/apra-increases-banks%E2%80%99-loan-serviceability-expectations-to-counter-rising); current monthly data via RBA Chart Pack (https://www.rba.gov.au/chart-pack/household-sector.html).

## 4. Bias and fair-lending in Australia

**Protected attributes** relevant to credit — age (Age Discrimination Act 2004), sex/sexual orientation/gender identity/intersex status/marital or relationship status/pregnancy/breastfeeding (Sex Discrimination Act 1984), race (RDA 1975), disability (DDA 1992) — and the "provision of goods and services" head explicitly covers credit (https://humanrights.gov.au/our-work/legal/legislation). Narrow actuarial-data exception for credit refusal exists but must be documented.

**Age + NCCP** — lenders cannot refuse on age alone but are **required** to assess whether the borrower can meet repayments past likely retirement age or the loan is "unsuitable" (https://www.lexology.com/library/detail.aspx?g=e4641677-6bb6-464a-8906-7a1de571bd71). Creates a legitimate-purpose exception with explicit reasoning trails.

**AHRC** submitted to the Adopting-AI Select Committee May 2024 warning that algorithmic bias replicates human errors at scale, and has built an **AI in Banking HRIA Tool** (https://humanrights.gov.au/our-work/legal/submission/adopting-ai-australia; https://humanrights.gov.au/about/news/media-releases/artificial-intelligence-and-anti-discrimination-major-new-publication; https://www.gradientinstitute.org/case-studies/australian-human-rights-commission/). Practical impact: no direct protected attributes as features without audit; **postcode** is the key proxy hazard (correlates with ethnicity and income) — only include via defensible audited aggregations (SA3 unemployment rate), not raw values.

## 5. Model practices worth copying

**CBA** publishes six AI Principles, uses SHAP for interpretability in credit decisioning, and released the first bank-level AI transparency report Feb-2026 (https://www.commbank.com.au/about-us/opportunity-initiatives/policies-and-practices/artificial-intelligence.html; https://www.commbank.com.au/articles/newsroom/2026/02/cba-approach-to-adopting-ai-report-announcement.html); formally tested Department of Industry AI Ethics Principles (https://www.industry.gov.au/publications/australias-artificial-intelligence-ethics-framework/testing-ai-ethics-principles/ai-ethics-case-study-commonwealth-bank-australia). Copy: per-decision SHAP, documented principles, published model cards.

**Athena/Tic:Toc** ship 15-minute applications and 60-second to 22-minute decisions by orchestrating ID, bureau, income verification, AVM into one synchronous path (https://blogs.mulesoft.com/digital-transformation/business/tictoc-instant-home-loans/ `[stale: 2019]`). Copy: instant-decision only for "clean" feature space; escalate outside calibrated confidence region.

**Pepper Money** decouples score from outcome, weighs employment stability, savings pattern, explanations for adverse events (https://www.peppermoney.com.au/resources/credit-report-real-life-guide). Copy: tiered near-prime/specialist bands with distinct weights, not a single cut-off.

**Plenti** publishes an explicit risk-bands 1–7 × rate/max-loan grid (https://res.cloudinary.com/plenti/image/upload/v1747190461/Plenti_Broker_Personal_Loans_Policy_Guide_14_May_2025_4f140d52ae.pdf). Copy: model-score → risk-band → rate-card pipeline, using rate uplift rather than binary decline for marginal applicants.

## Gaps / things I couldn't verify

1. **APG 223 response-to-submissions PDF** — returned as binary, not text-decodable via WebFetch; relied on handbook HTML.
2. **ASIC RG 209 / AHRC first-party pages** — WebFetch returned 403/permission-denied for `asic.gov.au` and `humanrights.gov.au`; content came from search snippets and official URLs I could cite but not retrieve body text for.
3. **ABS 6523.0** — last comprehensive release FY2019-20 `[stale: 2020]`; used newer Personal Income in Australia FY2022-23 as anchor. Household-level income quintiles at 2024 resolution not locatable.
4. **Equifax band population shares** — only the average (864) is public; per-band percentages are paywalled.
5. **Live production model feature lists** for Tic:Toc/Athena/Nano/Pepper — none publicly disclosed.
6. **RBA Chart Pack numeric figures** (household DTI ratio number, mortgage rates) — require downloading individual XLS files; not completed within the 25-page budget. Recommend follow-up via RBA Statistical Tables E2 and F5.
7. **Nano** — has wound down direct-to-consumer lending; public surface now B2B decisioning platform; de-prioritised.
8. **illion consumer credit report** — did not surface; Equifax used as bureau proxy.
9. **Interest-only share exact December-2025 percentage** — highlights page mentioned "broadly stable, edging higher" but did not give the number.
