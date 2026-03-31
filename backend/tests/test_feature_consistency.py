"""Tests for feature consistency between data generator, trainer, and predictor.

Ensures no train/serve skew — features generated must match features trained and predicted.
"""


class TestFeatureAlignment:
    def test_trainer_features_in_generated_data(self):
        """All trainer features should be producible by the data generator."""
        from apps.ml_engine.services.data_generator import DataGenerator
        from apps.ml_engine.services.trainer import ModelTrainer

        gen = DataGenerator()
        df = gen.generate(num_records=100)
        trainer = ModelTrainer()

        try:
            df = trainer.add_derived_features(df)
        except Exception:
            pass

        all_cols = trainer.NUMERIC_COLS + trainer.CATEGORICAL_COLS

        # Derived features are computed during training, not in raw generated data
        derived = {
            "lvr",
            "loan_to_income",
            "credit_card_burden",
            "expense_to_income",
            "lvr_x_dti",
            "income_credit_interaction",
            "serviceability_ratio",
            "employment_stability",
            "deposit_ratio",
            "monthly_repayment_ratio",
            "net_monthly_surplus",
            "income_per_dependant",
            "credit_score_x_tenure",
            "enquiry_intensity",
            "bureau_risk_score",
            "rate_stress_buffer",
            "stressed_repayment",
            "stressed_dsr",
            "hem_surplus",
            "uncommitted_monthly_income",
            "savings_to_loan_ratio",
            "debt_service_coverage",
            "bnpl_to_income_ratio",
            "enquiry_to_account_ratio",
            "stress_index",
            "log_annual_income",
            "log_loan_amount",
        }
        missing = [c for c in all_cols if c not in df.columns and c not in derived]
        assert len(missing) == 0, f"Trainer expects features not in data: {missing}"

    def test_predictor_cats_match_trainer(self):
        """Predictor CATEGORICAL_COLS should match trainer CATEGORICAL_COLS."""
        from apps.ml_engine.services.predictor import ModelPredictor
        from apps.ml_engine.services.trainer import ModelTrainer

        trainer_cats = set(ModelTrainer.CATEGORICAL_COLS)
        predictor_cats = set(ModelPredictor.CATEGORICAL_COLS)
        assert trainer_cats == predictor_cats, (
            f"Mismatch. Trainer has {trainer_cats - predictor_cats}, Predictor has {predictor_cats - trainer_cats}"
        )

    def test_no_duplicate_features(self):
        """Trainer should not have duplicate feature names."""
        from apps.ml_engine.services.trainer import ModelTrainer

        trainer = ModelTrainer()
        all_cols = trainer.NUMERIC_COLS + trainer.CATEGORICAL_COLS
        dupes = [c for c in all_cols if all_cols.count(c) > 1]
        assert len(dupes) == 0, f"Duplicate features: {set(dupes)}"
