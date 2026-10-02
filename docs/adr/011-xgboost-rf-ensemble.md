# 011: XGBoost + Random Forest ensemble for loan scoring

- **Status:** Accepted
- **Date:** 2026-04-17
- **Decider:** @zeroyuekun

## Context

The system scores Australian loan applicants (approve/deny probability). The model has these requirements:

- **Calibrated probabilities:** downstream guardrails and NBO use the raw probability, not just the class.
- **Interpretable:** NCCP responsible-lending obligations require decision reasoning (SHAP explanations). Neural nets are harder to justify.
- **Tabular data:** ~30 engineered features; no text or images.
- **Training data volume:** synthetic + seeded, ~10k rows. Not big-data scale.
- **Inference latency:** p95 < 500ms per applicant.
- **CPU-only inference:** runs in a Celery worker container, no GPU.

## Decision

Use an ensemble of XGBoost and Random Forest:
- **XGBoost (primary):** gradient-boosted trees, tuned with Optuna. Usually the stronger single model on tabular data.
- **Random Forest (secondary):** bagged trees. Lower variance on edge cases, and a cheaper fallback if XGBoost's prediction is marginal or its model artifact fails to load.
- The active algorithm is selected by `ModelVersion.is_active`, so operators can swap models without code changes.

SHAP runs on the active model to produce the feature importances shown in the dashboard and in denial emails.

## Consequences

**Good:**
- Both models are well documented, CPU-friendly, and have mature SHAP integration.
- Two independent algorithms give a simple A/B lever during operation.
- Training, scoring, and explanation all run in-process in the Celery `ml` worker, so there is no external inference service to operate.

**Costs:**
- There are two model artifacts to version instead of one, mitigated by the `ModelVersion.is_active` flag.
- XGBoost adds a dependency footprint (~30 MB per worker image), which is acceptable given the single-image-per-queue deployment.
- Tree ensembles are less well calibrated out of the box than logistic regression. Isotonic calibration is applied post hoc and monitored with calibration plots in `/dashboard/model-metrics`.

## Alternatives considered

### A: Logistic regression only
- **Pros:** Simplest, perfectly interpretable, natively calibrated.
- **Cons:** Meaningfully lower AUC on the feature set (~0.80 vs ~0.87 Optuna-tuned).
- **Why not:** Approval quality matters more than implementation simplicity, and the lift justifies the complexity.

### B: LightGBM
- **Pros:** Often a touch faster and slightly better than XGBoost on some tabular benchmarks.
- **Cons:** Slightly smaller ecosystem around SHAP integration, and XGBoost was already familiar to the team.
- **Why not:** The incremental gain isn't worth the switch. Could revisit if inference latency becomes a constraint.

### C: Deep learning (TabNet / FT-Transformer)
- **Pros:** Strong on larger tabular datasets.
- **Cons:** Worse SHAP story, higher inference cost, overkill at our data size.
- **Why not:** The interpretability requirement makes this a poor fit, and the data volume doesn't justify the capacity.

## References

- `backend/apps/ml_engine/services/training/trainer.py`: model training entry point.
- `backend/apps/ml_engine/models.py`: `ModelVersion` with `is_active` flag.
- `backend/apps/ml_engine/services/scoring/predictor.py`: inference.
- Optuna tuning notes: `project_ml_accuracy_context.md` (internal).
