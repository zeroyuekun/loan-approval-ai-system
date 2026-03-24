# ADR 002: XGBoost with Monotonic Constraints

## Status

Accepted

## Date

2026-03-23

## Context

The system needs a credit scoring model that balances predictive power with regulatory interpretability requirements. Australian prudential and conduct regulators (APRA CPG 235, ASIC RG 209) require that model behavior is directionally consistent with economic intuition — for example, a higher credit score should never decrease approval probability, all else being equal. The model must also deliver strong discrimination (Gini > 0.70) to be commercially viable.

## Decision

Use XGBoost with monotonic constraints as the primary credit scoring algorithm. Also support Random Forest as an alternative algorithm selectable via `ModelVersion`.

Monotonic constraints enforce directional consistency:

- `credit_score`: **+1** (higher score must never decrease approval probability)
- `annual_income`: **+1** (higher income must never decrease approval probability)
- `debt_to_income`: **-1** (higher DTI must never increase approval probability)
- `employment_length`: **+1** (longer employment must never decrease approval probability)
- `num_defaults_5yr`: **-1** (more defaults must never increase approval probability)
- `worst_arrears_months`: **-1** (worse arrears must never increase approval probability)

### Why not logistic regression?

- Lower discrimination power (Gini ~0.55 vs XGBoost ~0.75)
- Cannot capture non-linear interactions (e.g., LVR x DTI compounding risk at high levels)
- Requires manual feature engineering (WOE binning, interaction terms)
- A WOE/IV scorecard is still computed alongside the XGBoost model for regulatory comparison and as a benchmark

### Why not unconstrained XGBoost?

Without monotonic constraints, XGBoost could learn spurious patterns from sparse regions of the data — for example, that `credit_score=900` is worse than `credit_score=850` because very few training samples exist at 900. This violates the regulatory expectation (APRA CPG 235, ASIC RG 209) that model behavior is directionally consistent with economic intuition. Monotonic constraints prevent these artifacts while preserving the model's ability to learn non-linear magnitudes.

## Consequences

**Positive:**

- Regulatory compliant — directional effects match economic intuition
- Explainable — stakeholders can verify "higher income = better outcome"
- Strong discrimination — Gini ~0.73-0.77 on synthetic data
- SHAP values are directionally consistent, improving counterfactual explanations

**Negative:**

- Monotonic constraints slightly reduce AUC (~1-2% compared to unconstrained)
- More complex hyperparameter space than logistic regression
- Requires careful selection of which features get constraints (not all features have a clear monotonic relationship)

## Alternatives Considered

| Alternative | Reason for rejection |
|---|---|
| Logistic regression (WOE scorecard) | Lower discrimination (~0.55 Gini), cannot capture interactions |
| Unconstrained XGBoost | Directionally inconsistent in sparse regions, regulatory risk |
| LightGBM with monotonic constraints | Viable alternative, but XGBoost has broader regulatory acceptance in Australian lending |
| Neural network | Black box, difficult to apply monotonic constraints, regulatory resistance |
| Random Forest (alone) | Supported as alternative, but lacks native monotonic constraint support |
