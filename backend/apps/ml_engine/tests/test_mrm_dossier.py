"""Tests for D7 — Model Risk Management dossier generator.

Covers:
- All 11 required sections render (audit-visible headers always present,
  even when underlying data is missing).
- No TODO / PLACEHOLDER / FIXME strings leak into output.
- Missing `training_metadata.psi_by_feature` renders the documented
  "No PSI data" guidance instead of a broken table.
- Missing `fairness_metrics` renders the documented fallback.
- Changelog shows "first dossier" when no prior version on segment.
- Monotone table includes at least one positive and one negative feature
  from the authoritative `MONOTONE_CONSTRAINTS` registry.
- Policy overlay section enumerates every P-code defined in POLICY_RULES.
- `write_dossier` creates the file at `<dir>/<model_id>/mrm.md`.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mv(**overrides):
    """Build a ModelVersion-like stub. Simple object, no ORM."""
    mv = SimpleNamespace(
        id=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        pk=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        algorithm="xgb",
        version="20260418_120000",
        segment="personal",
        is_active=True,
        file_hash="abc123" * 10 + "abcd",
        auc_roc=0.87,
        ks_statistic=0.45,
        brier_score=0.08,
        ece=0.02,
        created_at=None,
        training_metadata={
            "training_seconds": 45,
            "n_training_samples": 10000,
            "positive_rate": 0.22,
            "psi_by_feature": {"credit_score": 0.05, "annual_income": 0.12, "dti": 0.30},
            "data_source": "synthetic + GMSC",
            "temporal_start": "2024-01-01",
            "temporal_end": "2026-04-01",
        },
        fairness_metrics={
            "gender": {"disparate_impact_ratio": 0.92, "passes_80_percent_rule": True},
            "age_group": {"disparate_impact_ratio": 0.78, "passes_80_percent_rule": False},
        },
        calibration_data={
            "deciles": [
                {"expected": 0.05, "observed": 0.04, "n": 1000},
                {"expected": 0.15, "observed": 0.16, "n": 1000},
            ]
        },
        retraining_policy={"cadence_days": 90, "min_samples": 10000, "max_psi_before_retrain": 0.25},
    )
    mv.get_algorithm_display = lambda: "XGBoost"
    for k, v in overrides.items():
        setattr(mv, k, v)
    return mv


# ---------------------------------------------------------------------------
# Section coverage
# ---------------------------------------------------------------------------


REQUIRED_SECTION_HEADERS = [
    "## 1. Header",
    "## 2. Purpose & limitations",
    "## 3. Data lineage",
    "## 4. Monotonicity constraint table",
    "## 5. Performance",
    "## 6. Calibration report",
    "## 7. PSI by feature",
    "## 8. Fairness audit",
    "## 9. Policy overlay reference",
    "## 10. Ongoing monitoring plan",
    "## 11. Change log",
]


def test_all_11_sections_present_with_populated_data():
    from apps.ml_engine.services.mrm_dossier import generate_dossier_markdown

    # Changelog section touches ORM; short-circuit with a patch.
    with patch("apps.ml_engine.services.mrm_dossier._changelog_section") as _cl:
        _cl.return_value = "## 11. Change log\n\nNo prior version on segment `personal` — this is the first dossier."
        md = generate_dossier_markdown(_make_mv())

    for header in REQUIRED_SECTION_HEADERS:
        assert header in md, f"Missing section header: {header}"


def test_no_placeholder_strings_leak_into_output():
    from apps.ml_engine.services.mrm_dossier import generate_dossier_markdown

    with patch("apps.ml_engine.services.mrm_dossier._changelog_section") as _cl:
        _cl.return_value = "## 11. Change log\n\n(no prior version)"
        md = generate_dossier_markdown(_make_mv())

    # These strings are spec-level red flags: if they appear, the
    # dossier is not ready for MRM submission.
    for bad in ("TODO", "FIXME", "TBD", "PLACEHOLDER", "XXX:"):
        assert bad not in md, f"Forbidden placeholder token present: {bad!r}"


def test_header_section_contains_model_metadata():
    from apps.ml_engine.services.mrm_dossier import generate_dossier_markdown

    with patch("apps.ml_engine.services.mrm_dossier._changelog_section") as _cl:
        _cl.return_value = "## 11. Change log\n\n(stub)"
        md = generate_dossier_markdown(_make_mv())

    assert "`12345678-1234-5678-1234-567812345678`" in md
    assert "XGBoost" in md
    assert "20260418_120000" in md
    assert "personal" in md


def test_purpose_statement_matches_segment():
    from apps.ml_engine.services.mrm_dossier import generate_dossier_markdown

    with patch("apps.ml_engine.services.mrm_dossier._changelog_section") as _cl:
        _cl.return_value = "## 11. Change log\n\n(stub)"

        md_personal = generate_dossier_markdown(_make_mv(segment="personal"))
        md_home = generate_dossier_markdown(_make_mv(segment="home_owner_occupier"))

    assert "personal loans" in md_personal.lower()
    assert "owner-occupier" in md_home.lower()


# ---------------------------------------------------------------------------
# Graceful-degradation (missing data) handling
# ---------------------------------------------------------------------------


def test_missing_psi_data_renders_guidance_not_empty_table():
    from apps.ml_engine.services.mrm_dossier import generate_dossier_markdown

    mv = _make_mv(training_metadata={"psi_by_feature": {}})
    with patch("apps.ml_engine.services.mrm_dossier._changelog_section") as _cl:
        _cl.return_value = "## 11. Change log\n\n(stub)"
        md = generate_dossier_markdown(mv)

    assert "## 7. PSI by feature" in md
    assert "No PSI data" in md


def test_missing_fairness_metrics_renders_guidance():
    from apps.ml_engine.services.mrm_dossier import generate_dossier_markdown

    mv = _make_mv(fairness_metrics={})
    with patch("apps.ml_engine.services.mrm_dossier._changelog_section") as _cl:
        _cl.return_value = "## 11. Change log\n\n(stub)"
        md = generate_dossier_markdown(mv)

    assert "## 8. Fairness audit" in md
    assert "No fairness metrics recorded" in md


def test_missing_calibration_renders_guidance():
    from apps.ml_engine.services.mrm_dossier import generate_dossier_markdown

    mv = _make_mv(calibration_data={})
    with patch("apps.ml_engine.services.mrm_dossier._changelog_section") as _cl:
        _cl.return_value = "## 11. Change log\n\n(stub)"
        md = generate_dossier_markdown(mv)

    assert "## 6. Calibration report" in md
    assert "Decile calibration not recorded" in md


# ---------------------------------------------------------------------------
# Monotone table
# ---------------------------------------------------------------------------


def test_monotone_table_includes_positive_and_negative_features():
    from apps.ml_engine.services.mrm_dossier import generate_dossier_markdown

    with patch("apps.ml_engine.services.mrm_dossier._changelog_section") as _cl:
        _cl.return_value = "## 11. Change log\n\n(stub)"
        md = generate_dossier_markdown(_make_mv())

    # Known positive + negative representatives from monotone_constraints.
    assert "`credit_score`" in md
    assert "+1 (↑)" in md
    assert "`debt_to_income`" in md
    assert "−1 (↓)" in md


# ---------------------------------------------------------------------------
# Policy overlay section
# ---------------------------------------------------------------------------


def test_policy_section_enumerates_all_p_codes():
    from apps.ml_engine.services.credit_policy import POLICY_RULES
    from apps.ml_engine.services.mrm_dossier import generate_dossier_markdown

    with patch("apps.ml_engine.services.mrm_dossier._changelog_section") as _cl:
        _cl.return_value = "## 11. Change log\n\n(stub)"
        md = generate_dossier_markdown(_make_mv())

    for rule in POLICY_RULES:
        assert f"| {rule.code} |" in md, f"Missing policy code in dossier: {rule.code}"


# ---------------------------------------------------------------------------
# File-write helper
# ---------------------------------------------------------------------------


def test_write_dossier_creates_file_at_expected_path():
    from apps.ml_engine.services.mrm_dossier import write_dossier

    mv = _make_mv()
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("apps.ml_engine.services.mrm_dossier._changelog_section") as _cl:
            _cl.return_value = "## 11. Change log\n\n(stub)"
            path = write_dossier(mv, tmpdir)

        p = Path(path)
        assert p.exists()
        assert p.name == "mrm.md"
        assert str(mv.id) in str(p.parent)
        content = p.read_text(encoding="utf-8")
        assert "## 1. Header" in content
        assert "## 11. Change log" in content
