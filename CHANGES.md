# Changelog

All notable changes to this project are documented here, in reverse chronological order. This log is intended to show the progression of the project — from initial scaffold to a production-grade system — for anyone reviewing the engineering work.

---

## 2026-03-20 — Customer Profile Flow, Edit Profile, and UI/UX Improvements

**Goal:** Fix the customer-facing loan application flow so customers see empty profile fields (not pre-filled fake data), can complete their own profile including identity documents, and get properly redirected to the loan application. Add a restricted "Edit Profile" page with fraud-prevention field locking, a customer account dropdown menu, Docker live reload, and various UI fixes.

### Why these changes were needed

The `seed_profiles` management command was populating ALL customer profile fields — personal details, identity documents, employment, income, assets — with random data. This meant customers logging in saw someone else's fake data pre-filled in their profile. Worse, the identity fields (DOB, residency, IDs) were marked read-only in the serializer, so customers could never submit their own identity documents through the API. The profile could never be completed by a customer.

The customer experience also had several broken paths: the "Complete Profile" button pointed to a non-existent dashboard route, numeric fields showing `0` appeared as empty due to JavaScript falsy-value bugs, and a stale React Query cache caused the profile to appear incomplete even after saving.

### Backend changes

**Serializer: identity fields made writable for customers**
- Removed `date_of_birth`, `residency_status`, `primary_id_type`, `primary_id_number`, `secondary_id_type`, `secondary_id_number`, `tax_file_number_provided`, and `is_politically_exposed` from `read_only_fields` in `CustomerProfileSerializer`
- These fields are required for the 100-point ID check under AML/CTF Act 2006 — customers must be able to submit them during initial profile completion
- Banking relationship fields (tenure, balances, products) remain read-only

**Seed command: reduced to bank-known data only**
- `seed_profiles` now only populates fields the bank would already have: `account_tenure_years`, `num_products`, `has_credit_card`, `has_mortgage`, `has_auto_loan`, `on_time_payment_pct`, `previous_loans_repaid`, `loyalty_tier`, `savings_balance`, `checking_balance`
- All customer-entered fields (personal, identity, employment, income, assets, liabilities, living situation) are left blank
- Existing seeded profiles were reset in the database

**Profile completeness check: fixed falsy-value bug**
- `is_profile_complete` and `missing_profile_fields` used Python truthiness checks (`all(getattr(self, f) for f in ...)`)
- `number_of_dependants = 0` was treated as "missing" because `0` is falsy
- Fixed to use explicit `val is None or val == ''` checks so `0` is correctly treated as a valid answer

### Frontend changes

**Customer dropdown menu**
- Replaced the bare logout icon in the customer header with a proper dropdown menu
- Shows avatar initial, full name, and email
- Contains "Edit Profile" link and "Sign Out" button
- Follows the same dropdown pattern used in the admin TopNav

**Edit Profile page (`/apply/profile/edit`)**
- New restricted profile editing page accessible from the customer dropdown
- **Locked fields (display only):** Name, email, date of birth, residency status, primary/secondary ID documents — with a notice explaining customers must visit a branch to change these (AML/CTF Act 2006 fraud prevention, consistent with CBA/ANZ/Westpac online banking)
- **Editable fields:** Phone, address, marital status, contact preference, employment, income, assets, liabilities, living situation — life-circumstance fields that Australian banks allow customers to update online
- ID document numbers are masked (show type + "****") in the locked section
- Redirects to `/apply` after saving

