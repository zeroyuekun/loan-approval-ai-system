"""Tests for the MRM dossier's calibration section path lookup.

Regression: the dossier used to read `mv.calibration_data["deciles"]` but
deciles live on a separate `mv.decile_analysis` JSONField. Fix preserves
fallback for legacy bundles that stored deciles inside calibration_data.

Stub deciles match the trainer's actual schema (`actual_rate`, `count`,
`cumulative_rate`, `lift`) so the table renders representative values
instead of all-`None` placeholders.
"""

import pytest
from types import SimpleNamespace

from apps.ml_engine.services.mrm_dossier import _calibration_section


def _stub_mv(decile_analysis=None, calibration_data=None):
    return SimpleNamespace(
        decile_analysis=decile_analysis or {},
        calibration_data=calibration_data or {},
    )


def _real_decile(idx, actual_rate, cumulative_rate, lift, count):
    """Build a row in the trainer's real `compute_decile_analysis` schema."""
    return {
        "decile": idx,
        "count": count,
        "actual_rate": actual_rate,
        "cumulative_rate": cumulative_rate,
        "lift": lift,
    }


def test_calibration_reads_decile_analysis_field():
    """When deciles are on mv.decile_analysis (current trainer output)."""
    deciles = [
        _real_decile(1, actual_rate=0.02, cumulative_rate=0.02, lift=0.4, count=100),
        _real_decile(2, actual_rate=0.05, cumulative_rate=0.035, lift=0.7, count=100),
    ]
    mv = _stub_mv(decile_analysis={"deciles": deciles})
    section = _calibration_section(mv)
    assert "Decile calibration not recorded" not in section
    assert "0.0200" in section  # actual_rate of decile 1 rendered
    assert "0.0500" in section  # actual_rate of decile 2 rendered


def test_calibration_falls_back_to_calibration_data_deciles():
    """Legacy bundles where deciles were nested under calibration_data."""
    deciles = [_real_decile(1, actual_rate=0.01, cumulative_rate=0.01, lift=0.2, count=100)]
    mv = _stub_mv(calibration_data={"deciles": deciles})
    section = _calibration_section(mv)
    assert "Decile calibration not recorded" not in section


def test_calibration_legacy_observed_key_still_renders():
    """Legacy stub schema using `observed` should still be readable via the fallback chain."""
    deciles = [{"decile": 1, "n": 100, "observed": 0.0123}]
    mv = _stub_mv(decile_analysis={"deciles": deciles})
    section = _calibration_section(mv)
    assert "0.0123" in section


def test_calibration_empty_state_when_no_deciles():
    """Both fields empty/absent → empty-state line."""
    mv = _stub_mv()
    section = _calibration_section(mv)
    assert "Decile calibration not recorded" in section
    assert "decile_analysis.deciles" in section
