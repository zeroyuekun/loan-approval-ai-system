# backend/apps/ml_engine/tests/test_run_ablation.py
import pathlib

import pytest
from django.core.management import call_command


@pytest.mark.slow
@pytest.mark.django_db
def test_run_ablation_produces_table(tmp_path: pathlib.Path) -> None:
    output = tmp_path / "ablations.md"
    call_command(
        "run_ablation",
        "--top-k=3",
        "--num-records=200",
        "--seed=42",
        f"--output={output}",
    )
    text = output.read_text(encoding="utf-8")
    assert "| Feature removed |" in text
    # Header + 3 rows
    assert text.count("\n| ") >= 4
    assert "\u0394AUC" in text or "\u0394AUC-ROC" in text
