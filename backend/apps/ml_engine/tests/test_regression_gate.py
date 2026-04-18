"""Tests for the golden-metrics regression gate.

Two layers:

1. **Pure-functional** — `check_regression(metrics, golden)` is exercised
   against hand-built metric + baseline dicts to pin the drop/rise
   arithmetic. These tests do not touch Django.

2. **Golden-file integrity** — `ml_models/golden_metrics.json` loads,
   parses, and contains the expected schema keys.

The "does the *currently-active* model still beat the golden file" test
is intentionally skip-if-no-active-model so a fresh clone's CI stays
green. In production CI, a nightly cron that trains a fresh model
against the test dataset runs the same assertion with `fail_on_missing`
semantics separately from this file.
"""

from __future__ import annotations

import pytest

from apps.ml_engine.services.regression_gate import (
    check_regression,
    load_golden,
)

# ---------------------------------------------------------------------------
# Golden file — shape + load integrity
# ---------------------------------------------------------------------------


def test_golden_metrics_file_loads():
    golden = load_golden()
    assert golden is not None, "ml_models/golden_metrics.json must exist and parse"
    assert golden.get("schema_version") == 1
    assert "metrics" in golden
    assert "tolerances" in golden


def test_golden_metrics_has_all_required_baselines():
    golden = load_golden()
    required = {"auc_roc", "ks_statistic", "brier_score", "ece"}
    assert required.issubset(golden["metrics"].keys())


def test_golden_metrics_has_all_required_tolerances():
    golden = load_golden()
    required = {
        "auc_roc_drop_pp",
        "ks_statistic_drop_pp",
        "brier_score_rise_pp",
        "ece_rise_pp",
    }
    assert required.issubset(golden["tolerances"].keys())


# ---------------------------------------------------------------------------
# check_regression — higher-is-better drops
# ---------------------------------------------------------------------------


def _baseline(auc=0.87, ks=0.45, brier=0.10, ece=0.03, auc_tol=0.02, ks_tol=0.015, brier_tol=0.02, ece_tol=0.015):
    return {
        "metrics": {"auc_roc": auc, "ks_statistic": ks, "brier_score": brier, "ece": ece},
        "tolerances": {
            "auc_roc_drop_pp": auc_tol,
            "ks_statistic_drop_pp": ks_tol,
            "brier_score_rise_pp": brier_tol,
            "ece_rise_pp": ece_tol,
        },
    }


def test_clean_metrics_no_breaches():
    observed = {"auc_roc": 0.87, "ks_statistic": 0.45, "brier_score": 0.10, "ece": 0.03}
    assert check_regression(observed, _baseline()) == []


def test_auc_drop_within_tolerance_passes():
    # 0.015 drop < 0.02 tolerance → OK
    observed = {"auc_roc": 0.855, "ks_statistic": 0.45, "brier_score": 0.10, "ece": 0.03}
    assert check_regression(observed, _baseline()) == []


def test_auc_drop_beyond_tolerance_breaches():
    # 0.05 drop > 0.02 tolerance → breach
    observed = {"auc_roc": 0.82, "ks_statistic": 0.45, "brier_score": 0.10, "ece": 0.03}
    breaches = check_regression(observed, _baseline())
    assert len(breaches) == 1
    assert "auc_roc" in breaches[0]


def test_ks_drop_beyond_tolerance_breaches():
    # 0.02 drop > 0.015 tolerance
    observed = {"auc_roc": 0.87, "ks_statistic": 0.43, "brier_score": 0.10, "ece": 0.03}
    breaches = check_regression(observed, _baseline())
    assert any("ks_statistic" in b for b in breaches)


# ---------------------------------------------------------------------------
# check_regression — lower-is-better rises
# ---------------------------------------------------------------------------


def test_brier_rise_within_tolerance_passes():
    observed = {"auc_roc": 0.87, "ks_statistic": 0.45, "brier_score": 0.115, "ece": 0.03}
    # rise=0.015 < tol 0.02
    assert check_regression(observed, _baseline()) == []


def test_brier_rise_beyond_tolerance_breaches():
    observed = {"auc_roc": 0.87, "ks_statistic": 0.45, "brier_score": 0.14, "ece": 0.03}
    breaches = check_regression(observed, _baseline())
    assert any("brier_score" in b for b in breaches)


def test_ece_rise_beyond_tolerance_breaches():
    observed = {"auc_roc": 0.87, "ks_statistic": 0.45, "brier_score": 0.10, "ece": 0.055}
    breaches = check_regression(observed, _baseline())
    assert any("ece" in b for b in breaches)


# ---------------------------------------------------------------------------
# Compound + resilience
# ---------------------------------------------------------------------------


def test_multiple_simultaneous_breaches_all_reported():
    observed = {"auc_roc": 0.80, "ks_statistic": 0.40, "brier_score": 0.15, "ece": 0.10}
    breaches = check_regression(observed, _baseline())
    assert len(breaches) == 4
    joined = " | ".join(breaches)
    for metric in ("auc_roc", "ks_statistic", "brier_score", "ece"):
        assert metric in joined


def test_missing_metric_is_skipped_not_failed():
    observed = {"auc_roc": 0.87}  # everything else missing
    assert check_regression(observed, _baseline()) == []


def test_missing_tolerance_is_skipped_not_failed():
    observed = {"auc_roc": 0.82}
    golden = _baseline()
    golden["tolerances"].pop("auc_roc_drop_pp")
    assert check_regression(observed, golden) == []


def test_non_numeric_metric_is_skipped():
    observed = {"auc_roc": "n/a"}
    assert check_regression(observed, _baseline()) == []


# ---------------------------------------------------------------------------
# Active-model integration — skip when no model exists
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_active_model_against_golden_file_skip_if_none():
    from apps.ml_engine.services.regression_gate import active_model_metrics

    metrics = active_model_metrics()
    golden = load_golden()
    if metrics is None or golden is None:
        pytest.skip("No active model or no golden file — first-run environment")

    breaches = check_regression(metrics, golden)
    assert breaches == [], (
        f"Active model regressed beyond tolerance: {breaches}. "
        "If intentional (new champion promoted), refresh ml_models/golden_metrics.json."
    )
