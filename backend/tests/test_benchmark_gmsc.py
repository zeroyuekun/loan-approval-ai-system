"""Unit tests for scripts.benchmark_gmsc — the CI-safe parts.

The full benchmark (Optuna search + 5-fold CV on 150k rows) is NOT run in
CI: it's a heavy manual benchmark. These tests exercise the lightweight
pure functions — loader, preprocessor, integrity check — against a
synthetic 150k-row CSV that mimics the GMSC schema.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts import benchmark_gmsc as bg


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_gmsc(tmp_path: Path) -> Path:
    """Build a 150k-row CSV with the GMSC schema and realistic class balance."""
    rng = np.random.default_rng(0)
    n = bg.EXPECTED_ROWS
    df = pd.DataFrame(
        {
            "Unnamed: 0": np.arange(1, n + 1),
            "SeriousDlqin2yrs": rng.binomial(1, 0.067, n),
            "RevolvingUtilizationOfUnsecuredLines": rng.beta(2, 5, n),
            "age": rng.integers(21, 90, n),
            "NumberOfTime30-59DaysPastDueNotWorse": rng.poisson(0.3, n),
            "DebtRatio": rng.gamma(2, 0.3, n),
            "MonthlyIncome": rng.lognormal(8.5, 0.8, n),
            "NumberOfOpenCreditLinesAndLoans": rng.poisson(8, n),
            "NumberOfTimes90DaysLate": rng.poisson(0.1, n),
            "NumberRealEstateLoansOrLines": rng.poisson(1, n),
            "NumberOfTime60-89DaysPastDueNotWorse": rng.poisson(0.2, n),
            "NumberOfDependents": rng.poisson(1, n).astype(float),
        }
    )
    # Inject ~20% MonthlyIncome NaNs (matches real GMSC)
    nan_idx = rng.choice(n, size=int(n * 0.2), replace=False)
    df.loc[nan_idx, "MonthlyIncome"] = np.nan
    # Inject a handful of NumberOfDependents NaNs
    dep_nan = rng.choice(n, size=100, replace=False)
    df.loc[dep_nan, "NumberOfDependents"] = np.nan

    out = tmp_path / "cs-training.csv"
    df.to_csv(out, index=False)
    return out


# ---------------------------------------------------------------------------
# Loader + preprocessor
# ---------------------------------------------------------------------------


class TestLoadAndPreprocess:
    def test_returns_expected_shape(self, synthetic_gmsc: Path):
        X, y = bg.load_and_preprocess(synthetic_gmsc)
        assert X.shape == (bg.EXPECTED_ROWS, len(bg.FEATURE_COLS))
        assert y.shape == (bg.EXPECTED_ROWS,)

    def test_no_nans_after_preprocess(self, synthetic_gmsc: Path):
        X, y = bg.load_and_preprocess(synthetic_gmsc)
        assert not X.isna().any().any(), "preprocessing must eliminate all NaNs"
        assert not y.isna().any()

    def test_monthly_income_99th_cap(self, synthetic_gmsc: Path):
        raw = pd.read_csv(synthetic_gmsc)
        X, _ = bg.load_and_preprocess(synthetic_gmsc)
        # After cap, max MonthlyIncome should equal the 99th percentile of
        # the median-imputed column.
        imputed = raw["MonthlyIncome"].fillna(raw["MonthlyIncome"].median())
        expected_cap = imputed.quantile(0.99)
        assert X["MonthlyIncome"].max() == pytest.approx(expected_cap, rel=1e-6)

    def test_dependents_integer_dtype(self, synthetic_gmsc: Path):
        X, _ = bg.load_and_preprocess(synthetic_gmsc)
        assert pd.api.types.is_integer_dtype(X["NumberOfDependents"])

    def test_wrong_row_count_raises(self, tmp_path: Path):
        df = pd.DataFrame(
            {col: [0.0] for col in bg.FEATURE_COLS + [bg.TARGET_COL]}
        )
        p = tmp_path / "bad.csv"
        df.to_csv(p, index=False)
        with pytest.raises(RuntimeError, match="Expected 150000 rows"):
            bg.load_and_preprocess(p)

    def test_missing_column_raises(self, tmp_path: Path):
        rng = np.random.default_rng(0)
        # Correct row count but missing a feature column
        df = pd.DataFrame(
            {col: rng.random(bg.EXPECTED_ROWS) for col in bg.FEATURE_COLS[:-1]}
        )
        df[bg.TARGET_COL] = rng.integers(0, 2, bg.EXPECTED_ROWS)
        p = tmp_path / "short.csv"
        df.to_csv(p, index=False)
        with pytest.raises(RuntimeError, match="Missing expected columns"):
            bg.load_and_preprocess(p)


# ---------------------------------------------------------------------------
# Integrity check
# ---------------------------------------------------------------------------


class TestDownloadIntegrity:
    def test_sha_mismatch_raises(self, tmp_path: Path, monkeypatch):
        # Write a known file
        p = tmp_path / "cs-training.csv"
        p.write_bytes(b"not the real data")

        monkeypatch.setattr(bg, "_cache_dir", lambda: tmp_path)
        monkeypatch.setattr(bg, "EXPECTED_SHA256", "0" * 64)

        with pytest.raises(RuntimeError, match="SHA256 mismatch"):
            bg.download_gmsc(assume_yes=True)

    def test_sha_match_passes(self, tmp_path: Path, monkeypatch):
        p = tmp_path / "cs-training.csv"
        p.write_bytes(b"payload")
        expected = hashlib.sha256(b"payload").hexdigest()

        monkeypatch.setattr(bg, "_cache_dir", lambda: tmp_path)
        monkeypatch.setattr(bg, "EXPECTED_SHA256", expected)

        result = bg.download_gmsc(assume_yes=True)
        assert result == p

    def test_unpinned_sha_warns_but_accepts(self, tmp_path: Path, monkeypatch, caplog):
        p = tmp_path / "cs-training.csv"
        p.write_bytes(b"anything")

        monkeypatch.setattr(bg, "_cache_dir", lambda: tmp_path)
        monkeypatch.setattr(bg, "EXPECTED_SHA256", None)

        with caplog.at_level("WARNING"):
            bg.download_gmsc(assume_yes=True)
        assert any("not pinned" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# KS statistic
# ---------------------------------------------------------------------------


class TestKSStatistic:
    def test_perfect_separation(self):
        y_true = np.array([0, 0, 0, 1, 1, 1])
        y_proba = np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9])
        ks = bg._ks_statistic(y_true, y_proba)
        assert ks == pytest.approx(1.0)

    def test_random_separation_low(self):
        rng = np.random.default_rng(0)
        y_true = rng.integers(0, 2, 1000)
        y_proba = rng.random(1000)
        ks = bg._ks_statistic(y_true, y_proba)
        assert ks < 0.2  # random scores shouldn't separate

    def test_range(self):
        y_true = np.array([0, 1, 1, 0])
        y_proba = np.array([0.5, 0.5, 0.5, 0.5])
        ks = bg._ks_statistic(y_true, y_proba)
        assert 0.0 <= ks <= 1.0
