# Data Generation Workflow

## Objective

Generate 10,000 realistic synthetic loan application records for model training and system testing.

## Required Inputs

- Number of records to generate (default: 10,000)
- Output file path (default: `.tmp/synthetic_loans.csv`)

## Tools

| Tool | Location | Purpose |
|------|----------|---------|
| Standalone generator | `tools/generate_synthetic_data.py` | CLI script for generating CSV outside Django |
| Django service | `backend/apps/ml_engine/services/data_generator.py` | Service used by management commands and API |

## Feature Specifications

| Feature | Type | Range / Values | Distribution |
|---------|------|---------------|-------------|
| `income` | float | 30,000 - 200,000 | Log-normal (median ~55k) |
| `credit_score` | int | 300 - 850 | Normal (mean 680, std 80) |
| `loan_amount` | float | 1,000 - 500,000 | Log-normal (median ~25k) |
| `debt_to_income` | float | 0.0 - 1.0 | Beta distribution (skewed toward 0.2-0.4) |
| `employment_length` | int | 0 - 40 | Exponential (most < 10 years) |
| `purpose` | categorical | home, auto, education, personal, business | Weighted: home 30%, auto 25%, personal 20%, education 15%, business 10% |
| `home_ownership` | categorical | own, rent, mortgage | Weighted: mortgage 45%, rent 35%, own 20% |
| `annual_income` | float | = `income` | Same as income (alias for compatibility) |
| `has_cosigner` | bool | True / False | 15% True |

## Target Variable: `approved`

The approval decision is based on a weighted scoring system, not a simple threshold:

### Scoring Formula

```
score = (
    0.35 * credit_score_normalized +     # Credit score is most important
    0.25 * (1 - debt_to_income) +        # Lower DTI is better
    0.20 * income_to_loan_ratio_capped + # Higher income relative to loan is better
    0.10 * employment_factor +            # Longer employment helps
    0.05 * cosigner_bonus +               # Cosigner provides small boost
    0.05 * purpose_factor                  # Some purposes slightly preferred
)
```

Where:
- `credit_score_normalized` = (credit_score - 300) / 550
- `income_to_loan_ratio_capped` = min(income / loan_amount, 1.0) for ratio, capped at 1.0
- `employment_factor` = min(employment_length / 10, 1.0)
- `cosigner_bonus` = 1.0 if has_cosigner else 0.0
- `purpose_factor`: home=0.8, auto=0.7, education=0.6, business=0.5, personal=0.4

### Decision Logic

```
approved = score > threshold + noise
```

- Base threshold: 0.5
- Noise: Uniform random in [-0.05, 0.05] (adds realistic randomness)
- Expected approval rate: approximately 55-65%

## Steps

1. **Set random seed** — Use `numpy.random.seed(42)` for reproducibility (can be overridden via CLI)
2. **Generate features** — Create each feature column according to the distributions above
3. **Clip values** — Ensure all values fall within their specified ranges
4. **Calculate approval** — Apply the weighted scoring formula
5. **Create DataFrame** — Assemble all columns into a pandas DataFrame
6. **Validate** — Check for nulls, verify value ranges, confirm approval rate is reasonable
7. **Save** — Write to CSV at the specified output path

## Expected Outputs

- CSV file with 10,000 rows (or `--num-records` count) and 10 columns
- Approval rate between 55-65%
- No null values
- All values within specified ranges

## CLI Usage

```bash
# Generate default 10,000 records
python tools/generate_synthetic_data.py

# Generate custom count
python tools/generate_synthetic_data.py --num-records 50000

# Custom output path
python tools/generate_synthetic_data.py --output-path data/training_data.csv

# Custom random seed
python tools/generate_synthetic_data.py --seed 123
```

## Edge Cases

- **Output directory doesn't exist**: Create it automatically with `os.makedirs(exist_ok=True)`.
- **Disk space**: 10,000 records is ~1.5MB CSV. 100,000 records is ~15MB. Warn if generating >1M records.
- **Reproducibility**: Always log the random seed used, even if it was the default, so results can be reproduced.
