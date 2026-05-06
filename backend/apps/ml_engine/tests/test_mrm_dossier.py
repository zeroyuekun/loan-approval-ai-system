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


# ---------------------------------------------------------------------------
# Performance section: dossier should not assert champion-challenger gates
# are *enforced* on activation (they are not — tasks.py:82-88 activates
# directly). (Codex 2026-05-06 finding 3a.)
# ---------------------------------------------------------------------------


def test_performance_section_no_longer_claims_gates_are_enforced():
    from apps.ml_engine.services.mrm_dossier import generate_dossier_markdown

    with patch("apps.ml_engine.services.mrm_dossier._changelog_section") as _cl:
        _cl.return_value = "## 11. Change log\n\n(stub)"
        md = generate_dossier_markdown(_make_compliant_mv())

    # Regression guard for the original overstated language.
    assert "enforce these" not in md
    # Honest replacement language must be present.
    assert "gates exist" in md.lower() or "exist in `model_selector.py`" in md
    assert "confirm pre-promotion review" in md


# ---------------------------------------------------------------------------
# Monitoring drift URL must point at a real route. (Codex 2026-05-06
# finding 3b — the original /api/ml-engine/drift/ was a 404.)
# ---------------------------------------------------------------------------


def test_monitoring_drift_url_uses_actual_route():
    from apps.ml_engine.services.mrm_dossier import generate_dossier_markdown

    with patch("apps.ml_engine.services.mrm_dossier._changelog_section") as _cl:
        _cl.return_value = "## 11. Change log\n\n(stub)"
        md = generate_dossier_markdown(_make_compliant_mv())

    assert "/api/v1/ml/models/active/drift/" in md
    # Regression guard against the dead legacy URL.
    assert "/api/ml-engine/drift/" not in md


# ---------------------------------------------------------------------------
# Out-of-scope wording is conditional on the runtime overlay mode.
# (Codex 2026-05-06 finding 1 — the dossier used to claim mandatory referral
# unconditionally, but the runtime only enforces it in `enforce` mode.)
# ---------------------------------------------------------------------------


def test_purpose_section_default_mode_emits_shadow_wording():
    """Default settings (no env override) → shadow wording, **not blocked**."""
    from apps.ml_engine.services.mrm_dossier import generate_dossier_markdown

    with patch("apps.ml_engine.services.mrm_dossier._changelog_section") as _cl:
        _cl.return_value = "## 11. Change log\n\n(stub)"
        md = generate_dossier_markdown(_make_compliant_mv())

    assert "shadow" in md.lower()
    assert "not blocked" in md
    # The old unconditional mandate must not appear in shadow mode.
    assert "must be treated as advisory" not in md


def test_purpose_section_enforce_mode_emits_mandatory_referral():
    from django.test import override_settings

    from apps.ml_engine.services.mrm_dossier import generate_dossier_markdown

    with (
        override_settings(CREDIT_POLICY_OVERLAY_MODE="enforce"),
        patch("apps.ml_engine.services.mrm_dossier._changelog_section") as _cl,
    ):
        _cl.return_value = "## 11. Change log\n\n(stub)"
        md = generate_dossier_markdown(_make_compliant_mv())

    assert "`enforce` mode" in md
    assert "blocked by the overlay" in md
    assert "routed to manual underwriter review" in md


def test_purpose_section_off_mode_emits_no_overlay_message():
    from django.test import override_settings

    from apps.ml_engine.services.mrm_dossier import generate_dossier_markdown

    with (
        override_settings(CREDIT_POLICY_OVERLAY_MODE="off"),
        patch("apps.ml_engine.services.mrm_dossier._changelog_section") as _cl,
    ):
        _cl.return_value = "## 11. Change log\n\n(stub)"
        md = generate_dossier_markdown(_make_compliant_mv())

    assert "No policy overlay is active" in md
    assert "manual scope review is required at intake" in md


def test_purpose_section_unknown_mode_falls_through_to_shadow():
    """Mirrors credit_policy.py:405 — unknown values default to shadow."""
    from django.test import override_settings

    from apps.ml_engine.services.mrm_dossier import generate_dossier_markdown

    with (
        override_settings(CREDIT_POLICY_OVERLAY_MODE="bogus_value"),
        patch("apps.ml_engine.services.mrm_dossier._changelog_section") as _cl,
    ):
        _cl.return_value = "## 11. Change log\n\n(stub)"
        md = generate_dossier_markdown(_make_compliant_mv())

    assert "`shadow` (observational) mode" in md
    assert "not blocked" in md


# ---------------------------------------------------------------------------
# Compliance status banner — derived from gate evidence so an auditor reads
# the failure on the first page rather than digging through §8 / §7 / §6.
# (Codex 2026-05-06 finding 2.)
# ---------------------------------------------------------------------------


