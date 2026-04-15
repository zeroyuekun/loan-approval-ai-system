# ADR-0003: Optuna over grid search

**Status:** Accepted
**Date:** 2026-04-15
**Deciders:** Neville Zeng

## Context

XGBoost has 9 hyperparameters that materially affect AUC on this dataset. Grid-searching the full space is combinatorial (even with 3 values per axis, 3^9 = 19,683 fits). Random search wastes budget. We want reproducible, budget-bounded hyperparameter optimisation that can be re-run on CI when the generator changes.

## Decision

We will use Optuna with the TPE sampler (`seed=42`), 50 trials default (configurable via `ML_OPTUNA_TRIALS`), 3-fold stratified cross-validation, and a 1200-second timeout plus a 600-second reserve for refitting the best model on the full training set. Pruning (MedianPruner) is currently disabled because trials are short; revisit if the budget increases.

## Alternatives Considered

- **Grid search** — Rejected: combinatorial explosion, wastes budget on known-bad corners.
- **Random search** — Rejected: no acquisition function, same budget yields worse frontier.
- **scikit-optimize Bayesian** — Rejected: less active project, fewer samplers, weaker pruning hooks.
- **Hyperopt** — Rejected: similar capabilities, less-clean API.

## Consequences

**Positive:**
- Budget-bounded (trials × time limit)
- Reproducible with fixed seed
- Study persistence lets us resume a crashed run
- Clear Pareto frontier visualisation when needed

**Negative:**
- Exact reproducibility requires matching Optuna + XGBoost minor versions
- `seed=42` only bounds sampling; refit shuffle order adds residual variance — acceptable given validation-set size
- First 10-15 trials are essentially random warmup; starving the budget (e.g., 20 trials) hurts quality sharply

## References

- `backend/apps/ml_engine/services/trainer.py` — hyperparameter search block (lines ~1100–1200)
- `ML_OPTUNA_TRIALS` in `backend/config/settings/base.py`
- Optuna docs: https://optuna.readthedocs.io/
