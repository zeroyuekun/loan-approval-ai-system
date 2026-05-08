"""Tests for the trainer's reference-distribution capture hook.

The hook stashes a sample of holdout probabilities and per-feature values on
the trainer instance after final model fit + predict_proba, so save_model can
embed them in the bundle and the metrics dict can mirror them for the simpler
weekly drift task.
"""

import numpy as np
import pytest

from apps.ml_engine.services.trainer import ModelTrainer


@pytest.mark.django_db
def test_capture_reference_distribution_caps_at_1000():
    """Sample size never exceeds 1000 even when holdout is larger."""
    trainer = ModelTrainer()
    rng = np.random.default_rng(42)
    holdout_probs = rng.random(size=5000)

    import pandas as pd
    holdout_features = pd.DataFrame({
        "annual_income": rng.integers(30000, 200000, size=5000),
        "credit_score": rng.integers(300, 850, size=5000),
    })

    trainer._capture_holdout_reference(holdout_probs, holdout_features)

    assert len(trainer._holdout_probabilities) == 1000
    assert set(trainer._holdout_feature_samples.keys()) == {"annual_income", "credit_score"}
    assert all(len(v) == 1000 for v in trainer._holdout_feature_samples.values())


@pytest.mark.django_db
def test_capture_reference_distribution_uses_full_holdout_when_small():
    """When holdout is smaller than the cap, capture the entire holdout."""
    import pandas as pd
    trainer = ModelTrainer()
    holdout_probs = np.array([0.1, 0.4, 0.7, 0.95])
    holdout_features = pd.DataFrame({"credit_score": [600, 650, 700, 750]})

    trainer._capture_holdout_reference(holdout_probs, holdout_features)

    assert trainer._holdout_probabilities == [0.1, 0.4, 0.7, 0.95]
    assert trainer._holdout_feature_samples == {"credit_score": [600, 650, 700, 750]}


@pytest.mark.django_db
def test_capture_reference_distribution_handles_empty_holdout():
    """Empty holdout produces empty lists, no exception."""
    import pandas as pd
    trainer = ModelTrainer()
    trainer._capture_holdout_reference(np.array([]), pd.DataFrame())

    assert trainer._holdout_probabilities == []
    assert trainer._holdout_feature_samples == {}
