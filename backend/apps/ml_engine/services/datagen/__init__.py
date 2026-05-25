"""Datagen subpackage — synthetic data generation + outcome simulation.

Extracted from the flat ml_engine/services/ directory on 2026-05-26 as part
of PR-5 of the decomposition cycle (see
docs/superpowers/specs/2026-05-25-ml-engine-decomposition-design.md).

- ``data_generator`` — Gaussian copula synthetic data generator (1565 LOC),
  calibrated against ATO / ABS / APRA / Equifax statistics
- ``feature_generator`` — behavioural feature generator used by data_generator
- ``loan_performance_simulator`` — post-outcome label simulator
- ``underwriting_engine`` — 1000-line rules-based labelling engine

Lazy ``__init__.py`` — direct submodule imports are the preferred API:

    from apps.ml_engine.services.datagen.data_generator import DataGenerator
"""
