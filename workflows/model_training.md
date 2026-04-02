# Model Training Workflow

<!-- TODO: update after Optuna migration — GridSearchCV for RF should probably move to Optuna too -->

## Objective

Train and retrain Random Forest (RF) and XGBoost classification models on loan application data to predict approval/denial outcomes.

## Required Inputs

- Loan dataset in CSV format (synthetic via `tools/generate_synthetic_data.py` or real export)
- Columns required: `income`, `credit_score`, `loan_amount`, `debt_to_income`, `employment_length`, `purpose`, `home_ownership`, `annual_income`, `has_cosigner`, `approved`

## Tools

| Tool | Location | Purpose |
|------|----------|---------|
| Standalone trainer | `tools/train_model.py` | CLI script for local training outside Django |
| Django service trainer | `backend/apps/ml_engine/services/trainer.py` | Training service used by Celery tasks |

## Steps

1. **Load data** - Read CSV from `--data-path` (default: `.tmp/synthetic_loans.csv`)
2. **Preprocess**
   - Encode categorical features (`purpose`, `home_ownership`) with `LabelEncoder` or `OneHotEncoder`
   - Scale numeric features (`income`, `credit_score`, `loan_amount`, `debt_to_income`, `employment_length`, `annual_income`) with `StandardScaler`
   - Handle missing values: drop rows with >50% missing, impute remainder with median (numeric) or mode (categorical)
3. **Split** - 80% train / 10% validation / 10% test using `train_test_split` with `random_state=42` and `stratify=y`
4. **Train with hyperparameter optimization**
   - RF: `GridSearchCV` with params `n_estimators` [100, 200], `max_depth` [10, 20, None], `min_samples_split` [2, 5]
   - XGBoost: `Optuna` Bayesian optimization (TPE sampler, 50 trials) with wider search space — max_depth [4-10], learning_rate [0.01-0.15], reg_lambda [1-50]
   - Use 3-fold stratified cross-validation, scoring on `roc_auc`
5. **Evaluate** - Run best model against validation set first, then test set. Print classification report, confusion matrix, AUC-ROC.
6. **Save** - Serialize best model with `joblib.dump()` to `backend/ml_models/` (or `--output-dir`). Include scaler and encoders in the same pipeline or as separate artifacts.

## Expected Outputs

- `.joblib` model file (e.g., `rf_model_20260312.joblib`)
- Metrics report printed to stdout and optionally saved to `.tmp/model_report.json`
- Preprocessor artifacts (scaler, encoders) saved alongside the model

## Watch out for

**Class imbalance:** If the approval rate is heavily skewed (>80% or <20%), use `class_weight='balanced'`, SMOTE on training data only, or adjust the decision threshold from the ROC curve. Never apply SMOTE to val/test sets.

**Overfitting:** Compare validation vs test accuracy — a >5% gap means the model is overfit. Reduce `max_depth`, increase `min_samples_split`, or add regularisation (`reg_alpha`, `reg_lambda` for XGBoost). Also check feature importances: if one feature dominates (>50%), it's likely a data leak.

<!-- this threshold was tuned empirically, might need adjusting for real bank data -->

**Data issues:** Fewer than 500 rows → warn that results may be unreliable. Any feature with >30% missing values → log a warning and consider dropping it.

## CLI Usage

```bash
# Train both algorithms on synthetic data
python tools/train_model.py --data-path .tmp/synthetic_loans.csv --algorithm both --output-dir backend/ml_models

# Train only Random Forest
python tools/train_model.py --algorithm rf

# Train only XGBoost
python tools/train_model.py --algorithm xgb
```
