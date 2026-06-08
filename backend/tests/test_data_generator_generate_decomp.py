"""M2: determinism guard for the DataGenerator.generate() decomposition.

These tests pin the synthetic generator's output so the refactor (extracting
phase helpers from the ~1000-line god method) cannot silently shift any draw
order. If a block move changes the RNG draw sequence, the frame-equality and
checksum assertions break immediately.
"""

import pandas as pd
import pytest

from apps.ml_engine.services.data_generator import DataGenerator


@pytest.fixture(scope="module")
def baseline():
    return DataGenerator().generate(num_records=500, random_seed=42, label_noise_rate=0.05)


def test_generate_is_deterministic_across_calls(baseline):
    again = DataGenerator().generate(num_records=500, random_seed=42, label_noise_rate=0.05)
    pd.testing.assert_frame_equal(baseline.reset_index(drop=True), again.reset_index(drop=True), check_dtype=False)


def test_generate_column_checksum_stable(baseline):
    # Pin a hashable signature so the refactor cannot silently shift values.
    num = baseline.select_dtypes("number").fillna(0).round(4)
    sig = {c: float(num[c].sum()) for c in sorted(num.columns)}
    assert sig["annual_income"] == pytest.approx(SUM_ANNUAL_INCOME, rel=1e-9)
    assert sig["credit_score"] == pytest.approx(SUM_CREDIT_SCORE, rel=1e-9)
    assert int(baseline["approved"].sum()) == SUM_APPROVED


# Pinned from the first live run on the pre-refactor code (captured, not invented).
# num_records=500, random_seed=42, label_noise_rate=0.05.
SUM_ANNUAL_INCOME = 49444038.86999999
SUM_CREDIT_SCORE = 432789.0
SUM_APPROVED = 276
