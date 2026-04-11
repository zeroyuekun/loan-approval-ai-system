# XGBoost lift over a naive scorecard

## One-line answer

On the most recent training run (`20260411_101947`, XGBoost), the main model scores **AUC 0.8703** on the held-out test set. A logistic-regression baseline trained on just three core credit features on the *same* train/test split scores **AUC 0.7688**. The measured lift is **+0.1015 AUC**.

That number is the answer to the standard credit-risk interview question — *"how much better is your model than a simple scorecard?"* — and it is recorded automatically on every training run so it cannot drift from marketing into reality.

## Why a baseline is worth the paragraph

A model with AUC 0.87 looks impressive in isolation. It looks different if you know the cheapest possible model on the same data scores 0.77. The *gap* is what tells you whether 79 features, XGBoost's histogram trees, monotonic constraints, Optuna tuning, isotonic calibration, and SHAP explainability actually justify their complexity — or whether the problem was easy and a 1-hour scorecard would have got you 90% of the way there.

In credit risk this question is usually answered with hand-wavy confidence. The fix is cheap: fit a logistic regression on the same split with a handful of core features, report the number, and let the delta speak. That is what this project does.

## The numbers, in context

| Metric | Main model (XGBoost) | LR baseline | Gap |
|---|---|---|---|
| AUC (test) | 0.8703 | 0.7688 | **+0.1015** |
| Features | 79 | 3 | — |
| Training rows | 36,868 | 36,868 | — |
| Temporal CV AUC (walk-forward mean) | 0.8695 | not measured | — |

The temporal CV number is close to the random-split AUC (0.8695 vs 0.8703), which means the model is not exploiting any accidental leakage from random partitioning. That is a separate sanity check from the baseline lift but is worth flagging in the same breath.

## What "the baseline" is

The LR baseline lives in [`trainer.py`](../apps/ml_engine/services/trainer.py) at `ModelTrainer._train_credit_score_baseline()`. It is deliberately minimal:

```python
_BASELINE_CANDIDATE_FEATURES = (
    "credit_score",
    "annual_income",
    "loan_amount",
    "debt_to_income",
)
```

On every training run, the trainer fits `sklearn.linear_model.LogisticRegression(max_iter=1000, solver="liblinear", random_state=42)` on whichever of those four features are present in the post-feature-engineering training matrix, scores it against the same test split, and records the AUC. The delta to the main-model AUC is stored alongside it.

Three design choices matter:

1. **Same train/test split.** No separate held-out set for the baseline. The lift number has to be apples-to-apples or it means nothing.
2. **Liblinear solver.** Deterministic, works on small feature sets, no tuning surface. The baseline must be a *reference point*, not a model to be optimised.
3. **Fail soft.** If none of the candidate features survive feature engineering (e.g. one was transformed into `log_annual_income` instead), the baseline returns `None` and the training run continues without a lift number. A missing baseline must never block a model release.

In the latest run, `annual_income` got dropped during feature engineering, so the baseline was fit on three features (`credit_score`, `loan_amount`, `debt_to_income`) instead of four. The result is still a valid reference point — a three-feature scorecard is what many Australian fintech affordability engines actually look like.

## Where to read the number yourself

The baseline results are stored on `ModelVersion.training_metadata`:

```python
from apps.ml_engine.models import ModelVersion
mv = ModelVersion.objects.order_by('-created_at').first()
md = mv.training_metadata
md["baseline_auc"]             # 0.7688
md["baseline_features"]        # ['credit_score', 'loan_amount', 'debt_to_income']
md["xgb_lift_over_baseline"]   # 0.1015
mv.auc_roc                     # 0.8703
```

No separate report, no stale markdown file — the source of truth is the model row that gets generated on every retrain.

## What a good lift range looks like

There is no universal right answer, but for a credit-scoring problem trained on realistic data:

| Lift | Read |
|---|---|
| +0.00 to +0.02 | The features are adding almost nothing. Either the problem is genuinely easy (rare) or the feature engineering is underpowered. Worth questioning why the fancy model is there at all. |
| +0.03 to +0.07 | Typical range for "we added data the bureau doesn't see". Real signal, justifies the complexity, but the baseline is doing most of the work. |
| **+0.08 to +0.15** | **The range this project lives in.** The main model is genuinely using the 76 extra features productively — behavioural signals, interactions, macro context. |
| +0.20 or more | Suspicious. Check for label leakage, target drift, or an accidentally hard baseline (e.g. the baseline is missing a feature it should have had). |

The 0.1015 lift here sits in the healthy middle of the "real work is happening" range. It is high enough to justify the complexity and low enough to be credible.

## What this number is *not*

It is not a real-world benchmark. Both models were trained and tested on the same synthetic distribution. A Lending Club or APRA-sourced dataset would almost certainly move both numbers, and probably move them different amounts — feature engineering generalises worse than a simple scorecard does. For the estimated real-world AUC, see [`tstr_validator.py`](../apps/ml_engine/services/tstr_validator.py) and the relevant section of [MODEL_CARD.md](MODEL_CARD.md).

It is also not a lift over the bureau score itself. `credit_score` is one of the baseline features, so the baseline is already using what a bureau-only model would use. This is stronger than "XGBoost beats bureau score" — it's "XGBoost beats a three-feature affordability scorecard that already has the bureau score in it."

## Reproducing the number

```bash
docker compose exec backend python manage.py train_model \
    --algorithm xgb \
    --data-path .tmp/synthetic_loans.csv
```

After the run completes, the baseline AUC and lift are in the new `ModelVersion` row and in the training log line that reads:

```
Baseline LR AUC: 0.7688 on ['credit_score', 'loan_amount', 'debt_to_income']; XGBoost lift: +0.1015
```

If you run the training command and the lift comes out significantly different from the numbers above, something changed — either the synthetic data generator, the feature engineering, or the XGBoost hyperparameters. That is exactly the kind of drift this file exists to make visible.
