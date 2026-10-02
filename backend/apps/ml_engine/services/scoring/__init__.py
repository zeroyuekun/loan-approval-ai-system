"""Scoring subpackage — prediction hot path + supporting services.

Files in this subpackage cover everything from raw application to a
final scored Decision:

- ``predictor`` — main ModelPredictor (the hot path)
- ``decision_assembly`` — assembles raw scores into the structured Decision
- ``credit_policy`` — deterministic credit-policy rules
- ``policy_overlay`` / ``policy_recompute`` — overlay handling
- ``prediction_cache`` / ``prediction_diagnostics`` / ``prediction_explanations`` / ``prediction_features`` — supporting helpers
- ``adverse_action`` / ``reason_codes`` — adverse-action / NCCP reason codes
- ``shap_attribution`` — SHAP feature attribution
- ``counterfactual_engine`` — DiCE-style counterfactuals
- ``pricing_engine`` — risk-based pricing
- ``segmentation`` — product segmentation (home/personal)
- ``consistency`` — feature consistency checks

Lazy ``__init__.py`` — no re-exports. Direct submodule imports are the
preferred API:

    from apps.ml_engine.services.scoring.predictor import ModelPredictor
    from apps.ml_engine.services.scoring.counterfactual_engine import CounterfactualEngine

Re-exports here created circular imports when callers loaded eagerly;
the lazy init avoids that entirely.
"""
