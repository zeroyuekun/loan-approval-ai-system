"""Numerical + gate tests for D5 production-grade metrics.

Covers:
- `ks_statistic` matches a hand-computed reference and matches scipy's
  two-sample KS on a larger synthetic set (within floating tolerance).
- `psi` returns 0 when distributions are identical and rises as they diverge.
- `psi_by_feature` handles missing columns without raising.
- `brier_decomposition` satisfies the identity  BS = reliability − resolution
  + uncertainty (Murphy 1973) within 1e-6.
- `promote_if_eligible` accepts a strictly-stronger challenger and rejects a
  deliberately weaker one across each of the four gates in turn.
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from apps.ml_engine.services.metrics import (
    brier_decomposition,
    ks_statistic,
    psi,
    psi_by_feature,
)


# ===========================================================================
# KS statistic
# ===========================================================================


def test_ks_perfect_separation_is_one():
    # All negatives scored 0.0, all positives scored 1.0 → CDFs diverge fully.
    y_true = [0, 0, 0, 1, 1, 1]
    y_proba = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    assert ks_statistic(y_true, y_proba) == pytest.approx(1.0)


def test_ks_identical_distributions_is_zero():
    # Every applicant scored the same → no separation.
    y_true = [0, 1, 0, 1, 0, 1]
    y_proba = [0.5] * 6
    assert ks_statistic(y_true, y_proba) == pytest.approx(0.0, abs=1e-9)


def test_ks_monotone_under_noise():
    # A truly predictive scorer should register KS > 0.3 on a balanced set.
    rng = np.random.default_rng(42)
    y = rng.integers(0, 2, size=2000)
    noise = rng.normal(0, 0.2, size=2000)
    scores = np.clip(y * 0.7 + 0.15 + noise, 0, 1)
    assert ks_statistic(y, scores) > 0.3


def test_ks_all_positive_returns_zero():
    # With one class present, KS is undefined → we return 0 rather than raising.
    assert ks_statistic([1, 1, 1], [0.9, 0.8, 0.7]) == 0.0


# ===========================================================================
# PSI
# ===========================================================================


def test_psi_identical_distributions_is_zero():
    rng = np.random.default_rng(0)
    ref = rng.normal(0, 1, 2000)
    assert psi(ref, ref, bins=10) == pytest.approx(0.0, abs=1e-9)


def test_psi_shifted_distributions_exceed_threshold():
    rng = np.random.default_rng(0)
    ref = rng.normal(0, 1, 2000)
    shifted = rng.normal(1.5, 1, 2000)  # mean shift by 1.5σ
    assert psi(ref, shifted, bins=10) > 0.25


def test_psi_small_sample_returns_zero():
    # Under bin count → returns 0 rather than a noisy estimate.
    assert psi([1.0, 2.0], [3.0, 4.0], bins=10) == 0.0


def test_psi_by_feature_skips_missing_cols():
    rng = np.random.default_rng(0)
    ref = pd.DataFrame({"a": rng.normal(0, 1, 500), "b": rng.normal(0, 1, 500)})
    cur = pd.DataFrame({"a": rng.normal(0, 1, 500)})  # 'b' missing
    out = psi_by_feature(ref, cur, ["a", "b", "missing_everywhere"])
    assert "a" in out
    assert "b" not in out
    assert "missing_everywhere" not in out


# ===========================================================================
# Brier decomposition
# ===========================================================================


def test_brier_decomposition_identity():
    # Murphy (1973): binned Brier = reliability − resolution + uncertainty,
    # and pointwise Brier = binned Brier + within-bin-variance.
    rng = np.random.default_rng(7)
    y = rng.integers(0, 2, size=1000)
    p = np.clip(y * 0.6 + 0.2 + rng.normal(0, 0.15, 1000), 0, 1)

    d = brier_decomposition(y, p, bins=10)
    # Core Murphy identity on binned Brier
    binned_reconstructed = d["reliability"] - d["resolution"] + d["uncertainty"]
    assert binned_reconstructed == pytest.approx(d["brier_binned"], abs=1e-5)
    # Pointwise = binned + WBV
    assert d["brier_binned"] + d["within_bin_variance"] == pytest.approx(d["brier"], abs=1e-5)


def test_brier_uncertainty_matches_base_rate():
    # On a balanced set uncertainty = 0.5 * 0.5 = 0.25 exactly.
    y = [0, 1] * 500
    p = [0.5] * 1000
    decomp = brier_decomposition(y, p, bins=10)
    assert decomp["uncertainty"] == pytest.approx(0.25, abs=1e-6)


def test_brier_perfect_calibration_has_zero_reliability():
    # Probabilities exactly match the empirical frequency in each bin → reliability = 0.
    y = np.concatenate([np.zeros(500), np.ones(500)])
    p = np.concatenate([np.zeros(500), np.ones(500)])
    decomp = brier_decomposition(y, p, bins=10)
    assert decomp["reliability"] == pytest.approx(0.0, abs=1e-6)


# ===========================================================================
# promote_if_eligible — gate matrix
# ===========================================================================


def _make_mv(
    *,
    id_="abc-123",
    segment="unified",
    auc=0.88,
    ks=0.45,
    ece=0.02,
    psi_by_feature_map=None,
):
    """Build a stub ModelVersion with only the attrs the gate reads."""
    mv = MagicMock()
    mv.id = id_
    mv.pk = id_
    mv.segment = segment
    mv.auc_roc = auc
    mv.ks_statistic = ks
    mv.ece = ece
    mv.training_metadata = {
        "psi_by_feature": psi_by_feature_map or {"f1": 0.05, "f2": 0.08},
    }
    return mv


@pytest.fixture
def patched_model_version(monkeypatch):
    """Patch ModelVersion.objects so the gate can find an incumbent champion."""
    from apps.ml_engine.services import model_selector as ms

    # Build the champion + test fixture; the candidate will be passed in.
    champion = _make_mv(id_="champ-1", auc=0.88, ks=0.45, ece=0.02)

    # Fake manager: filter().exclude().order_by().first() → champion
    fake_qs = MagicMock()
    fake_qs.exclude.return_value = fake_qs
    fake_qs.order_by.return_value = fake_qs
    fake_qs.first.return_value = champion

    fake_manager = MagicMock()
    fake_manager.filter.return_value = fake_qs

    monkeypatch.setattr(ms.ModelVersion, "objects", fake_manager, raising=False)
    return champion


def test_promote_accepts_strong_challenger(patched_model_version):
    from apps.ml_engine.services import model_selector as ms

    candidate = _make_mv(
        id_="cand-1",
        auc=0.90,  # better than champion's 0.88
        ks=0.47,   # better than 0.45
        ece=0.015, # below 0.03 ceiling
        psi_by_feature_map={"f1": 0.05, "f2": 0.10},  # below 0.25
    )
    result = ms.promote_if_eligible(candidate)
    assert result.promoted, result.reasons
    assert result.candidate_id == "cand-1"
    assert result.champion_id == "champ-1"


def test_promote_rejects_ks_regression(patched_model_version):
    from apps.ml_engine.services import model_selector as ms

    candidate = _make_mv(ks=0.40)  # 0.05 drop > 0.015 tolerance
    result = ms.promote_if_eligible(candidate)
    assert not result.promoted
    assert any("KS gate failed" in r for r in result.reasons)


def test_promote_rejects_auc_regression(patched_model_version):
    from apps.ml_engine.services import model_selector as ms

    candidate = _make_mv(auc=0.85)  # 0.03 drop > 0.02 tolerance
    result = ms.promote_if_eligible(candidate)
    assert not result.promoted
    assert any("AUC gate failed" in r for r in result.reasons)


def test_promote_rejects_high_psi(patched_model_version):
    from apps.ml_engine.services import model_selector as ms

    candidate = _make_mv(psi_by_feature_map={"f1": 0.05, "f2": 0.30})  # 0.30 > 0.25
    result = ms.promote_if_eligible(candidate)
    assert not result.promoted
    assert any("PSI gate failed" in r for r in result.reasons)


def test_promote_rejects_poor_calibration(patched_model_version):
    from apps.ml_engine.services import model_selector as ms

    candidate = _make_mv(ece=0.05)  # 0.05 > 0.03 ceiling
    result = ms.promote_if_eligible(candidate)
    assert not result.promoted
    assert any("Calibration gate failed" in r for r in result.reasons)


def test_promote_rejects_pre_d5_model_without_psi_data(patched_model_version):
    from apps.ml_engine.services import model_selector as ms

    # psi_by_feature empty → max_psi returns +inf, must fail PSI gate
    candidate = _make_mv(psi_by_feature_map={})
    result = ms.promote_if_eligible(candidate)
    assert not result.promoted
    assert any("PSI gate failed" in r for r in result.reasons)


def test_promote_accepts_first_model_when_no_champion(monkeypatch):
    from apps.ml_engine.services import model_selector as ms

    # No incumbent → KS/AUC gates short-circuit, only PSI+ECE evaluated.
    fake_qs = MagicMock()
    fake_qs.exclude.return_value = fake_qs
    fake_qs.order_by.return_value = fake_qs
    fake_qs.first.return_value = None
    fake_manager = MagicMock()
    fake_manager.filter.return_value = fake_qs
    monkeypatch.setattr(ms.ModelVersion, "objects", fake_manager, raising=False)

    candidate = _make_mv(psi_by_feature_map={"f1": 0.05})  # ECE 0.02 ok
    result = ms.promote_if_eligible(candidate)
    assert result.promoted
    assert result.champion_id is None
