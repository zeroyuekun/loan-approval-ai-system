# ADR 002: XGBoost with monotonic constraints

## Status

Accepted

## Date

2026-03-23

## Context

The credit scoring model has to predict well and still be interpretable enough for regulators. Australian prudential and conduct regulators (APRA CPG 235, ASIC RG 209) require model behavior to be directionally consistent with economic intuition. For example, all else being equal, a higher credit score should never lower the approval probability. To be commercially viable, the model also needs strong discrimination (Gini > 0.70).

## Decision

Use XGBoost with monotonic constraints as the primary credit scoring algorithm, with Random Forest available as an alternative selected through `ModelVersion`.

The monotonic constraints fix the direction of each effect:

- `credit_score`: **+1** (higher score must never decrease approval probability)
- `annual_income`: **+1** (higher income must never decrease approval probability)
- `debt_to_income`: **-1** (higher DTI must never increase approval probability)
- `employment_length`: **+1** (longer employment must never decrease approval probability)
- `num_defaults_5yr`: **-1** (more defaults must never increase approval probability)
- `worst_arrears_months`: **-1** (worse arrears must never increase approval probability)

### Why not logistic regression?

- Lower discrimination (Gini ~0.55 vs ~0.75 for XGBoost).
- It can't capture non-linear interactions, such as LVR x DTI compounding risk at high levels.
- It needs manual feature engineering (WOE binning, interaction terms).
- A WOE/IV scorecard is still computed alongside the XGBoost model, for regulatory comparison and as a benchmark.

### Why not unconstrained XGBoost?

Without monotonic constraints, XGBoost can learn spurious patterns in sparse regions of the data. It might decide that `credit_score=900` is worse than `credit_score=850` only because there are very few training samples at 900. That breaks the regulatory expectation (APRA CPG 235, ASIC RG 209) that model behavior is directionally consistent with economic intuition. The constraints rule out these artifacts and still let the model learn non-linear magnitudes.

## Consequences

**Positive:**

- Directional effects match economic intuition, so the model meets the regulatory expectation.
- Stakeholders can check for themselves that "higher income = better outcome".
- Discrimination is strong: Gini ~0.73-0.77 on synthetic data.
- SHAP values are directionally consistent, which improves the counterfactual explanations.

**Negative:**

- The constraints cost a little AUC (~1-2% compared to unconstrained).
- The hyperparameter space is more complex than logistic regression's.
- Choosing which features get constraints takes care, because not every feature has a clear monotonic relationship.

## Alternatives considered

| Alternative | Reason for rejection |
|---|---|
| Logistic regression (WOE scorecard) | Lower discrimination (~0.55 Gini), cannot capture interactions |
| Unconstrained XGBoost | Directionally inconsistent in sparse regions, regulatory risk |
| LightGBM with monotonic constraints | Viable alternative, but XGBoost has broader regulatory acceptance in Australian lending |
| Neural network | Black box, hard to apply monotonic constraints to, regulatory resistance |
| Random Forest (alone) | Supported as an alternative, but lacks native monotonic constraint support |
