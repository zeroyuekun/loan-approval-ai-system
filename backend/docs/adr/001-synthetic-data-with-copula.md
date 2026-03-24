# ADR 001: Synthetic Data Generation with Gaussian Copula

## Status

Accepted

## Date

2026-03-23

## Context

The loan approval AI system requires realistic synthetic loan application data for model development, testing, and demonstration purposes. Access to real customer data is not available due to privacy and licensing constraints. The synthetic data must exhibit realistic correlations between features (e.g., higher income correlating with higher credit scores, older applicants having longer employment histories) to produce meaningful model training outcomes.

## Decision

Use a Gaussian copula to generate correlated synthetic features, calibrated against official Australian statistical sources:

- **ATO** income distributions by occupation and state
- **Equifax** credit score distributions by state and age band
- **ABS** employment data (employment length, type distributions)
- **APRA** lending indicators (LVR bands, DTI distributions)
- **CoreLogic** property data (median values by state)

The generator uses a sub-population mixture model with 6 segments:

1. **First Home Buyer (FHB)** — younger, lower deposit, higher LVR
2. **Upgrader** — mid-career, existing equity, moderate LVR
3. **Refinancer** — established, existing mortgage, rate-seeking
4. **Personal loan** — unsecured, shorter term, higher rate
5. **Business loan** — variable income, asset-backed
6. **Investor** — higher income, multiple properties, interest-only

A temporal dimension spans 12 quarters to support out-of-time validation (see ADR 004).

### Why not independent sampling?

Independent feature sampling destroys realistic correlations. When features are drawn independently:

- A 25-year-old could have 20 years of employment history
- A $30k income applicant could have a $2M property with zero deposit
- High credit scores would appear equally across all debt levels

These physically impossible combinations degrade model quality and produce misleading performance metrics. The Gaussian copula preserves each feature's marginal distribution while maintaining pairwise correlations defined in a correlation matrix.

### Why not real data?

- Privacy and licensing constraints prevent sharing or storing real customer data
- Inability to distribute data publicly for reproducibility
- Cannot version-control or regenerate real data on demand
- Calibration against published aggregate statistics provides equivalent distributional fidelity for model development

## Consequences

**Positive:**

- Fully reproducible — same seed produces identical datasets
- Shareable — no PII, can be committed to version control
- Controllable — can adjust segment proportions, inject drift, or stress-test edge cases
- Calibrated — distributions match published Australian statistics

**Negative:**

- Cannot capture non-linear real-world quirks (e.g., COVID-era payment holidays)
- Requires ongoing recalibration as ATO/ABS/APRA statistics are updated
- Copula assumes elliptical dependence structure, which may miss tail dependencies

## Alternatives Considered

| Alternative | Reason for rejection |
|---|---|
| Independent random sampling | Destroys feature correlations, produces impossible combinations |
| Real anonymised data | Privacy/licensing constraints, not reproducible or shareable |
| GAN-based generation | Higher complexity, mode collapse risk, harder to calibrate to known statistics |
| VAE-based generation | Similar complexity concerns as GANs, less interpretable latent space |
