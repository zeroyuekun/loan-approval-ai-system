## Intended Use

**Primary intended uses.** Real-time credit risk scoring of Australian personal and home loan applications: producing a calibrated approval probability, a recommended decision, adverse-action reason codes, and SHAP-based feature contributions. Designed to support — not replace — a licensed credit officer's "not unsuitable" assessment under NCCP Ch 3.

**Primary intended users.** Licensed loan officers conducting initial eligibility and serviceability assessments; compliance reviewers auditing decisioning consistency.

**Out-of-scope uses.** Business lending. Commercial/SMSF property. Reverse mortgages. Hardship renegotiation. Any decision with direct legal effect on the applicant without human officer review. Any dataset other than Australian residents.

## Factors

**Evaluation factors.** State of residence (8 values), employment type (4 values), applicant type (single/couple), sub-population segment (first-home buyer / upgrader / refinancer / personal / business / investor), age band (where derivable from supplied data).

**Relevant factors not measured.** Gender, ethnicity, sexual orientation, marital history, disability — not collected as features, by design. Proxies for these are constrained via postcode aggregation to SA3 only and monotonic constraints on income/credit/employment.
