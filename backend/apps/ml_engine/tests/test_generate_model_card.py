# backend/apps/ml_engine/tests/test_generate_model_card.py
import pathlib
from io import StringIO

import pytest
from django.conf import settings
from django.core.management import call_command

from apps.ml_engine.models import ModelVersion


@pytest.mark.django_db
def test_generate_model_card_writes_expected_sections(tmp_path: pathlib.Path) -> None:
    fake_model_path = pathlib.Path(settings.ML_MODELS_DIR) / "test-model-card.joblib"
    mv = ModelVersion.objects.create(
        algorithm="xgb",
        version="test-20260415",
        file_path=str(fake_model_path),
        is_active=True,
        accuracy=0.87,
        precision=0.82,
        recall=0.79,
        f1_score=0.80,
        auc_roc=0.91,
        brier_score=0.12,
        gini_coefficient=0.82,
        ks_statistic=0.65,
        ece=0.04,
        optimal_threshold=0.51,
        confusion_matrix={"tp": 100, "tn": 200, "fp": 20, "fn": 30},
        feature_importances={"annual_income": 0.31, "credit_score": 0.22},
        training_params={"n_estimators": 400},
        calibration_data={"method": "isotonic"},
        training_metadata={"num_records": 50000, "seed": 42},
    )

    output_path = tmp_path / "test-model-card.md"
    buf = StringIO()
    call_command(
        "generate_model_card",
        f"--version-id={mv.id}",
        f"--output={output_path}",
        stdout=buf,
    )

    contents = output_path.read_text(encoding="utf-8")
    for heading in [
        "# Model Card",
        "## Model Details",
        "## Intended Use",
        "## Factors",
        "## Metrics",
        "## Evaluation Data",
        "## Training Data",
        "## Quantitative Analyses",
        "## Ethical Considerations",
        "## Caveats and Recommendations",
    ]:
        assert heading in contents, f"Missing heading: {heading}"

    # Spot-check a metric value is rendered
    assert "0.9100" in contents  # auc_roc
    assert "isotonic" in contents  # calibration method
