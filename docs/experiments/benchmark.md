# Benchmark - XGBoost vs LR vs RF vs LightGBM

_Generated on 2026-04-15 13:14 UTC_

- **Records:** 2,000
- **Seed:** 42
- **Split:** stratified 80/20
- **Features:** numeric after `compute_derived_features`, imputed to 0, StandardScaler for LR only

<!-- BENCHMARK TABLE BEGIN -->

| Model | AUC-ROC | PR-AUC | Brier | Train time (s) |
|---|---|---|---|---|
| LogisticRegression | 0.8364 | 0.8788 | 0.1655 | 0.02 |
| RandomForest | 0.8490 | 0.8578 | 0.1530 | 0.15 |
| XGBoost | 0.8499 | 0.8759 | 0.1561 | 0.31 |
| LightGBM | 0.8445 | 0.8782 | 0.1664 | 2.19 |

<!-- BENCHMARK TABLE END -->

## Takeaway

_Human-written interpretation goes here. Edit freely - this section is preserved on future `make benchmark` runs._