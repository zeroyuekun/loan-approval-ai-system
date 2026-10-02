# Data generation workflow

## Objective

Generate 10,000 realistic synthetic loan application records for model training and system testing, following Australian lending standards.

## Tools

| Tool | Location | Purpose |
|------|----------|---------|
| Management command | `backend/apps/ml_engine/management/commands/generate_data.py` | `python manage.py generate_data`: writes the CSV and optionally seeds demo applications |
| Django service | `backend/apps/ml_engine/services/datagen/data_generator.py` | `DataGenerator`, used by the management command and the API |

## Feature specifications (Australian standards)

### Original features

| Feature | Type | Range / Values | Distribution |
|---------|------|---------------|-------------|
| `annual_income` | float | 25,000 - 500,000 | Log-normal (median ~$70k AUD, ABS aligned) |
| `credit_score` | int | 0 - 1200 | Normal (mean 750, std 180) - Equifax Australia scale |
| `loan_amount` | float | 5,000 - 3,000,000 | Log-normal (median ~$350k, reflects AU property market) |
| `loan_term_months` | int | 60-360 | Weighted toward 25-30yr (300-360 months) |
| `debt_to_income` | float | 0.1 - 12.0 | DTI ratio (e.g. 4.5 = 4.5x gross income) |
| `employment_length` | int | 0 - 40 | Exponential (most < 10 years) |
| `purpose` | categorical | home, auto, education, personal, business | Weighted: home 35%, personal 20%, auto 20%, education 15%, business 10% |
| `home_ownership` | categorical | own, rent, mortgage | Weighted: mortgage 45%, rent 35%, own 20% |
| `has_cosigner` | bool | True / False | 8% True |

### New Australian lending features

| Feature | Type | Range / Values | Distribution / Logic |
|---------|------|---------------|---------------------|
| `property_value` | float | 0 - 5,000,000 | For home loans: loan_amount / target_LVR. 0 for non-home loans |
| `deposit_amount` | float | 0 - 2,000,000 | property_value - loan_amount for home loans |
| `monthly_expenses` | float | 800 - 10,000 | Log-normal (median ~$2,500), self-declared |
| `existing_credit_card_limit` | float | 0 - 50,000 | 70% have cards, log-normal (median ~$8k) |
| `number_of_dependants` | int | 0 - 4 | Weighted: 0→35%, 1→25%, 2→25%, 3→10%, 4→5% |
| `employment_type` | categorical | payg_permanent, payg_casual, self_employed, contract | Weighted: permanent 55%, self-employed 20%, casual 15%, contract 10% |
| `applicant_type` | categorical | single, couple | Weighted: couple 55%, single 45% |

## Target variable: `approved`

The approval decision uses Australian lending rules based on APRA 2026 regulations, Big 4 bank criteria, and industry practice.

### Step 1: Income shading (by employment type)

Banks don't count every type of income at 100%:

| Employment Type | Income Accepted |
|----------------|----------------|
| PAYG Permanent | 100% |
| PAYG Casual | 80% |
| Self-Employed | 75% (average of last 2 years, then shaded) |
| Contract | 85% |

### Step 2: Hard cutoffs (auto-deny)

