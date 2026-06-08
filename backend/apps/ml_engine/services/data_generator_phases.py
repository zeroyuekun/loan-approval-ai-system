"""generate() phase helpers (M2 decomposition, sibling module).

These are verbatim extractions of post-DataFrame-assembly phases from
``DataGenerator.generate``. They live here (rather than as methods on
``DataGenerator``) purely to keep ``data_generator.py`` under the file-size
ratchet — the bodies are unchanged.

Each function is pure with respect to its arguments: it takes the data it
needs (arrays / DataFrame) plus the shared ``rng`` explicitly and draws from
that ``rng`` in the same order as the original inline code. They are called at
the SAME point in sequence in ``generate()``, so the draw order — and thus
every downstream value — is byte-for-byte identical. The determinism snapshot
test (``tests/test_data_generator_generate_decomp.py``) guards this invariant.
"""

import numpy as np


def synthesize_bureau_features(n, credit_norm, age_proxy, annual_income, has_bankruptcy, rng):
    """Synthesize credit-bureau features (enquiries, arrears, defaults,
    history, open accounts, BNPL, cash advances). Returns a dict of arrays."""
    enquiry_lambda = np.where(credit_norm > 0.7, 0.8, np.where(credit_norm > 0.4, 1.5, 3.5))
    num_credit_enquiries_6m = rng.poisson(enquiry_lambda)

    arrears_u = rng.random(n)
    worst_arrears_months = np.where(
        credit_norm > 0.7,
        np.where(arrears_u < 0.97, 0, np.where(arrears_u < 0.99, 1, np.where(arrears_u < 0.998, 2, 3))),
        np.where(
            credit_norm > 0.4,
            np.where(arrears_u < 0.88, 0, np.where(arrears_u < 0.96, 1, np.where(arrears_u < 0.99, 2, 3))),
            np.where(arrears_u < 0.70, 0, np.where(arrears_u < 0.85, 1, np.where(arrears_u < 0.95, 2, 3))),
        ),
    )

    default_u = rng.random(n)
    num_defaults_5yr = np.where(
        credit_norm > 0.6,
        0,
        np.where(default_u < 0.90, 0, np.where(default_u < 0.97, 1, np.where(default_u < 0.99, 2, 3))),
    )
    num_defaults_5yr[has_bankruptcy == 1] = np.clip(num_defaults_5yr[has_bankruptcy == 1] + 1, 1, 5)

    credit_history_months = np.clip(((age_proxy - 18) * 12 * rng.uniform(0.3, 0.9, size=n)).astype(int), 0, 480)

    total_open_accounts = np.clip(
        rng.poisson(np.where(annual_income > 100000, 5.0, np.where(annual_income > 60000, 3.5, 2.0))), 0, 15
    )

    bnpl_base_prob = np.where(
        age_proxy < 30, 0.55, np.where(age_proxy < 40, 0.35, np.where(age_proxy < 50, 0.15, 0.05))
    )
    has_bnpl = rng.random(n) < bnpl_base_prob
    num_bnpl_accounts = np.where(has_bnpl, rng.choice([1, 2, 3, 4], size=n, p=[0.45, 0.30, 0.15, 0.10]), 0)

    cash_advance_count_12m = np.where(
        credit_norm > 0.6,
        0,
        np.where(rng.random(n) < 0.15, rng.choice([1, 2, 3, 4, 5], size=n, p=[0.50, 0.25, 0.15, 0.07, 0.03]), 0),
    )
    return {
        "num_credit_enquiries_6m": num_credit_enquiries_6m,
        "worst_arrears_months": worst_arrears_months,
        "num_defaults_5yr": num_defaults_5yr,
        "credit_history_months": credit_history_months,
        "total_open_accounts": total_open_accounts,
        "num_bnpl_accounts": num_bnpl_accounts,
        "cash_advance_count_12m": cash_advance_count_12m,
    }


