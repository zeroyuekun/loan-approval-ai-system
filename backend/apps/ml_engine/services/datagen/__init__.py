"""Datagen subpackage — synthetic data generation + outcome simulation.

- ``data_generator`` — Gaussian copula synthetic data generator,
  calibrated against ATO / ABS / APRA / Equifax statistics
- ``feature_generator`` — behavioural feature generator used by data_generator
- ``loan_performance_simulator`` — post-outcome label simulator
- ``underwriting_engine`` — rules-based labelling engine

Lazy ``__init__.py`` — direct submodule imports are the preferred API:

    from apps.ml_engine.services.datagen.data_generator import DataGenerator
"""
