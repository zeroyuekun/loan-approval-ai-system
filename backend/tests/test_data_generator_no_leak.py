"""Regression test: no post-outcome feature may reach the training feature set.

A post-outcome feature is one whose value is only knowable AFTER a lending
decision has been made (e.g., realised default flags, prepayment buffer
computed after approval, ex-post loan performance metrics). Including any
such feature in training is target leakage — it inflates validation AUC
without generalising to real prediction-time data.

This test enforces the separation as a code-level invariant so the pattern
cannot be reintroduced without a deliberate test change.
"""

from apps.ml_engine.services.data_generator import POST_OUTCOME_FEATURES
from apps.ml_engine.services.trainer import ModelTrainer


def test_training_features_exclude_post_outcome_columns():
    training_features = set(ModelTrainer.NUMERIC_COLS) | set(ModelTrainer.CATEGORICAL_COLS)
    leaked = training_features & POST_OUTCOME_FEATURES
    assert not leaked, (
        f"Post-outcome features leaked into training set: {sorted(leaked)}. "
        f"These columns represent information only available AFTER a lending "
        f"decision and must not be used as model inputs."
    )


def test_post_outcome_features_constant_is_not_empty():
    """Sanity check: if this constant became empty, a future refactor silently
    defanged the leakage test above. Fail loudly instead."""
    assert len(POST_OUTCOME_FEATURES) >= 3, (
        f"POST_OUTCOME_FEATURES has only {len(POST_OUTCOME_FEATURES)} entries. "
        f"Expected at least 3 known post-decision columns from DataGenerator."
    )