**Profile redirect fix**
- Changed the "Go to My Profile" link in `ApplicationForm` from `/dashboard/profile` (didn't exist) to `/apply/profile`

**Falsy-value fixes on profile page**
- Changed `form.number_of_dependants || ''` to `form.number_of_dependants ?? ''` across all numeric fields
- Applied to both the `useEffect` form initialisation and the input `value` props
- `0` now displays correctly instead of showing as empty

**Stale cache fix**
- Profile page now `await`s `queryClient.invalidateQueries` before redirecting to `/apply/new`
- `ApplicationForm` profile query uses `staleTime: 0` to always refetch on mount
- Prevents the race condition where `/apply/new` loaded stale cached profile data showing `is_profile_complete: false`

**Application status page**
- Removed "Back" button
- Added "Finished" button (bottom-right, blue) linking to `/apply`
- Added spacing between the last card and the button

**Incomplete profile warning**
- Removed "Go Back" button from the incomplete profile card in `ApplicationForm`
- Added "Finished" button (bottom-right) linking to `/apply`

**Apply page spacing**
- Added proper spacing between the "Apply Now" button row and application cards
- Removed the `+` icon from the "Apply Now" button

**Customers table**
- Added border between "All Customers" heading and the table

**Model metrics**
- Changed "Active" badge to green (`success` variant)
- Matched badge sizes between version and active badges

### Hydration error fixes

**Badge component (`badge.tsx`)**
- Changed from `<div>` to `<span>` to fix "div cannot be a descendant of p" hydration error

**CardDescription component (`card.tsx`)**
- Changed from `<p>` to `<div>` to fix "p cannot contain a nested div" hydration error
- `CardDescription` was being used with block-level children (badges, flex containers) in `ThresholdChart`

### Infrastructure

**Docker live reload for frontend**
- Added `command: npm run dev` override in `docker-compose.yml` for the frontend service
- Added `WATCHPACK_POLLING: "true"` for Windows Docker file system compatibility
- Mounted `./frontend/public:/app/public` volume
- Changes to `frontend/src/` now hot-reload without requiring container rebuilds

### Files changed
- `backend/apps/accounts/serializers.py` — identity fields writable
- `backend/apps/accounts/models.py` — fixed profile completeness check
- `backend/apps/accounts/management/commands/seed_profiles.py` — bank-known data only
- `frontend/src/app/apply/layout.tsx` — customer dropdown menu
- `frontend/src/app/apply/profile/edit/page.tsx` — new edit profile page
- `frontend/src/app/apply/profile/page.tsx` — falsy-value fixes, cache fix
- `frontend/src/app/apply/page.tsx` — spacing, button cleanup
- `frontend/src/app/apply/status/[id]/page.tsx` — finished button, removed back
- `frontend/src/components/applications/ApplicationForm.tsx` — redirect fix, cache fix, button changes
- `frontend/src/app/dashboard/customers/page.tsx` — table header border
- `frontend/src/app/dashboard/model-metrics/page.tsx` — green active badge, badge sizing
- `frontend/src/components/ui/badge.tsx` — div to span (hydration fix)
- `frontend/src/components/ui/card.tsx` — p to div (hydration fix)
- `docker-compose.yml` — frontend dev mode, live reload

---

## 2026-03-19 — Pipeline Integrity Fixes, Risk Analytics, Feature Interactions, and Self-Healing Validation

**Goal:** Fix 4 critical pipeline contradictions found during a team code review, add Basel III risk analytics (EL = PD x LGD x EAD, stress testing, conformal prediction), feature interaction engineering, credit-score-sensitive LGD, and implement self-healing validation with realistic Australian demo scenarios.

### Why these changes were needed

A 3-agent code review team (credit risk analyst, QA engineer, mortgage broker) audited the full ML pipeline and found that while the model architecture was sound, several components were silently contradicting each other. These weren't accuracy problems — they were correctness problems. The model was producing predictions based on inconsistent assumptions between training and inference.

The risk analytics additions transform the model output from a binary approve/deny into the kind of dollar-value risk assessment that APRA-regulated banks actually use for capital allocation and pricing.

### Critical bug fixes

**C1: Reject inference label removed from training output**
- **What:** The `_reject_inference_label` column (NaN for approved, 0/1 for denied) was persisting in the training CSV. It wasn't entering the model features by coincidence (not listed in `NUMERIC_COLS`), but it was one accidental inclusion away from catastrophic target leakage.
- **Why it matters:** This column is a near-perfect proxy for the target variable. If any automated feature selection tool or future developer included it, the model would achieve 99%+ AUC by cheating — learning "if this column exists, deny" rather than learning actual risk patterns.
- **Fix:** Column stored as instance attribute `self.reject_inference_labels`, dropped from DataFrame before return.

**C2: State field now written to database records**
- **What:** The generator produces state-aware data (8 Australian states with different income/credit/property profiles), and the model trains on it. But `generate_data.py` never passed `state` to `LoanApplication.objects.create()`, so all database records defaulted to NSW.
- **Why it matters:** 67% of production predictions were using the wrong state features. A QLD applicant was being predicted as if they lived in Sydney, with Sydney income expectations and credit score adjustments.
- **Fix:** Added `state=row['state']` to DB creation. Removed silent NSW default in predictor — missing state now raises an error rather than silently defaulting.

**C3: Missing value imputation aligned between trainer and predictor**
- **What:** The trainer imputed missing `monthly_expenses` with the training set median (~$2,500). The predictor imputed with 0 (via `float(application.monthly_expenses or 0)`).
- **Why it matters:** For the ~4% of applications with missing expenses, the predictor fed the model a value (0) that the scaler had never seen during training. The `expense_to_income` derived feature became 0.0, making the model think these applicants spend nothing — and approve them more readily.
- **Fix:** Imputation values stored in the model bundle during training. Predictor loads them and uses the same values.

**C4: WOE scorecard computed on raw data (not scaled)**
- **What:** The WOE/IV analysis was running on StandardScaler-transformed features. Bin edges were in z-score units (e.g., "credit_score between -1.2 and 0.4") instead of real units.
- **Why it matters:** A WOE scorecard must be interpretable — APRA requires that a credit officer can explain every decision. A scorecard with z-score bins fails this requirement. The AUC figure was also misleading because it was computed in-sample.
- **Fix:** WOE computed on raw data before scaling. Bins now in real units (e.g., credit_score 650-750). AUC reported on held-out test set.

### Monotonic constraint corrections

**H1: Removed LVR monotonic constraint**
- **What:** `lvr: -1` (higher LVR = lower approval) was forcing the model to treat all non-home loans (LVR=0.0) as "best possible LVR" — more approvable than any home loan with a deposit.
- **Why:** LVR=0.0 for a personal loan means "no property", not "zero risk". The monotonic constraint was inverting the intended behavior for 52% of the dataset.

**H2: Removed HECS monotonic constraint**
- **What:** `has_hecs: -1` forced HECS to always reduce approval probability. But the actual effect is income-mediated: a $200K earner with HECS repaying $583/month is barely affected; a $50K earner repaying $146/month is significantly affected.
- **Why:** The constraint prevented the model from learning this nuance. High-income HECS holders were being unfairly penalised.

### Risk analytics additions

**Expected Loss (EL = PD x LGD x EAD) — Basel III / APRA APS 113**
- Added LGD lookup table by loan purpose and LVR band (home 15-40%, personal 50-75%, business 80%)
- Credit-score-sensitive LGD: better credit reduces LGD by up to 20% (cooperative recovery), worse credit increases it. Credit score 900 → LGD 0.213 vs credit 600 → LGD 0.227 on same loan.
- EL computed for every prediction: the dollar amount the bank expects to lose
- This transforms the model from binary approve/deny into a dollar-value risk assessment

**Stress Testing — APRA APS 110**
- 4 adverse scenarios: interest rate +2%, income -15%, property value -20%, combined
- Re-runs the prediction under each scenario
- Shows how the approval probability degrades under stress

**Conformal Prediction — confidence intervals**
- Instead of just "72% probability", outputs "72% [65%, 79%] at 95% confidence"
- Uses split conformal prediction with nonconformity scores from calibration set

**Adversarial Validation**
- Trains a classifier to distinguish training from test data
- If AUC > 0.55, flags a distribution mismatch
- Sanity check that runs automatically during training

**Concentration Risk — APRA APS 221**
- HHI (Herfindahl-Hirschman Index) by state, purpose, employment type
- Flags if any segment exceeds 40% of portfolio

### Feature engineering improvements

**4 interaction features (standard in Big 4 scorecards)**
- `lvr_x_dti`: compounding leverage risk — high LVR + high DTI is much riskier than either alone (RBA FSR 2022 finding: borrowers with both high DTI and high LVR were ~4x more likely to report mortgage stress)
- `income_credit_interaction`: joint creditworthiness x capacity signal using log-scaled income x normalised credit score
- `serviceability_ratio`: monthly buffer after all commitments as a ratio — directly models the bank's serviceability assessment
- `employment_stability`: employment type quality (permanent=1.0, casual=0.4) weighted by log tenure — captures that a casual worker with 5 years is very different from a casual with 6 months

**Monotonic constraints updated for interaction features**
- `lvr_x_dti: -1` (compounding leverage always hurts)
- `income_credit_interaction: 1` (higher combined creditworthiness always helps)
- `serviceability_ratio: 1` (more buffer always helps)
- `employment_stability: 1` (more stability always helps)

**Discrete feature WOE binning fix**
- Features with <= 10 unique values (e.g., number_of_dependants with 5 values: 0-4) now bin by unique value instead of quantile
- Prevents degenerate bins where multiple quantile edges collapse to the same value
- Dependants now correctly produces 5 WOE bins (one per value) instead of 2-3 collapsed bins

### Self-healing pipeline validation

Added `validate_pipeline_consistency()` that runs after every training:
- Checks CATEGORICAL_COLS match between trainer and predictor
- Verifies all monotonic constraint features exist in the feature set
- Confirms imputation values are stored in the model bundle
- Detects target-leaking columns in training data
- Raises clear errors listing all failures

### Demo scenarios (6 named Australian applicants)

| # | Name | State | Scenario | Expected |
|---|------|-------|----------|----------|
| 1 | Sarah Chen | NSW | FHB couple, $152K, $680K home loan, HECS | Approved |
| 2 | Liam O'Connor | QLD | Regional upgrader, $185K, $520K loan | Approved |
| 3 | Marco Rossi | VIC | Self-employed tradie, $135K, $620K loan | Borderline |
| 4 | Chloe Martin | VIC | Casual 8mo, $52K, personal loan | Denied (tenure) |
| 5 | Raj Patel | NSW | Investor DTI 6.2, $210K, $1.3M loan | Denied (APRA DTI) |
| 6 | Tom Anderson | SA | Bankruptcy, $78K, personal loan | Denied (bankruptcy) |

### Files changed
- `backend/apps/ml_engine/services/data_generator.py` — drop leak column, copula validation, dead code removal
- `backend/apps/ml_engine/services/trainer.py` — imputation storage, raw WOE, constraints fix, fairness, self-healing
- `backend/apps/ml_engine/services/predictor.py` — state fix, imputation, EL calculation, stress testing, conformal prediction
- `backend/apps/ml_engine/services/metrics.py` — WOE test AUC, PSI epsilon, adversarial validation, concentration risk, EL computation
- `backend/apps/ml_engine/management/commands/generate_data.py` — state in DB, demo scenarios
- `backend/tests/conftest.py` — state in fixtures
- `README.md` — risk analytics documentation, limitations section
- `CHANGES.md` — this entry

---

## 2026-03-19 — WOE Scorecard, Monotonic Constraints, and Reject Inference

**Goal:** Add the three credit risk techniques that real APRA-regulated banks use but most ML projects miss — WOE/IV scorecards for regulatory interpretability, monotonic constraints for domain-consistent predictions, and reject inference to correct for selection bias.

### Why these techniques matter

A recruiter at a bank will look at a loan approval model and ask: "Where's the scorecard?" XGBoost is great for prediction but regulators require interpretability. A credit officer needs to explain to AFCA exactly why someone was denied — "the 247th tree said no" doesn't satisfy the Banking Code of Practice paragraph 81 requirement to provide reasons for denial.

### What changed

**Weight of Evidence (WOE) / Information Value (IV) scorecard**
- WOE transformation: bins each feature and computes log odds ratio per bin — the standard methodology under Basel III / APRA APS 113
- Information Value for automatic feature ranking: IV < 0.02 (drop), 0.02-0.10 (weak), 0.10-0.30 (medium), 0.30-0.50 (strong), > 0.50 (check for leakage)
- Full WOE logistic regression scorecard built alongside XGBoost — base score 600, PDO (Points to Double Odds) 20
- Scorecard can be printed on a single page — a key regulatory requirement for APRA model documentation
- Scorecard AUC ~0.78 (lower than XGBoost's ~0.93, but fully interpretable — this is the tradeoff banks actually make)

**Monotonic constraints on XGBoost**
- 11 domain-enforced monotonic relationships: credit_score (positive), income (positive), DTI (negative), employment_length (positive), bankruptcy (negative), etc.
- Prevents the model from learning spurious non-monotonic patterns from noise
- Regulatory expectation: APRA and ASIC expect that a model won't approve someone with a lower credit score over an identical applicant with a higher score

**Reject inference (parcelling method)**
- In real lending, outcomes are only observed for approved loans — denied applicants never get a chance to prove they'd repay
- The generator uses the parcelling method to estimate hypothetical outcomes for denied applicants
- ~50% of denied applicants estimated as "would have repaid" (consistent with banking literature)

### Files changed
- `backend/apps/ml_engine/services/metrics.py` — `compute_woe_iv`, `compute_all_woe_iv`, `build_woe_scorecard`
- `backend/apps/ml_engine/services/trainer.py` — `_build_monotonic_constraints`, WOE scorecard in training output
- `backend/apps/ml_engine/services/data_generator.py` — reject inference parcelling

---

## 2026-03-19 — Synthetic Data Calibration (Gaussian Copula + Mixture Model + Geographic Segmentation)

**Goal:** Make the synthetic training data statistically realistic by calibrating every distribution parameter against official Australian government and industry statistics, rather than using estimated values.

### Why this matters

Most ML portfolio projects generate synthetic data with guessed distributions, train a model, get 99% accuracy, and call it done. A recruiter who's worked at a bank knows those numbers mean the data was trivial. This project takes a different approach: every parameter is sourced from a published statistic, and the generator uses the same techniques (copula, mixture models) that credit risk teams at Moody's Analytics and the Big 4 banks use for synthetic data generation.

### What changed

**Gaussian copula for correlated feature generation**
- 7x7 correlation matrix calibrated from ATO/ABS/Equifax cross-tabulations
- Income <-> Credit Score: r=0.26, Income <-> Expenses: r=0.34, Age <-> Employment: r=0.19
- Without this, the model trains on artificially independent features — like assuming income has nothing to do with credit score

**Sub-population mixture model with 5 borrower archetypes**
- First home buyers (18%): young, high LVR, moderate income
- Upgraders (20%): mid-career, moderate LVR, excellent credit
- Refinancers (10%): established, low LVR, longest employment
- Personal borrowers (37%): auto/education/personal loans
- Business borrowers (15%): older, self-employed skew

**Geographic segmentation across all 8 Australian states/territories**
- State profiles with income multipliers (WA 1.12x mining, ACT 1.25x public service, TAS 0.88x)
- Equifax credit score adjustments by state (ACT +51, NT -20 from national average)
- State-level validation: ACT highest credit (905), NT lowest (824), matches Equifax 2025

**Calibration against 11 official sources**
- ATO Taxation Statistics 2022-23, ABS Employee Earnings Aug 2025, ABS Characteristics of Employment Aug 2025, ABS Lending Indicators Dec Q 2025, APRA Quarterly ADI Property Exposures Sep Q 2025, Equifax 2025 Credit Scorecard, RBA Financial Stability Review Oct 2025, CoreLogic 2025, ABS Total Value of Dwellings Dec Q 2025, Melbourne Institute HEM 2025/2026, AFSA 2024-25

### Validation results

| Parameter | Before | After | Target | Source |
|-----------|--------|-------|--------|--------|
| Income (single) | $70K est. | $79,821 | $74,100 | ABS 2025 |
| Credit score | ~846 est. | 875 | 864 | Equifax 2025 |
| LVR >= 80% | uncalibrated | 32.1% | 30.8% | APRA Sep Q 2025 |
| Approval rate | uncalibrated | 66.3% | 65-75% | Big 4 banks |
| Employment split | 55/15/20/10% est. | 68/12/12/8% | 68/12/12/8% | ABS 2025 |

### Files changed
- `backend/apps/ml_engine/services/data_generator.py` — major rewrite
- `backend/apps/ml_engine/services/trainer.py` — `state` categorical column
- `backend/apps/ml_engine/services/predictor.py` — `state` in feature dict
- `backend/apps/loans/models.py` — `AustralianState` choices and `state` field
- `backend/apps/loans/serializers.py` — `state` in serializer fields

---

## 2026-03-18 — Banking Metrics, Drift Monitoring, and Fairness Analysis

**Goal:** Add banking-industry-standard model evaluation metrics that go beyond accuracy/F1, implement per-application drift detection, and add fairness metrics with disparate impact analysis.

### Why these metrics matter

A model with 90% accuracy sounds good until you realise it's approving loans that default and denying loans that would have been profitable. Banks don't use accuracy — they use Gini (discrimination power), KS (separation between good and bad), PSI (distribution shift), and calibration (are the probabilities trustworthy). Adding these shows understanding of what matters in production credit risk.

### What changed

**Banking metrics:** Gini coefficient, KS statistic, log loss, ECE (Expected Calibration Error), decile lift analysis, threshold sweep with 3 optimal strategies (F1, Youden's J, cost-matrix with banking 5:1 FP:FN ratio)

**PSI drift monitoring:** Batch PSI comparing training vs production distributions, per-feature PSI to identify which features drifted, APRA CPG 235 thresholds (<0.10 stable, 0.10-0.25 moderate, >=0.25 retrain)

**Per-application drift detection:** Z-score against training distribution, flags at 3σ (warning) and 4σ (drift), triggers human review

**Fairness metrics:** Per-group TPR/FPR, disparate impact ratio, EEOC 80% rule check, equalized odds difference

### Files changed
- `backend/apps/ml_engine/services/metrics.py` — all new metric computations
- `backend/apps/ml_engine/services/predictor.py` — drift detection
- `backend/apps/ml_engine/services/trainer.py` — reference distribution, fairness
- `backend/apps/ml_engine/views.py` — drift monitoring endpoint

---

## 2026-03-17 — Model Training Pipeline Hardening (Calibration, SHAP, Overfitting Detection)

**Goal:** Make the model training pipeline production-grade with probability calibration, per-prediction explainability, and overfitting safeguards.

### Why calibration matters

An XGBoost model might output "0.72 probability of approval" — but that doesn't mean 72 out of 100 applicants with that score actually get approved. Isotonic calibration warps the raw probabilities to match observed frequencies, making the numbers meaningful for risk-based pricing and regulatory reporting.

### What changed

**Isotonic probability calibration:** Custom `_CalibratedModel` wrapper, fitted on held-out validation set (10% of data), 80/10/10 split to prevent leakage

**SHAP feature explanations:** TreeExplainer for per-prediction SHAP values, extracts underlying estimator from calibration wrapper

**XGBoost training improvements:** RandomizedSearchCV (50 iterations), `scale_pos_weight` for class imbalance, early stopping (20 rounds), thread management for oversubscription prevention

**Overfitting detection:** Train vs test AUC comparison, warning if gap > 0.05

**Data consistency checker:** Cross-field validation (deposit vs property value, DTI vs income/loan), blocks predictions on logically inconsistent inputs

**Model security:** SHA-256 hash verification, path traversal protection, thread-safe caching

### Files changed
- `backend/apps/ml_engine/services/trainer.py` — calibration, RandomizedSearchCV, overfitting
- `backend/apps/ml_engine/services/predictor.py` — SHAP, hash verification, caching
- `backend/apps/ml_engine/services/consistency.py` — cross-field validation

---

## 2026-03-16 — Email Guardrails System (10 Deterministic Checks)

**Goal:** Replace the basic email validation with a comprehensive guardrail system that catches compliance violations, hallucinated numbers, AI-sounding language, and formatting issues before any email goes out.

### Why deterministic checks over LLM review

Sending every email to an LLM for review is expensive, slow, and unreliable (LLMs hallucinate bias flags). Deterministic regex checks are free, instant, and consistent. The LLM is reserved for ambiguous cases that actually need interpretation — a 10x cost reduction with better reliability.

### What changed

10-check pipeline: prohibited language (discrimination acts), hallucinated numbers (validated against pricing engine), tone, AI giveaway language (30+ patterns), professional terms, plain text only, word count, required regulatory elements (Banking Code, AFCA, cooling-off), sign-off structure, sentence rhythm

**Pricing engine:** Realistic Australian lending rates by purpose and credit band, ASIC RG 262 comparison rate calculations

### Files changed
- `backend/apps/email_engine/services/guardrails.py`, `email_generator.py`, `pricing.py`, `prompts.py`

---

## 2026-03-15 — Bias Detection Redesign (3-Layer Tiered System)

**Goal:** Replace the naive "send everything to an LLM" bias check with a tiered deterministic-first approach that's cheaper, faster, and more reliable.

### Why 3 layers

Layer 1 (regex) catches 90% of issues at zero API cost. Layer 2 (LLM) only fires for the 10% that need interpretation. Layer 3 (human) catches the cases where the LLM isn't confident. This matches how real compliance departments work — junior analysts screen, senior analysts review flags, compliance officers sign off.

### What changed

**Layer 1:** Deterministic regex, weighted scoring 0-100, zero API cost
**Layer 2:** Claude Sonnet for moderate flags (60-80), sorts false positives from real issues
**Layer 3:** Human escalation for low-confidence LLM reviews (<0.70)
**Orchestrator:** Zombie run detection, auto-recovery after 5 minutes

### Files changed
- `backend/apps/agents/services/bias_detector.py`, `marketing_agent.py`, `orchestrator.py`, `tasks.py`

---

## 2026-03-14 — Next Best Offer Engine and Marketing Agent

**Goal:** When an applicant is denied, automatically generate alternative product suggestions and a marketing email — with its own compliance pipeline.

### Why NBO matters

A denial is a lost customer. If they don't qualify for a $600K home loan, they might qualify for a $400K loan with a longer term, or a secured personal loan. The NBO engine analyses why they were denied and suggests alternatives. This is standard practice at every major lender.

### What changed

**NBO engine:** Analyses denial reasons, generates up to 3 alternatives with estimated rates
**Marketing agent:** Claude generates professional follow-up email, separate bias check (tighter thresholds)
**Pipeline integration:** NBO + marketing fires automatically after denial

### Files changed
- `backend/apps/agents/services/next_best_offer.py`, `marketing_agent.py`, `orchestrator.py`

---

## 2026-03-13 — Frontend Polish and Customer Experience

**Goal:** Improve the frontend UI, add SHAP visualisation, implement agent status polling, and enforce customer profile completeness.

### What changed

- SHAP feature importance bar chart on application detail page
- Drift warning display for unusual applicant values
- `useAgentStatus` polling hook (2-second intervals during pipeline)
- Customer profile completeness enforcement before loan submission
- UI cleanup (unused CSS, button variants)

### Files changed
- `frontend/src/components/applications/ApplicationDetail.tsx`
- `frontend/src/hooks/useAgentStatus.ts`
- `frontend/src/app/globals.css`, `frontend/src/components/ui/button.tsx`

---

## 2026-03-12 — Initial Scaffold

**Goal:** Build the full project structure with all Django apps, frontend, Docker configuration, and basic functionality end-to-end.

### What was built

**Backend:** 5 Django apps (accounts, loans, ml_engine, email_engine, agents), JWT auth with Argon2, PII encryption, Celery with 3 queues, rate limiting, audit logging

**Frontend:** Next.js 15, React 19, shadcn/ui, TanStack Query, JWT auth flow

**Infrastructure:** Docker Compose (7 containers), PostgreSQL 17, Redis, separate ML/IO workers

**ML Pipeline:** XGBoost + Random Forest, synthetic data generator, GridSearchCV, model versioning

### Files created
- Full project structure: ~50 Python files, ~20 TypeScript/React files, 7 Docker configs
