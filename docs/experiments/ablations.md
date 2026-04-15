# Ablation - top-K feature removal

_Generated on 2026-04-15 13:15 UTC_

- **Records:** 2,000
- **Seed:** 42
- **Baseline AUC-ROC:** 0.8499
- **Baseline PR-AUC:** 0.8759
- **Top-K features removed (one at a time):** 10

<!-- ABLATION TABLE BEGIN -->

| Feature removed | AUC without | ΔAUC | ΔPR-AUC |
|---|---|---|---|
| lvr_x_dti | 0.8449 | +0.0050 | -0.0004 |
| monthly_repayment_ratio | 0.8517 | -0.0018 | -0.0123 |
| employment_length | 0.8484 | +0.0015 | +0.0022 |
| credit_score_x_tenure | 0.8460 | +0.0039 | +0.0016 |
| expense_to_income | 0.8553 | -0.0054 | -0.0026 |
| has_bankruptcy | 0.8504 | -0.0005 | +0.0010 |
| dti_x_rate_sensitivity | 0.8531 | -0.0032 | -0.0107 |
| months_since_last_default | 0.8546 | -0.0047 | -0.0105 |
| cash_advance_count_12m | 0.8530 | -0.0031 | -0.0021 |
| lvr_x_property_growth | 0.8584 | -0.0085 | -0.0090 |

<!-- ABLATION TABLE END -->

## Takeaway

_Human-written interpretation goes here. Edit freely - this section is preserved on future `make ablate` runs._