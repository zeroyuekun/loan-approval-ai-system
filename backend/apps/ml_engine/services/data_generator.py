import os

import numpy as np
import pandas as pd


class DataGenerator:
    """Generates synthetic loan application data for model training."""

    PURPOSES = ['home', 'auto', 'education', 'personal', 'business']
    HOME_OWNERSHIP = ['own', 'rent', 'mortgage']
    HOME_OWNERSHIP_WEIGHTS = [0.25, 0.35, 0.40]

    def generate(self, num_records=10000, random_seed=42):
        """Generate synthetic loan data with realistic distributions."""
        np.random.seed(random_seed)

        data = {
            'annual_income': np.random.lognormal(mean=np.log(60000), sigma=0.5, size=num_records).round(2),
            'credit_score': np.clip(
                np.random.normal(loc=680, scale=80, size=num_records).astype(int), 300, 850
            ),
            'loan_amount': np.random.lognormal(mean=np.log(15000), sigma=0.8, size=num_records).round(2),
            'loan_term_months': np.random.choice([12, 24, 36, 48, 60, 72, 84], size=num_records),
            'debt_to_income': np.clip(
                np.random.beta(a=2, b=5, size=num_records), 0.01, 0.99
            ).round(4),
            'employment_length': np.clip(
                np.random.exponential(scale=5, size=num_records).astype(int), 0, 40
            ),
            'purpose': np.random.choice(self.PURPOSES, size=num_records),
            'home_ownership': np.random.choice(
                self.HOME_OWNERSHIP, size=num_records, p=self.HOME_OWNERSHIP_WEIGHTS
            ),
            'has_cosigner': np.random.choice([0, 1], size=num_records, p=[0.9, 0.1]),
        }

        df = pd.DataFrame(data)

        # Generate approval labels based on scoring logic
        df['approved'] = self._compute_approval(df)

        return df

    def _compute_approval(self, df):
        """Compute approval based on weighted scoring with noise."""
        credit_norm = (df['credit_score'] - 300) / 550
        dti = df['debt_to_income']
        income_norm = np.clip((df['annual_income'] - 20000) / 150000, 0, 1)
        emp_norm = np.clip(df['employment_length'] / 20, 0, 1)
        cosigner_bonus = df['has_cosigner'] * 0.1

        score = (
            0.35 * credit_norm
            + 0.25 * (1 - dti)
            + 0.20 * income_norm
            + 0.10 * emp_norm
            + 0.10 * cosigner_bonus
        )

        noise = np.random.normal(0, 0.05, size=len(df))
        score_with_noise = score + noise

        return (score_with_noise > 0.45).astype(int)

    def save_to_csv(self, df, path):
        """Save DataFrame to CSV, creating directories as needed."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df.to_csv(path, index=False)
        return path
