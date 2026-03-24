"""Tests for CV report generation logic in ModelTrainer.

These are unit tests that validate the cv_report dict structure and
the instability detection logic WITHOUT training a real model.
"""

import numpy as np
import pytest


def build_cv_report(cv_scores):
    """Replicate the CV report generation logic from ModelTrainer.train().

    This mirrors the exact code in trainer.py (lines ~492-514) so we can
    unit-test the report structure and instability flag independently of
    the full training pipeline.
    """
    cv_mean = float(cv_scores.mean())
    cv_std = float(cv_scores.std())
    cv_unstable = bool(cv_scores.max() - cv_scores.min() > 0.06)

    return {
        'n_splits': 5,
        'strategy': 'StratifiedKFold',
        'scoring': 'roc_auc',
        'fold_scores': cv_scores.tolist(),
        'mean': cv_mean,
        'std': cv_std,
        'min': float(cv_scores.min()),
        'max': float(cv_scores.max()),
        'range': float(cv_scores.max() - cv_scores.min()),
        'unstable': cv_unstable,
    }


CV_REPORT_EXPECTED_KEYS = {
    'n_splits', 'strategy', 'scoring', 'fold_scores',
    'mean', 'std', 'min', 'max', 'range', 'unstable',
}


class TestCVReportKeys:
    """Test that the CV report dict contains all expected keys."""

    def test_all_keys_present(self):
        scores = np.array([0.85, 0.86, 0.84, 0.87, 0.85])
        report = build_cv_report(scores)
        assert set(report.keys()) == CV_REPORT_EXPECTED_KEYS

    def test_no_extra_keys(self):
        scores = np.array([0.90, 0.91, 0.89, 0.92, 0.90])
        report = build_cv_report(scores)
        assert set(report.keys()) == CV_REPORT_EXPECTED_KEYS


class TestCVInstabilityFlag:
    """Test the instability detection threshold (range > 0.06)."""

    def test_unstable_when_range_exceeds_threshold(self):
        # Range = 0.10 > 0.06 → unstable
        scores = np.array([0.80, 0.85, 0.90, 0.82, 0.88])
        report = build_cv_report(scores)
        assert report['unstable'] is True

    def test_stable_when_range_within_threshold(self):
        # Range = 0.03 < 0.06 → stable
        scores = np.array([0.85, 0.86, 0.87, 0.86, 0.84])
        report = build_cv_report(scores)
        assert report['unstable'] is False

    def test_stable_when_all_folds_identical(self):
        scores = np.array([0.88, 0.88, 0.88, 0.88, 0.88])
        report = build_cv_report(scores)
        assert report['unstable'] is False
        assert report['range'] == 0.0

    def test_unstable_boundary_just_above(self):
        # Range = 0.061 > 0.06 → unstable
        scores = np.array([0.85, 0.85, 0.85, 0.85, 0.911])
        report = build_cv_report(scores)
        assert report['unstable'] is True

    def test_stable_boundary_below(self):
        # Range = 0.05 → NOT unstable (well below 0.06 threshold)
        scores = np.array([0.85, 0.85, 0.85, 0.85, 0.90])
        report = build_cv_report(scores)
        assert report['unstable'] is False


class TestCVReportTypes:
    """Test that CV report values have correct types."""

    @pytest.fixture
    def report(self):
        scores = np.array([0.82, 0.85, 0.84, 0.86, 0.83])
        return build_cv_report(scores)

    def test_mean_is_float(self, report):
        assert isinstance(report['mean'], float)

    def test_std_is_float(self, report):
        assert isinstance(report['std'], float)

    def test_min_is_float(self, report):
        assert isinstance(report['min'], float)

    def test_max_is_float(self, report):
        assert isinstance(report['max'], float)

    def test_range_is_float(self, report):
        assert isinstance(report['range'], float)

    def test_fold_scores_is_list(self, report):
        assert isinstance(report['fold_scores'], list)

    def test_fold_scores_length(self, report):
        assert len(report['fold_scores']) == 5

    def test_fold_scores_elements_are_float(self, report):
        assert all(isinstance(s, float) for s in report['fold_scores'])

    def test_unstable_is_bool(self, report):
        assert isinstance(report['unstable'], bool)

    def test_n_splits_is_int(self, report):
        assert isinstance(report['n_splits'], int)

    def test_strategy_is_str(self, report):
        assert isinstance(report['strategy'], str)

    def test_scoring_is_str(self, report):
        assert isinstance(report['scoring'], str)


class TestCVReportValues:
    """Test that computed values are mathematically correct."""

    def test_mean_value(self):
        scores = np.array([0.80, 0.82, 0.84, 0.86, 0.88])
        report = build_cv_report(scores)
        assert report['mean'] == pytest.approx(0.84, abs=1e-10)

    def test_min_max_correct(self):
        scores = np.array([0.80, 0.82, 0.84, 0.86, 0.88])
        report = build_cv_report(scores)
        assert report['min'] == pytest.approx(0.80)
        assert report['max'] == pytest.approx(0.88)

    def test_range_equals_max_minus_min(self):
        scores = np.array([0.75, 0.82, 0.84, 0.86, 0.90])
        report = build_cv_report(scores)
        assert report['range'] == pytest.approx(report['max'] - report['min'])

    def test_static_fields(self):
        scores = np.array([0.85, 0.86, 0.87, 0.86, 0.84])
        report = build_cv_report(scores)
        assert report['n_splits'] == 5
        assert report['strategy'] == 'StratifiedKFold'
        assert report['scoring'] == 'roc_auc'
