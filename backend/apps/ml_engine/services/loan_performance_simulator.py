import numpy as np
import pandas as pd


class LoanPerformanceSimulator:
    """Simulates post-approval loan performance using Markov chain transitions.

    Stateless -- takes a DataFrame and returns it with performance columns added.
    Extracted from DataGenerator to isolate loan performance simulation logic.
    """

    def simulate_loan_performance(self, df: pd.DataFrame) -> pd.DataFrame:
        """Simulate loan performance outcomes for approved loans.

        For each approved loan, runs month-by-month Markov chain simulation
        using risk-adjusted transition probabilities from RealWorldBenchmarks.
        Produces: months_on_book, ever_30dpd, ever_90dpd, default_flag,
        prepaid_flag, current_status.

        Calibrated to:
        - APRA NPL 1.04% (via transition matrix)
        - Moody's AU RMBS CPR 15-22% annually
        - S&P APAC cure rates (30dpd: 40-60%, 60dpd: 10-20%)
        """
        from .real_world_benchmarks import RealWorldBenchmarks

        reference_date = pd.Timestamp("2025-12-31")
        approved_mask = df["approved"] == 1

        # Initialize performance columns for ALL rows
        df["months_on_book"] = 0
        df["ever_30dpd"] = 0
        df["ever_90dpd"] = 0
        df["default_flag"] = 0
        df["prepaid_flag"] = 0
        df["current_status"] = "denied"

        approved_indices = df[approved_mask].index

        for idx in approved_indices:
            row = df.loc[idx]
            app_date = pd.Timestamp(row["application_date"])
            mob = max(0, (reference_date.year - app_date.year) * 12 + (reference_date.month - app_date.month))
            df.at[idx, "months_on_book"] = mob

            if mob == 0:
                df.at[idx, "current_status"] = "performing"
                continue

            # Risk multiplier based on borrower characteristics.
            # Base multiplier of 1.8 calibrates terminal default rate to
            # ~1.0-1.5% given the corrected Moody's transition matrix
            # (performing->30dpd 0.3%/mo) and avg MOB of ~12-18 months.
            risk_multiplier = 1.8

            # DTI effect (baseline at 4.0, higher = riskier)
            dti = row.get("debt_to_income", 4.0)
            risk_multiplier *= max(0.5, min(3.0, dti / 4.0))

            # Credit score effect (baseline at 800, lower = riskier)
            credit = row.get("credit_score", 800)
            risk_multiplier *= max(0.3, min(3.0, 800 / max(credit, 300)))

            # LVR effect (baseline at 0.70, higher = riskier)
            lvr = row.get("lvr", 0.70) if "lvr" in df.columns else 0.70
            if pd.notna(lvr) and lvr > 0:
                risk_multiplier *= max(0.5, min(2.5, lvr / 0.70))

            # Rate stress (higher cash rate at origination = more stress)
            cash_rate = row.get("cash_rate", 4.35)
            if cash_rate > 3.0:
                risk_multiplier *= 1.0 + (cash_rate - 3.0) * 0.15

            # Employment type
            emp_type = row.get("employment_type", "payg_permanent")
            if emp_type in ("payg_casual", "contract"):
                risk_multiplier *= 1.5
            elif emp_type == "self_employed":
                risk_multiplier *= 1.2

            # Month-by-month simulation using transition matrix
            state = "performing"
            ever_30 = False
            ever_90 = False

            for _month in range(1, mob + 1):
                base_probs = RealWorldBenchmarks.get_transition_probs(state)

                # Adjust for risk
                adjusted_probs = {}
                for next_state, prob in base_probs.items():
                    if next_state in ("30dpd", "60dpd", "90dpd", "default"):
                        adjusted_probs[next_state] = min(prob * risk_multiplier, 0.95)
                    elif next_state == "performing" and state != "performing":
                        adjusted_probs[next_state] = max(prob / risk_multiplier, 0.01)
                    else:
                        adjusted_probs[next_state] = prob

                # Normalize
                total = sum(adjusted_probs.values())
                adjusted_probs = {k: v / total for k, v in adjusted_probs.items()}

                # Transition
                states = list(adjusted_probs.keys())
                probs = list(adjusted_probs.values())
                state = np.random.choice(states, p=probs)

                if state in ("30dpd", "60dpd", "90dpd"):
                    ever_30 = True
                if state == "90dpd":
                    ever_90 = True
                if state == "default":
                    ever_30 = True
                    ever_90 = True
                    break
                if state == "prepaid":
                    break

            df.at[idx, "ever_30dpd"] = int(ever_30)
            df.at[idx, "ever_90dpd"] = int(ever_90)
            df.at[idx, "default_flag"] = int(state == "default")
            df.at[idx, "prepaid_flag"] = int(state == "prepaid")
            df.at[idx, "current_status"] = state

        return df
