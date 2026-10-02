# Model training workflow

<!-- TODO: update after Optuna migration — GridSearchCV for RF should probably move to Optuna too -->

## Objective

Train and retrain Random Forest (RF) and XGBoost classification models on loan application data to predict approval/denial outcomes.

## Required inputs

- Loan dataset in CSV format (synthetic via `python manage.py generate_data`, see `workflows/data_generation.md`, or a real export)
- Required columns: `income`, `credit_score`, `loan_amount`, `debt_to_income`, `employment_length`, `purpose`, `home_ownership`, `annual_income`, `has_cosigner`, `approved`

## Tools

| Tool | Location | Purpose |
|------|----------|---------|
| Management command | `backend/apps/ml_engine/management/commands/train_model.py` | `python manage.py train_model`: same path as the dashboard's Train Model button (training lock, `ModelVersion` registration, governance gates) |
| Django service trainer | `backend/apps/ml_engine/services/training/trainer.py` | Training service used by the command and the Celery task |

## Steps

1. **Load data.** Read the CSV from `--data-path` (default: `.tmp/synthetic_loans.csv`).
2. **Preprocess.**
   - Encode categorical features (`purpose`, `home_ownership`) with `LabelEncoder` or `OneHotEncoder`
   - Scale numeric features (`income`, `credit_score`, `loan_amount`, `debt_to_income`, `employment_length`, `annual_income`) with `StandardScaler`
   - Handle missing values: drop rows with >50% missing, and impute the rest with the median (numeric) or mode (categorical)
3. **Split.** 80% train / 10% validation / 10% test, using `train_test_split` with `random_state=42` and `stratify=y`.
4. **Train with hyperparameter optimization.**
   - RF: `GridSearchCV` with params `n_estimators` [100, 200], `max_depth` [10, 20, None], `min_samples_split` [2, 5]
   - XGBoost: `Optuna` Bayesian optimization (TPE sampler, 50 trials) with a wider search space: max_depth [4-10], learning_rate [0.01-0.15], reg_lambda [1-50]
   - Use 3-fold stratified cross-validation, scoring on `roc_auc`
5. **Evaluate.** Run the best model against the validation set first, then the test set. Print the classification report, confusion matrix, and AUC-ROC.
6. **Save.** The trainer serializes the model bundle with `joblib.dump()` to `backend/ml_models/` and registers a `ModelVersion`; it is activated only if the governance gates pass.

## Expected outputs

- `.joblib` model file (e.g., `rf_model_20260312.joblib`)
- Metrics report printed to stdout and optionally saved to `.tmp/model_report.json`
- Preprocessor artifacts (scaler, encoders) saved alongside the model

## Watch out for

**Class imbalance:** If the approval rate is heavily skewed (>80% or <20%), use `class_weight='balanced'`, SMOTE on training data only, or adjust the decision threshold from the ROC curve. Never apply SMOTE to val/test sets.

**Overfitting:** Compare validation and test accuracy. A gap of >5% means the model is overfit. Reduce `max_depth`, increase `min_samples_split`, or add regularisation (`reg_alpha`, `reg_lambda` for XGBoost). Also check feature importances. If one feature dominates (>50%), it's likely a data leak.

<!-- this threshold was tuned empirically, might need adjusting for real bank data -->

**Data issues:** With fewer than 500 rows, warn that results may be unreliable. For any feature with >30% missing values, log a warning and consider dropping it.

## CLI usage

Run from `backend/` (or prefix with `docker-compose exec backend`). One algorithm per run:

```bash
# Train XGBoost (the default) on the default .tmp/synthetic_loans.csv
python manage.py train_model --algorithm xgb --data-path .tmp/synthetic_loans.csv

# Train Random Forest
python manage.py train_model --algorithm rf

# Train a per-segment model (default segment: unified)
python manage.py train_model --algorithm xgb --segment personal
```
