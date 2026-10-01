"""Training subpackage — model training pipeline + feature engineering.

- ``trainer`` — main ModelTrainer entry point including Optuna
  hyperparameter optimisation, isotonic calibration, monotonic constraints
- ``feature_engineering`` — engineered interaction features
- ``feature_prep`` — pre-training feature preparation
- ``feature_selection`` — IV / SHAP-based feature pruning
- ``monotone_constraints`` — XGBoost monotonic constraint spec
- ``tstr_validator`` — Train-on-Synthetic, Test-on-Real validator

Lazy ``__init__.py`` — direct submodule imports are the preferred API:

    from apps.ml_engine.services.training.trainer import ModelTrainer
"""
