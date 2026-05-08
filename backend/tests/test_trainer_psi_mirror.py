"""Tests for trainer mirroring psi_by_feature into training_metadata.

The dossier reads training_metadata.psi_by_feature; the trainer used to
write only metrics["psi_by_feature"] (top level) which was dropped by the
ModelVersion creation path. This test pins the mirror.
"""

import pytest

from apps.ml_engine.services.trainer import ModelTrainer


@pytest.mark.django_db
def test_train_metrics_include_psi_by_feature_in_training_metadata(tmp_path, monkeypatch):
    """metrics['training_metadata']['psi_by_feature'] mirrors the top-level metrics['psi_by_feature']."""
    from apps.ml_engine.services.data_generator import DataGenerator

    gen = DataGenerator()
    df = gen.generate(num_records=300, random_seed=42, label_noise_rate=0.05)
    csv_path = tmp_path / "tiny.csv"
    df.to_csv(csv_path, index=False)

    trainer = ModelTrainer()
    monkeypatch.setattr(trainer, "_train_xgb", trainer._train_rf)
    _model, metrics = trainer.train(str(csv_path), algorithm="rf")

    top_level = metrics.get("psi_by_feature") or {}
    mirrored = metrics.get("training_metadata", {}).get("psi_by_feature") or {}

    assert isinstance(mirrored, dict)
    assert set(mirrored.keys()) == set(top_level.keys())
    for k in mirrored:
        assert abs(mirrored[k] - top_level[k]) < 1e-9, f"mirror diverged for {k}"