def synthesize_ccr_features(n, credit_norm, annual_income, num_defaults_5yr, rng):
    """Synthesize Comprehensive Credit Reporting features (late payments,
    worst-late buckets, limits, utilization, hardship, default recency,
    provider count). Returns a dict of arrays."""
    late_pay_lambda = np.where(credit_norm > 0.7, 0.2, np.where(credit_norm > 0.4, 1.5, 4.0))
    ccr_num_late_payments_24m = np.clip(rng.poisson(late_pay_lambda), 0, 20)

    worst_late_buckets = [0, 14, 30, 60, 90]
    worst_late_probs_good = [0.85, 0.08, 0.04, 0.02, 0.01]
    worst_late_probs_bad = [0.20, 0.15, 0.25, 0.20, 0.20]
    worst_late_probs = np.where(
        credit_norm[:, None] > 0.6,
        np.tile(worst_late_probs_good, (n, 1)),
        np.tile(worst_late_probs_bad, (n, 1)),
    )
    ccr_worst_late_payment_days = np.array([rng.choice(worst_late_buckets, p=p) for p in worst_late_probs])

    ccr_total_credit_limit = np.clip(
        rng.lognormal(mean=np.log(annual_income * 0.3), sigma=0.5, size=n), 1000, 500000
    ).round(2)

    ccr_credit_utilization_pct = np.clip(rng.beta(2, 5, size=n) + (1 - credit_norm) * 0.3, 0.0, 1.0).round(3)

    hardship_prob = np.where(credit_norm > 0.6, 0.02, np.where(credit_norm > 0.3, 0.08, 0.18))
    ccr_num_hardship_flags = np.where(
        rng.random(n) < hardship_prob, rng.choice([1, 2, 3], size=n, p=[0.7, 0.2, 0.1]), 0
    )

    has_default = num_defaults_5yr > 0
    ccr_months_since_last_default = np.where(
        has_default, np.clip(rng.exponential(24, size=n).astype(int), 1, 60), np.nan
    ).astype(float)

    ccr_num_credit_providers = np.clip(rng.poisson(np.where(credit_norm > 0.5, 3, 2), size=n), 1, 15)
    return {
        "ccr_num_late_payments_24m": ccr_num_late_payments_24m,
        "ccr_worst_late_payment_days": ccr_worst_late_payment_days,
        "ccr_total_credit_limit": ccr_total_credit_limit,
        "ccr_credit_utilization_pct": ccr_credit_utilization_pct,
        "ccr_num_hardship_flags": ccr_num_hardship_flags,
        "ccr_months_since_last_default": ccr_months_since_last_default,
        "ccr_num_credit_providers": ccr_num_credit_providers,
    }


def simulate_ex_post_outcomes(df, rng):
    """Simulate ex-post loan outcomes (arrears/default/prepaid/performing)
    and months-to-outcome for approved loans."""
    approved_mask = df["approved"] == 1

    base_pd = np.full(len(df), 0.015)

    base_pd = np.where(df["credit_score"] < 650, base_pd * 3.0, base_pd)
    base_pd = np.where(df["credit_score"] > 850, base_pd * 0.4, base_pd)
    base_pd = np.where(df["num_defaults_5yr"] > 0, base_pd * 2.5, base_pd)
    if "stress_index" in df.columns:
        base_pd = np.where(df["stress_index"] > 60, base_pd * 2.5, base_pd)
    if "overdraft_frequency_90d" in df.columns:
        base_pd = np.where(df["overdraft_frequency_90d"] > 5, base_pd * 2.0, base_pd)
    if "gambling_transaction_flag" in df.columns:
        base_pd = np.where(df["gambling_transaction_flag"], base_pd * 1.8, base_pd)
    if "worst_late_payment_days" in df.columns:
        base_pd = np.where(df["worst_late_payment_days"] >= 60, base_pd * 2.0, base_pd)
    if "bnpl_late_payments_12m" in df.columns:
        base_pd = np.where(df["bnpl_late_payments_12m"] > 2, base_pd * 1.5, base_pd)
    if "savings_to_loan_ratio" in df.columns:
        base_pd = np.where(df["savings_to_loan_ratio"] > 0.3, base_pd * 0.6, base_pd)
    if "debt_service_coverage" in df.columns:
        base_pd = np.where(df["debt_service_coverage"] > 2.0, base_pd * 0.5, base_pd)

    if "quarter" in df.columns:
        base_pd = np.where(df["quarter"] == 1, base_pd * 1.3, base_pd)
        base_pd = np.where(df["quarter"] == 3, base_pd * 1.15, base_pd)
        base_pd = np.where(df["quarter"] == 4, base_pd * 0.95, base_pd)

    base_pd = np.clip(base_pd, 0.001, 0.50)

    outcome_roll = rng.random(len(df))
    prepaid_threshold = 0.035

    outcomes = np.where(
        ~approved_mask,
        None,
        np.where(
            outcome_roll < base_pd * 0.3,
            "arrears_90",
            np.where(
                outcome_roll < base_pd * 0.6,
                "arrears_60",
                np.where(
                    outcome_roll < base_pd,
                    "arrears_30",
                    np.where(outcome_roll < base_pd + prepaid_threshold, "prepaid", "performing"),
                ),
            ),
        ),
    )
    default_roll = rng.random(len(df))
    outcomes = np.where((outcomes == "arrears_90") & (default_roll < 0.5), "default", outcomes)

    df["actual_outcome"] = outcomes

    df["months_to_outcome"] = np.where(
        approved_mask & df["actual_outcome"].isin(["default", "arrears_90"]),
        np.clip(rng.lognormal(mean=np.log(18), sigma=0.5, size=len(df)).astype(int), 3, 36),
        np.where(
            approved_mask & df["actual_outcome"].isin(["arrears_30", "arrears_60"]),
            np.clip(rng.lognormal(mean=np.log(12), sigma=0.6, size=len(df)).astype(int), 1, 36),
            np.where(
                approved_mask & (df["actual_outcome"] == "prepaid"),
                np.clip(rng.poisson(4, len(df)), 1, 12),
                np.where(approved_mask, 12, np.nan),
            ),
        ),
    )
    return df