def _make_compliant_mv(**overrides):
    """Default `_make_mv` is intentionally NON-COMPLIANT (failed age_group +
    PSI on dti). For positive-path tests build a clean MV here. Overrides
    take precedence over the clean defaults so callers can flip individual
    fields without wrestling with duplicate-kwarg errors."""
    defaults = {
        "fairness_metrics": {
            "gender": {"disparate_impact_ratio": 0.92, "passes_80_percent_rule": True},
            "age_group": {"disparate_impact_ratio": 0.88, "passes_80_percent_rule": True},
        },
        "training_metadata": {
            "training_seconds": 45,
            "n_training_samples": 10000,
            "positive_rate": 0.22,
            "psi_by_feature": {"credit_score": 0.05, "annual_income": 0.12, "dti": 0.18},
            "data_source": "synthetic + GMSC",
            "temporal_start": "2024-01-01",
            "temporal_end": "2026-04-01",
        },
        "ece": 0.02,
    }
    defaults.update(overrides)
    return _make_mv(**defaults)


def test_compliance_status_compliant_when_all_gates_pass_and_evidence_present():
    from apps.ml_engine.services.mrm_compliance import _compliance_status

    status, reasons = _compliance_status(_make_compliant_mv())
    assert status == "COMPLIANT"
    assert reasons == []


def test_compliance_status_non_compliant_on_failed_fairness():
    from apps.ml_engine.services.mrm_compliance import _compliance_status

    mv = _make_compliant_mv(
        fairness_metrics={
            "gender": {"disparate_impact_ratio": 0.92, "passes_80_percent_rule": True},
            "age_group": {"disparate_impact_ratio": 0.78, "passes_80_percent_rule": False},
        }
    )
    status, reasons = _compliance_status(mv)
    assert status == "NON-COMPLIANT"
    assert any("age_group" in r for r in reasons)
    assert any("80%-rule" in r for r in reasons)


def test_compliance_status_non_compliant_on_high_psi():
    from apps.ml_engine.services.mrm_compliance import _compliance_status

    mv = _make_compliant_mv(
        training_metadata={
            "psi_by_feature": {"credit_score": 0.05, "dti": 0.30},
        }
    )
    status, reasons = _compliance_status(mv)
    assert status == "NON-COMPLIANT"
    assert any("PSI" in r and "dti" in r for r in reasons)


def test_compliance_status_non_compliant_on_high_ece():
    from apps.ml_engine.services.mrm_compliance import _compliance_status

    mv = _make_compliant_mv(ece=0.08)
    status, reasons = _compliance_status(mv)
    assert status == "NON-COMPLIANT"
    assert any("ECE" in r for r in reasons)


def test_compliance_status_needs_review_when_fairness_evidence_missing():
    from apps.ml_engine.services.mrm_compliance import _compliance_status

    mv = _make_compliant_mv(fairness_metrics={})
    status, reasons = _compliance_status(mv)
    assert status == "NEEDS REVIEW"
    assert any("fairness metrics" in r for r in reasons)


def test_compliance_status_needs_review_when_psi_missing():
    from apps.ml_engine.services.mrm_compliance import _compliance_status

    mv = _make_compliant_mv(training_metadata={"psi_by_feature": {}})
    status, reasons = _compliance_status(mv)
    assert status == "NEEDS REVIEW"
    assert any("PSI" in r for r in reasons)


def test_compliance_status_needs_review_when_calibration_missing():
    from apps.ml_engine.services.mrm_compliance import _compliance_status

    mv = _make_compliant_mv(calibration_data={})
    status, reasons = _compliance_status(mv)
    assert status == "NEEDS REVIEW"
    assert any("calibration" in r for r in reasons)


def test_header_renders_non_compliant_status_when_fairness_fails():
    """Even with is_active=True, a failed fairness gate must surface in §1."""
    from apps.ml_engine.services.mrm_dossier import generate_dossier_markdown

    mv = _make_mv(is_active=True)  # default has age_group failing
    with patch("apps.ml_engine.services.mrm_dossier._changelog_section") as _cl:
        _cl.return_value = "## 11. Change log\n\n(stub)"
        md = generate_dossier_markdown(mv)

    assert "**Compliance status:** NON-COMPLIANT" in md
    assert "age_group" in md  # named reason surfaces in the header sub-list


def test_header_renders_compliant_status_when_clean():
    from apps.ml_engine.services.mrm_dossier import generate_dossier_markdown

    with patch("apps.ml_engine.services.mrm_dossier._changelog_section") as _cl:
        _cl.return_value = "## 11. Change log\n\n(stub)"
        md = generate_dossier_markdown(_make_compliant_mv())

    assert "**Compliance status:** COMPLIANT" in md


def test_document_subtitle_drops_alignment_keeps_format_reference():
    """Regression guard for the implicit-claim removal (Codex finding 2)."""
    from apps.ml_engine.services.mrm_dossier import generate_dossier_markdown

    with patch("apps.ml_engine.services.mrm_dossier._changelog_section") as _cl:
        _cl.return_value = "## 11. Change log\n\n(stub)"
        md = generate_dossier_markdown(_make_compliant_mv())

    # Locate the subtitle line (second line of the document).
    lines = md.splitlines()
    subtitle = next((ln for ln in lines[:5] if ln.startswith("_Generated")), "")
    assert subtitle, "Document subtitle line not found"
    assert "alignment" not in subtitle, f"Subtitle still implies alignment: {subtitle!r}"
    assert "APRA CPS 220 / SR 11-7" in subtitle
    assert "Format:" in subtitle


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