1. **APRA DTI cap**: DTI >= 6.0x gross income → denied (with 15% quota pass-through for APRA's 20% allowance)
2. **Credit score floor**: Equifax < 500 → denied. Score 500-650: 60% denial rate (borderline for Big 4)
3. **Self-employed < 2 years**: denied (insufficient trading history)
4. **Casual < 1 year**: denied (insufficient employment history)

### Step 3: LVR check (home loans only)

```
LVR = loan_amount / property_value

LVR > 95%: denied (no lender supports without government scheme)
LVR > 90% AND credit_score < 700: denied (need good credit for high LVR)
```

### Step 4: Genuine savings check (home loans, LVR > 80%)

```
if LVR > 80% AND deposit < 5% of property_value: denied
```

### Step 5: HEM-based expense calculation

Banks take MAX(declared_expenses, HEM_benchmark).

HEM varies by applicant type, dependants, and income bracket (low/mid/high):

| Household | Low (<$60k) | Mid ($60k-$120k) | High (>$120k) |
|-----------|------------|-------------------|----------------|
| Single, 0 dep | $1,400 | $1,800 | $2,200 |
| Single, 1 dep | $1,900 | $2,300 | $2,700 |
| Single, 2+ dep | $2,200 | $2,700 | $3,100 |
| Couple, 0 dep | $2,100 | $2,600 | $3,100 |
| Couple, 1 dep | $2,500 | $3,000 | $3,500 |
| Couple, 2+ dep | $2,800 | $3,400 | $3,900 |

### Step 6: Serviceability formula (APRA buffer)

```
assessment_rate = max(product_rate + 3%, floor_rate)  # Currently 9.5%
monthly_repayment = P&I amortization at assessment_rate

# Australian marginal tax rates (simplified)
annual_tax = marginal_rates(annual_income)  # 0/19/32.5/37/45% brackets

# Credit card commitment
credit_card_monthly = existing_credit_card_limit × 3%

monthly_surplus = shaded_monthly_income
                - monthly_tax
                - effective_expenses (MAX of declared, HEM)
                - existing_debt_repayments
                - credit_card_monthly
                - monthly_repayment

if monthly_surplus < 0: denied
```

### Step 7: DSR check

```
DSR = (existing_debt_monthly + credit_card_monthly + monthly_repayment) / gross_monthly_income
if DSR > 35%: denied
```

### Step 8: Composite score (borderline cases)

Applications that pass every check get a composite score:

```
composite = 0.20 * credit_normalized    # Equifax 500-1200 → 0-1
          + 0.20 * dti_score            # lower DTI = better
          + 0.12 * income_score
          + 0.08 * employment_score
          + 0.18 * surplus_score        # monthly surplus capacity
          + 0.10 * lvr_score            # lower LVR = better (home loans)
          + employment_type_bonus       # +5% permanent, -3% self-employed
          + cosigner_bonus              # +5%
          - dependant_penalty           # -2% per dependant (max -8%)
```

If composite + noise < 0.35: denied

## Steps

1. **Set the random seed.** `DataGenerator.generate` defaults to `random_seed=42` for reproducibility.
2. **Generate features.** Create each feature column from the distributions above.
3. **Clip values.** Make sure every value falls within its specified range.
4. **Calculate approval.** Apply the 8-step assessment pipeline.
5. **Create the DataFrame.** Assemble all columns into a pandas DataFrame.
6. **Validate.** Check for nulls, verify value ranges, and confirm the approval rate is reasonable.
7. **Save.** Write the CSV to the specified output path.

## Expected outputs

- CSV file with 10,000 rows (or `--num-records` count) and 17 columns
- Approval rate between 45-60%
- No null values
- All values within specified ranges

## CLI usage

Run from `backend/` (or prefix with `docker-compose exec backend`):

```bash
# 10,000 records to the default .tmp/synthetic_loans.csv, CSV only (no DB rows)
python manage.py generate_data --num-records 10000 --create-db-records 0

# Default 50,000 records, plus 100 demo LoanApplication rows in the DB
python manage.py generate_data

# Custom output path
python manage.py generate_data --output data/training_data.csv

# Calibrate distributions against live ABS / APRA / RBA benchmarks
python manage.py generate_data --use-live-data
```

## Edge cases

If the output directory doesn't exist, create it with `os.makedirs(exist_ok=True)`. On disk, 10k records is about 2.5MB and 100k is ~25MB. Warn if generating over 1M. Always log the random seed used (even the default) so results can be reproduced. Non-home loans have `property_value` and `deposit_amount` set to 0, so the LVR and genuine savings checks are skipped.
