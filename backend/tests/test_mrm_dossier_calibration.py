"""Tests for the MRM dossier's calibration section path lookup.

Regression: the dossier used to read `mv.calibration_data["deciles"]` but
deciles live on a separate `mv.decile_analysis` JSONField. Fix preserves
fallback for legacy bundles that stored deciles inside calibration_data.
"""

import pytest
from types import SimpleNamespace

from apps.ml_engine.services.mrm_dossier import _calibration_section


def _stub_mv(decile_analysis=None, calibration_data=None):
    return SimpleNamespace(
        decile_analysis=decile_analysis or {},
        calibration_data=calibration_data or {},
    )


def test_calibration_reads_decile_analysis_field():
    """When deciles are on mv.decile_analysis (current trainer output)."""
    deciles = [
        {"decile": 1, "n": 100, "actual_default_rate": 0.02, "predicted_default_rate": 0.018},
        {"decile": 2, "n": 100, "actual_default_rate": 0.05, "predicted_default_rate": 0.048},
    ]
    mv = _stub_mv(decile_analysis={"deciles": deciles})
    section = _calibration_section(mv)
    assert "Decile calibration not recorded" not in section
    assert "0.02" in section or "2.0%" in section or "0.018" in section


def test_calibration_falls_back_to_calibration_data_deciles():
    """Legacy bundles where deciles were nested under calibration_data."""
    deciles = [{"decile": 1, "n": 100, "actual_default_rate": 0.01, "predicted_default_rate": 0.012}]
    mv = _stub_mv(calibration_data={"deciles": deciles})
    section = _calibration_section(mv)
    assert "Decile calibration not recorded" not in section


def test_calibration_empty_state_when_no_deciles():
    """Both fields empty/absent → empty-state line."""
    mv = _stub_mv()
    section = _calibration_section(mv)
    assert "Decile calibration not recorded" in section
    assert "decile_analysis.deciles" in section  # new canonical path in the message
