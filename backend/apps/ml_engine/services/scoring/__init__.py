"""Scoring subpackage — prediction hot path + supporting services.

Extracted from the flat ml_engine/services/ directory on 2026-05-26 as PR-4
of the decomposition cycle (see
docs/superpowers/specs/2026-05-25-ml-engine-decomposition-design.md).

Files in this subpackage cover everything from raw application to a
final scored Decision:

- ``predictor`` — main ModelPredictor (the hot path)
- ``decision_assembly`` — assembles raw scores into the structured Decision
- ``credit_policy`` — deterministic credit-policy rules
- ``policy_overlay`` / ``policy_recompute`` — overlay handling
- ``prediction_cache`` / ``prediction_diagnostics`` / ``prediction_explanations`` / ``prediction_features`` — supporting helpers
- ``adverse_action`` / ``reason_codes`` — adverse-action / NCCP reason codes
- ``shap_attribution`` — SHAP feature attribution
- ``stress_testing`` — APRA stress testing (+3% rate buffer)
- ``counterfactual_engine`` — DiCE-style counterfactuals
- ``pricing_engine`` — risk-based pricing
- ``segmentation`` — product segmentation (home/personal)
- ``consistency`` — feature consistency checks

Lazy ``__init__.py`` — no re-exports. Direct submodule imports are the
preferred API:

    from apps.ml_engine.services.scoring.predictor import ModelPredictor
    from apps.ml_engine.services.scoring.counterfactual_engine import CounterfactualEngine

PR-3 surfaced that re-exports create circular imports when callers
load eagerly. Lazy init avoids the problem entirely.
"""
