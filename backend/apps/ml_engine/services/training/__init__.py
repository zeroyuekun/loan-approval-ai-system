"""Training subpackage — model training pipeline + feature engineering.

Extracted from the flat ml_engine/services/ directory on 2026-05-26 as part
of PR-5 of the decomposition cycle (see
docs/superpowers/specs/2026-05-25-ml-engine-decomposition-design.md).

- ``trainer`` — main ModelTrainer entry point (1334 LOC) including Optuna
  hyperparameter optimisation, isotonic calibration, monotonic constraints
- ``feature_engineering`` — engineered interaction features
- ``feature_prep`` — pre-training feature preparation
- ``feature_selection`` — IV / SHAP-based feature pruning
- ``monotone_constraints`` — XGBoost monotonic constraint spec
- ``tstr_validator`` — Train-on-Synthetic, Test-on-Real validator

Lazy ``__init__.py`` — direct submodule imports are the preferred API:

    from apps.ml_engine.services.training.trainer import ModelTrainer
"""
