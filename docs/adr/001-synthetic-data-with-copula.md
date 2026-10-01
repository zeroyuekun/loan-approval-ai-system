# ADR 001: Synthetic data generation with Gaussian copula

## Status

Accepted

## Date

2026-03-23

## Context

The system needs realistic synthetic loan applications for model development, testing, and demos, because privacy and licensing constraints rule out real customer data. The synthetic features have to be correlated the way real ones are (higher income goes with higher credit scores, older applicants have longer employment histories). Without those correlations, model training produces meaningless results.

## Decision

Use a Gaussian copula to generate correlated synthetic features, calibrated against official Australian statistical sources:

- ATO income distributions by occupation and state
- Equifax credit score distributions by state and age band
- ABS employment data (employment length, type distributions)
- APRA lending indicators (LVR bands, DTI distributions)
- CoreLogic property data (median values by state)

The generator uses a sub-population mixture model with 6 segments:

1. First home buyer (FHB): younger, lower deposit, higher LVR
2. Upgrader: mid-career, existing equity, moderate LVR
3. Refinancer: established, existing mortgage, rate-seeking
4. Personal loan: unsecured, shorter term, higher rate
5. Business loan: variable income, asset-backed
6. Investor: higher income, multiple properties, interest-only

The data spans 12 quarters, which supports out-of-time validation (see ADR 004).

### Why not independent sampling?

Sampling each feature independently destroys the correlations between them. You get applicants like these:

- A 25-year-old could have 20 years of employment history
- A $30k income applicant could have a $2M property with zero deposit
- High credit scores would appear equally across all debt levels

These impossible combinations degrade the model and make its performance metrics misleading. A Gaussian copula keeps each feature's marginal distribution and still applies the pairwise correlations set in a correlation matrix.

### Why not real data?

- Privacy and licensing constraints prevent sharing or storing real customer data.
- Real data can't be published, so nobody else could reproduce the results.
- Real data can't be version-controlled or regenerated on demand.
- Calibrating against published aggregate statistics gives equivalent distributional fidelity for model development.

## Consequences

**Positive:**

- The same seed always produces an identical dataset.
- The data contains no PII, so it can be shared and committed to version control.
- Segment proportions can be adjusted, drift injected, and edge cases stress-tested.
- Distributions match published Australian statistics.

**Negative:**

- It can't capture non-linear real-world quirks such as COVID-era payment holidays.
- It needs recalibrating whenever ATO, ABS or APRA statistics are updated.
- The copula assumes an elliptical dependence structure, so it may miss tail dependencies.

## Alternatives considered

| Alternative | Reason for rejection |
|---|---|
| Independent random sampling | Destroys feature correlations and produces impossible combinations |
| Real anonymised data | Privacy/licensing constraints; not reproducible or shareable |
| GAN-based generation | Higher complexity, risk of mode collapse, harder to calibrate to known statistics |
| VAE-based generation | Same complexity concerns as GANs, and a less interpretable latent space |
