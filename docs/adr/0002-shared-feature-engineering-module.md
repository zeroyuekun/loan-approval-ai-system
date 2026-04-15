# ADR-0002: Shared feature-engineering module

**Status:** Accepted
**Date:** 2026-04-15
**Deciders:** Neville Zeng

## Context

Train/serve skew is the most common cause of silent ML failure: a derived feature gets computed one way during training and subtly differently at inference, and the model's calibration goes out of distribution without anyone noticing. This system has 30+ derived features (LVR, serviceability ratio, HEM surplus, credit-card burden, bureau risk score, subgroup interactions).

## Decision

We will compute every derived feature through one function — `apps.ml_engine.services.feature_engineering.compute_derived_features` — imported by both the trainer and the predictor. The function is pure: same input DataFrame → same output DataFrame. Imputation defaults, bucket boundaries, and formula constants live inside this module and are bundled alongside the model artefact (`imputation_values` in the joblib bundle).

## Alternatives Considered

- **Duplicate code** between `trainer.py` and `predictor.py` — Rejected: the precise failure mode we are trying to avoid.
- **Dedicated feature store (Feast)** — Rejected for now: adds operational complexity (online/offline stores, registry service) disproportionate to current scale. Re-evaluate if we move off synthetic data or if feature logic grows beyond one module.
- **SQL view** — Rejected: we want feature computation in Python so it is testable and portable to notebooks.

## Consequences

**Positive:**
- Zero train/serve skew by construction
- Feature invariants testable as pure-function unit tests
- Model bundles are self-contained: imputation values travel with the model

**Negative:**
- Tight coupling: trainer and predictor must run on the same library versions and Python minor
- Bundling imputation values into the joblib makes model artefacts larger by a few KB (acceptable)
- Migrating to a real feature store later means extracting this module behind a new interface — one future refactor we accept

## References

- `backend/apps/ml_engine/services/feature_engineering.py`
- `backend/apps/ml_engine/services/trainer.py` (imports `compute_derived_features`)
- `backend/apps/ml_engine/services/predictor.py` (imports same)
- `backend/tests/test_feature_engineering.py`, `test_feature_consistency.py`
