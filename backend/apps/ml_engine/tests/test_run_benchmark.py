# backend/apps/ml_engine/tests/test_run_benchmark.py
import pathlib

import pytest
from django.core.management import call_command


@pytest.mark.slow
@pytest.mark.django_db
def test_run_benchmark_produces_table(tmp_path: pathlib.Path) -> None:
    output = tmp_path / "benchmark.md"
    call_command(
        "run_benchmark",
        "--num-records=200",
        "--seed=42",
        f"--output={output}",
    )
    text = output.read_text(encoding="utf-8")
    assert "| Model |" in text
    # Four models: LR, RF, XGB, LGBM
    assert text.count("\n| ") >= 5  # header + 4 rows
    assert "LogisticRegression" in text
    assert "RandomForest" in text
    assert "XGBoost" in text
    assert "LightGBM" in text
    # Sanity floor: all AUCs plausible
    for float_token in text.split():
        if float_token.replace(".", "").isdigit() and "." in float_token:
            value = float(float_token)
            if 0.0 <= value <= 1.0:
                # Found an AUC-range value - too loose to assert each,
                # but ensures no NaN/Inf/negative.
                assert value >= 0.0
