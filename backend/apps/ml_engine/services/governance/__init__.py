"""Governance subpackage — model risk management, fairness, drift, validation.

Extracted from the flat ml_engine/services/ directory on 2026-05-26 as PR-3
of the decomposition cycle (see
docs/superpowers/specs/2026-05-25-ml-engine-decomposition-design.md).

Files in this subpackage cover the SR 11-7 / APRA CPG 235 / Banking Code
governance surface:

- ``calibration_validator`` — calibration validation against AIHW benchmarks
- ``drift_monitor`` — PSI / CSI / KS drift detection
- ``fairness_gate`` — pre-deployment EEOC four-fifths gate
- ``fairness_gate_mode`` — runtime fairness gate (warn / block / off)
- ``intersectional_fairness`` — intersectional disparate impact analysis
- ``model_card`` — model card generator (SR 11-7 / APRA CPG 235)
- ``mrm_compliance`` — compliance-status helpers
- ``mrm_dossier`` — full model risk management dossier writer
- ``outcome_tracker`` — outcome / vintage analysis
- ``promotion_gate_mode`` — runtime promotion gate (warn / block / off)
- ``regression_gate`` — performance regression detection
- ``shadow_scoring`` — challenger model shadow scoring

Direct imports from submodules are the preferred API:

    from apps.ml_engine.services.governance.fairness_gate import check_fairness_gate
    from apps.ml_engine.services.governance.mrm_dossier import write_dossier

This ``__init__.py`` deliberately does not re-export — the symbols across
12 modules don't share a single coherent public API surface, and keeping
the init lazy avoids importing every governance module whenever anyone
imports the package.
"""
