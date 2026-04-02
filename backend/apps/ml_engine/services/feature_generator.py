import numpy as np
import pandas as pd


class BehavioralFeatureGenerator:
    """Generates behavioral realism features for synthetic loan data.

    Stateless class -- all methods take data + rng as parameters.
    Extracted from DataGenerator to isolate behavioral feature logic.
    """

    def apply_round_number_bias(self, loan_amount, rng):
        """Apply round-number bias to loan amounts (MIT/Wharton research).

        65% round to nearest $5K, 22% to nearest $1K, 13% keep as-is.
        """
        n = len(loan_amount)
        tier_roll = rng.random(n)
        rounded = np.where(
            tier_roll < 0.65,
            np.round(loan_amount / 5000) * 5000,
            np.where(
                tier_roll < 0.87,
                np.round(loan_amount / 1000) * 1000,
                np.round(loan_amount / 100) * 100,
            ),
        )
        return rounded

    def assign_application_channel(self, age, purpose, sub_pop, rng):
        """Assign application channel (digital/mobile/branch/broker).

        77% of AU mortgages via brokers; personal loans mostly digital.
        Age adjustments: <30 digital+, >50 branch+.
        Vectorized implementation using numpy broadcasting.
        """
        n = len(age)
        is_home = purpose == "home"

        # Base weights: [digital, mobile, branch, broker]
        # Start with non-home defaults, override for home loans
        w_digital = np.where(is_home, 0.15, 0.55)
        w_mobile = np.where(is_home, 0.05, 0.20)
        w_branch = np.where(is_home, 0.05, 0.18)
        w_broker = np.where(is_home, 0.75, 0.07)

        # Age adjustments
        young = age < 30
        old = age > 50
        w_digital = np.where(young, w_digital + 0.10, np.where(old, w_digital - 0.10, w_digital))
        w_mobile = np.where(young, w_mobile + 0.05, np.where(old, w_mobile - 0.05, w_mobile))
        w_branch = np.where(young, w_branch - 0.10, np.where(old, w_branch + 0.10, w_branch))
        w_broker = np.where(young, w_broker - 0.05, np.where(old, w_broker + 0.05, w_broker))

        # Clip and normalize
        w_digital = np.clip(w_digital, 0.01, None)
        w_mobile = np.clip(w_mobile, 0.01, None)
        w_branch = np.clip(w_branch, 0.01, None)
        w_broker = np.clip(w_broker, 0.01, None)
        w_total = w_digital + w_mobile + w_branch + w_broker
        w_digital /= w_total
        w_mobile /= w_total
        w_branch /= w_total
        w_broker /= w_total

        # Vectorized sampling using cumulative thresholds
        roll = rng.random(n)
        cum1 = w_digital
        cum2 = cum1 + w_mobile
        cum3 = cum2 + w_branch

        channel = np.where(
            roll < cum1, "digital", np.where(roll < cum2, "mobile", np.where(roll < cum3, "branch", "broker"))
        )
        return channel

    def apply_income_inflation(self, annual_income, employment_type, is_fraud_signal, rng):
        """Apply strategic income inflation (ASIC v Westpac research).

        7% base inflation rate; self-employed 3x (21%), casual 1.5x (10.5%).
        Magnitude: 70% mild (1.05-1.15x), 25% moderate (1.15-1.25x), 5% severe (1.25-1.40x).
        """
        n = len(annual_income)
        inflation_prob = np.full(n, 0.07)
        inflation_prob[employment_type == "self_employed"] = 0.21
        inflation_prob[employment_type == "payg_casual"] = 0.105
        inflation_prob[is_fraud_signal == 1] = 0.80

        is_inflator = rng.random(n) < inflation_prob

        # Magnitude tiers
        magnitude_roll = rng.random(n)
        multiplier = np.where(
            magnitude_roll < 0.70,
            rng.uniform(1.05, 1.15, size=n),
            np.where(magnitude_roll < 0.95, rng.uniform(1.15, 1.25, size=n), rng.uniform(1.25, 1.40, size=n)),
        )

        true_income = annual_income.copy()
        inflated_income = annual_income.copy()
        inflated_income[is_inflator] = (annual_income[is_inflator] * multiplier[is_inflator]).round(2)

        # income_verification_gap = stated / verified
        verification_gap = np.where(is_inflator, inflated_income / true_income, 1.0).round(2)

        return inflated_income, true_income, verification_gap

    def apply_optimism_bias(self, loan_amount, age, sub_pop, rng):
        """Apply optimism bias -- borrowers request more than capacity (Philadelphia Fed).

        27% base rate; age <30: 40%, FHB: 1.3x, refinancer: 0.6x.
        Optimists request 10-25% more than capacity.
        """
        n = len(loan_amount)
        base_prob = np.full(n, 0.27)
        base_prob[age < 30] = 0.40
        base_prob[(age >= 30) & (age < 40)] = 0.32
        base_prob[age >= 50] = 0.19

        # Sub-population adjustments
        base_prob[sub_pop == "first_home_buyer"] *= 1.3
        base_prob[sub_pop == "refinancer"] *= 0.6
        base_prob = np.clip(base_prob, 0, 0.60)

        is_optimist = rng.random(n) < base_prob

        # Optimists request 10-25% more
        boost = rng.uniform(1.10, 1.25, size=n)
        adjusted_amount = loan_amount.copy()
        adjusted_amount[is_optimist] = (loan_amount[is_optimist] * boost[is_optimist]).round(2)

        return adjusted_amount, is_optimist.astype(int)

    def assign_financial_literacy(self, age, credit_score, sub_pop, rng):
        """Assign financial literacy score (ANZ Survey).

        Beta(4,4) base; age <25: -0.15, credit >900: +0.10, business: +0.10.
        """
        n = len(age)
        base = rng.beta(4, 4, size=n)

        # Age adjustments (ANZ Survey)
        base[age < 25] -= 0.15
        base[(age >= 25) & (age < 35)] -= 0.05
        base[(age >= 35) & (age < 50)] += 0.05
        base[age >= 50] += 0.10

        # Credit score correlation
        base[credit_score > 900] += 0.10
        base[credit_score < 700] -= 0.10

        # Business borrowers tend to be more literate
        base[sub_pop == "business_borrower"] += 0.10

        return np.clip(base, 0.05, 0.95).round(2)

    def compute_prepayment_buffer(self, df, rng):
        """Compute prepayment buffer and negative equity flag (RBA RDP 2020-03).

        Buffer distribution: <1mo: 8%, 1-3: 12%, 3-6: 10%, 6-12: 25%, 12+: 45%.
        """
        n = len(df)
        buffer_tier = rng.choice(
            ["very_low", "low", "medium", "high", "very_high"],
            size=n,
            p=[0.08, 0.12, 0.10, 0.25, 0.45],
        )
        buffer_months = np.where(
            buffer_tier == "very_low",
            rng.uniform(0, 1, size=n),
            np.where(
                buffer_tier == "low",
                rng.uniform(1, 3, size=n),
                np.where(
                    buffer_tier == "medium",
                    rng.uniform(3, 6, size=n),
                    np.where(buffer_tier == "high", rng.uniform(6, 12, size=n), rng.uniform(12, 36, size=n)),
                ),
            ),
        ).round(1)

        # Correlate with credit score
        credit_norm = np.clip((df["credit_score"].values - 650) / 400, 0, 1)
        buffer_months = buffer_months * (0.5 + credit_norm)
        buffer_months = np.clip(buffer_months, 0, 60).round(1)

        # Negative equity flag (home loans only)
        is_home = df["purpose"] == "home"
        property_growth = df.get("property_growth_12m", pd.Series(np.zeros(n))).values
        lvr = np.where(
            df["property_value"] > 0,
            df["loan_amount"] / df["property_value"],
            0.0,
        )
        # After 12 months of property growth, what's the effective LVR?
        effective_lvr = lvr / (1 + property_growth / 100)
        negative_equity = (is_home & (effective_lvr > 1.0)).astype(int)

        return buffer_months, negative_equity

    def assign_life_event_trigger(self, purpose, sub_pop, rng):
        """Assign life event trigger for the loan application.

        Personal: debt_consolidation 35%, etc.  Home: by sub-population.
        Business: expansion/equipment/working_capital/startup.
        """
        n = len(purpose)
        triggers = np.full(n, "other", dtype="<U25")

        personal_mask = np.isin(purpose, ["personal", "auto", "education"])
        home_mask = purpose == "home"
        business_mask = purpose == "business"

        # Personal loans
        personal_events = [
            "debt_consolidation",
            "home_improvement",
            "major_purchase",
            "medical",
            "wedding",
            "travel",
            "moving_costs",
            "other",
        ]
        personal_weights = [0.35, 0.15, 0.12, 0.10, 0.08, 0.07, 0.05, 0.08]
        if personal_mask.sum() > 0:
            triggers[personal_mask] = rng.choice(personal_events, size=personal_mask.sum(), p=personal_weights)

        # Override for auto/education
        triggers[purpose == "auto"] = "vehicle_purchase"
        triggers[purpose == "education"] = "education"

        # Home loans by sub-population
        fhb_mask = home_mask & (sub_pop == "first_home_buyer")
        upgrader_mask = home_mask & (sub_pop == "upgrader")
        refinancer_mask = home_mask & (sub_pop == "refinancer")
        investor_mask = home_mask & (sub_pop == "investor")
        triggers[fhb_mask] = "purchase"
        if upgrader_mask.sum() > 0:
            triggers[upgrader_mask] = rng.choice(["purchase", "renovation"], size=upgrader_mask.sum(), p=[0.80, 0.20])
        triggers[refinancer_mask] = "refinance"
        triggers[investor_mask] = "investment_purchase"

        # Business loans
        business_events = ["expansion", "equipment", "working_capital", "startup"]
        business_weights = [0.30, 0.25, 0.30, 0.15]
        if business_mask.sum() > 0:
            triggers[business_mask] = rng.choice(business_events, size=business_mask.sum(), p=business_weights)

        return triggers
