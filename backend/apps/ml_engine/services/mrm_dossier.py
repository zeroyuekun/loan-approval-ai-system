"""Model Risk Management (MRM) dossier generator — D7.

Produces a plain-markdown dossier for a trained `ModelVersion`, covering the
11 sections required by APRA CPS 220 / SR 11-7 model-risk review:

  1. Header                          7. PSI by feature (stability)
  2. Purpose & limitations           8. Fairness audit
  3. Data lineage                    9. Policy overlay reference
  4. Monotonicity constraint table  10. Ongoing monitoring plan
  5. Performance                    11. Change log vs previous version
  6. Calibration report

The generator is deliberately pure-functional: it takes a `ModelVersion`
and returns a markdown string. The management command + Celery task wrap
this to write the dossier to disk. Keeping the core side-effect-free
makes it trivial to unit-test without Django ORM / filesystem setup.

Missing data degrades gracefully: if `training_metadata.psi_by_feature`
is absent (pre-D5 models), the PSI section renders "No PSI data — train
with v1.9.9+". Any section that can't be computed prints an explicit
"Unavailable" line rather than silently omitting, so the auditor sees
the gap.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# Compliance thresholds — surface in the header banner when breached so an
# auditor reading the first page sees gate failures, not a silent "Active:
# True" line. Values match _psi_section's "significant drift" boundary and
# the standard ECE acceptance ceiling for AU retail-credit scorecards.
# ---------------------------------------------------------------------------

PSI_FAIL_THRESHOLD = 0.25
ECE_FAIL_THRESHOLD = 0.05


# ---------------------------------------------------------------------------
# Purpose statements per segment. Kept adjacent so a change to the training
# scope is one place, not scattered across templates.
# ---------------------------------------------------------------------------

_SEGMENT_PURPOSE = {
    "unified": (
        "General-purpose PD estimation across AU retail loan products. "
        "Not validated for: business lending, secured non-home lending, "
        "applicants outside AU residency, loans > $5M, loans with unusual "
        "repayment structures (balloon, interest-only > 5yr)."
    ),
    "home_owner_occupier": (
        "PD estimation for AU owner-occupier home loans. Valid for "
        "standard P&I and short (≤5yr) interest-only terms up to $5M. "
        "Not validated for: investor home loans, construction loans, "
        "bridging loans, SMSF borrowers, non-resident applicants."
    ),
    "home_investor": (
        "PD estimation for AU residential investment home loans. "
        "Investment-income weighting, negative-gearing adjustments "
        "applied. Not validated for: commercial property, developer "
        "exposures, cross-collateralised portfolios > 3 securities."
    ),
    "personal": (
        "PD estimation for AU unsecured personal loans up to $55k, "
        "1–7yr term. Not validated for: secured personal lending, "
        "business personal loans, loans to undischarged bankrupts."
    ),
}


def _compliance_status(mv) -> tuple[str, list[str]]:
    """Derive the dossier compliance banner from gate evidence already
    recorded on the ModelVersion. Returns (status, reasons).

    Status decision (first match wins):
      1. Any fairness gate `passes_80_percent_rule == False` → NON-COMPLIANT
      2. Any feature PSI ≥ PSI_FAIL_THRESHOLD                → NON-COMPLIANT
      3. ECE > ECE_FAIL_THRESHOLD                            → NON-COMPLIANT
      4. Fairness / PSI / calibration evidence missing       → NEEDS REVIEW
      5. Otherwise                                           → COMPLIANT

    The reasons list is empty for COMPLIANT; for the other two it carries one
    bullet per failure or missing-evidence reason so §1 Header can render the
    sub-list. Pure function — no DB, no Django boot required.
    """
    reasons: list[str] = []

    fairness = mv.fairness_metrics or {}
    psi_map = (mv.training_metadata or {}).get("psi_by_feature") or {}
    calibration = mv.calibration_data or {}
    deciles = calibration.get("deciles") or calibration.get("decile_analysis") or []

    failed_attrs: list[str] = []
    for attr, data in fairness.items():
        if isinstance(data, dict) and data.get("passes_80_percent_rule") is False:
            failed_attrs.append(attr)
    if failed_attrs:
        reasons.append(f"Fairness 80%-rule fails on: {', '.join(sorted(failed_attrs))}")

    breached_psi: list[tuple[str, float]] = []
    for feat, value in psi_map.items():
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if v >= PSI_FAIL_THRESHOLD:
            breached_psi.append((feat, v))
    if breached_psi:
        breached_psi.sort(key=lambda kv: -kv[1])
        details = ", ".join(f"{f} (PSI={v:.2f})" for f, v in breached_psi)
        reasons.append(f"PSI ≥ {PSI_FAIL_THRESHOLD} on: {details}")

    ece = mv.ece
    if isinstance(ece, (int, float)) and ece > ECE_FAIL_THRESHOLD:
        reasons.append(f"ECE {ece:.4f} exceeds ceiling of {ECE_FAIL_THRESHOLD}")

    if reasons:
        return ("NON-COMPLIANT", reasons)

    missing: list[str] = []
    if not fairness:
        missing.append("fairness metrics")
    if not psi_map:
        missing.append("PSI by feature")
    if not deciles:
        missing.append("decile calibration")
    if missing:
        return (
            "NEEDS REVIEW",
            [f"Missing evidence: {', '.join(missing)}"],
        )

    return ("COMPLIANT", [])


def _header_section(mv) -> str:
    """§1 — Header."""
    trained_at = getattr(mv, "created_at", None)
    algorithm_display = mv.get_algorithm_display() if hasattr(mv, "get_algorithm_display") else mv.algorithm
    training_meta = mv.training_metadata or {}
    status, reasons = _compliance_status(mv)
    lines = [
        "## 1. Header",
        "",
        f"- **Model ID:** `{mv.id}`",
        f"- **Algorithm:** {algorithm_display}",
        f"- **Version:** {mv.version}",
        f"- **Segment:** `{mv.segment}`",
        f"- **Trained at:** {trained_at.isoformat() if trained_at else 'unknown'}",
        f"- **Training duration:** {training_meta.get('training_seconds', 'unknown')}s",
        f"- **Training samples:** {training_meta.get('n_training_samples', 'unknown')}",
        f"- **Class balance (positive rate):** {training_meta.get('positive_rate', 'unknown')}",
        f"- **Active:** {mv.is_active}",
        f"- **Compliance status:** {status}",
    ]
    for reason in reasons:
        lines.append(f"  - {reason}")
    lines.append(f"- **File hash (SHA-256):** `{mv.file_hash or 'not recorded'}`")
    return "\n".join(lines)


def _purpose_section(mv) -> str:
    """§2 — Purpose & limitations."""
    purpose = _SEGMENT_PURPOSE.get(mv.segment, "Segment-specific purpose statement not yet registered.")
    return "\n".join(
        [
            "## 2. Purpose & limitations",
            "",
            purpose,
            "",
            "All scope boundaries above reflect the training distribution. "
            "Predictions on applications outside scope must be treated as advisory "
            "only and referred to human underwriter review (see §9 policy overlay).",
        ]
    )


def _data_lineage_section(mv) -> str:
    """§3 — Data lineage."""
    meta = mv.training_metadata or {}
    source = meta.get("data_source", "synthetic (DataGenerator v1 + GMSC real-data benchmark)")
    synthetic = meta.get("synthetic", True)
    class_balance = meta.get("positive_rate", "unknown")
    reject_inference = meta.get("reject_inference", "not applied")
    temporal_start = meta.get("temporal_start", "unknown")
    temporal_end = meta.get("temporal_end", "unknown")
    return "\n".join(
        [
            "## 3. Data lineage",
            "",
            f"- **Source:** {source}",
            f"- **Synthetic vs real:** {'synthetic' if synthetic else 'real'}",
            f"- **Class balance (positive rate):** {class_balance}",
            f"- **Reject-inference usage:** {reject_inference}",
            f"- **Temporal coverage:** {temporal_start} → {temporal_end}",
            "",
            "Reject-inference is not applied for this version; the accept-only "
            "training distribution is a known bias risk and is mitigated through "
            "ongoing PSI monitoring (§10) + quarterly challenger retraining.",
        ]
    )


def _monotone_section(mv) -> str:
    """§4 — Monotonicity constraint table."""
    try:
        from apps.ml_engine.services.monotone_constraints import (
            MONOTONE_CONSTRAINTS,
            RATIONALE,
        )
    except Exception:
        return "## 4. Monotonicity constraint table\n\nUnavailable — could not import monotone_constraints."

    rows = ["| Feature | Sign | Rationale |", "|---|---|---|"]
    positives, negatives = [], []
    for feat, sign in sorted(MONOTONE_CONSTRAINTS.items()):
        rationale = RATIONALE.get(feat, "—")
        sign_str = "+1 (↑)" if sign == 1 else "−1 (↓)" if sign == -1 else "0"
        row = f"| `{feat}` | {sign_str} | {rationale} |"
        (positives if sign == 1 else negatives).append(row)
    rows.extend(positives)
    rows.extend(negatives)
    return "## 4. Monotonicity constraint table\n\n" + "\n".join(rows)


def _performance_section(mv) -> str:
    """§5 — Performance metrics."""
    auc = mv.auc_roc
    ks = mv.ks_statistic
    brier = mv.brier_score
    ece = mv.ece
    meta = mv.training_metadata or {}
    temporal_cv = meta.get("temporal_cv", {})
    baseline_gap = meta.get("baseline_lr_gap", "not measured")

    def _fmt(x):
        return f"{x:.4f}" if isinstance(x, (int, float)) else "unavailable"

    return "\n".join(
        [
            "## 5. Performance",
            "",
            "Evaluated on hold-out test set (20% of training data):",
            "",
            f"- **AUC-ROC:** {_fmt(auc)}",
            f"- **KS statistic:** {_fmt(ks)}",
            f"- **Brier score (pointwise):** {_fmt(brier)}",
            f"- **ECE (15-bin):** {_fmt(ece)}",
            "",
            f"**Temporal cross-validation:** {temporal_cv or 'not recorded'}",
            "",
            f"**Baseline logistic-regression gap:** {baseline_gap}",
            "",
            "KS > 0.30 and AUC > 0.75 are the regulator-expected performance floor "
            "for AU retail-credit scorecards. Champion-challenger promotion gates "
            "(see model_selector.py) enforce these + PSI and calibration ceilings.",
        ]
    )


def _calibration_section(mv) -> str:
    """§6 — Calibration report (decile table)."""
    calibration = mv.calibration_data or {}
    deciles = calibration.get("deciles") or calibration.get("decile_analysis") or []
    if not deciles:
        return (
            "## 6. Calibration report\n\n"
            "Decile calibration not recorded. Re-train with v1.9.0+ trainer which "
            "emits `calibration_data.deciles` on every run."
        )

    rows = ["| Decile | Expected PD | Observed default rate | n |", "|---|---|---|---|"]
    for i, row in enumerate(deciles, start=1):
        if isinstance(row, dict):
            exp = row.get("expected") or row.get("predicted_rate") or row.get("mean_pred")
            obs = row.get("observed") or row.get("observed_rate") or row.get("default_rate")
            n = row.get("n") or row.get("count") or "—"
        else:
            exp = obs = n = "—"
        exp_s = f"{exp:.4f}" if isinstance(exp, (int, float)) else str(exp)
        obs_s = f"{obs:.4f}" if isinstance(obs, (int, float)) else str(obs)
        rows.append(f"| {i} | {exp_s} | {obs_s} | {n} |")
    return "## 6. Calibration report\n\n" + "\n".join(rows)


def _psi_section(mv) -> str:
    """§7 — PSI by feature."""
    meta = mv.training_metadata or {}
    psi_map = meta.get("psi_by_feature") or {}
    if not psi_map:
        return (
            "## 7. PSI by feature\n\n"
            "No PSI data recorded. Train with v1.9.9+ trainer — it emits "
            "`training_metadata.psi_by_feature` (train vs test) on every run."
        )

    rows = ["| Feature | PSI (train vs test) | Status |", "|---|---|---|"]
    # Sort descending by PSI so highest-drift rows surface first.
    for feat, value in sorted(psi_map.items(), key=lambda kv: -(kv[1] or 0)):
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = 0.0
        if v < 0.10:
            status = "stable"
        elif v < 0.25:
            status = "⚠ moderate drift"
        else:
            status = "✗ significant drift — investigate"
        rows.append(f"| `{feat}` | {v:.4f} | {status} |")
    return "## 7. PSI by feature\n\n" + "\n".join(rows)


def _fairness_section(mv) -> str:
    """§8 — Fairness audit."""
    fairness = mv.fairness_metrics or {}
    if not fairness:
        return (
            "## 8. Fairness audit\n\n"
            "No fairness metrics recorded. Check that the fairness evaluator ran "
            "during training (see `fairness_gate.py` and `intersectional_fairness.py`)."
        )

    rows = ["| Protected attribute | DI ratio | 80%-rule passes |", "|---|---|---|"]
    for attr, data in fairness.items():
        if not isinstance(data, dict):
            continue
        di = data.get("disparate_impact_ratio")
        passes = data.get("passes_80_percent_rule")
        di_s = f"{di:.4f}" if isinstance(di, (int, float)) else "—"
        rows.append(f"| `{attr}` | {di_s} | {passes} |")
    return (
        "## 8. Fairness audit\n\n" + "\n".join(rows) + "\n\nCross-reference `intersectional_fairness.py` output in "
        "`training_metadata.intersectional_fairness` for two-way slices."
    )


def _policy_section(mv) -> str:
    """§9 — Policy overlay reference (active P-codes at training time)."""
    try:
        from apps.ml_engine.services.credit_policy import POLICY_RULES
    except Exception:
        return "## 9. Policy overlay reference\n\nUnavailable — could not import credit_policy."

    rows = ["| Code | Severity | Description |", "|---|---|---|"]
    for rule in POLICY_RULES:
        code = getattr(rule, "code", "?")
        severity = getattr(rule, "severity", "?")
        desc = getattr(rule, "description", "")
        rows.append(f"| {code} | {severity} | {desc} |")
    return (
        "## 9. Policy overlay reference\n\n"
        + "\n".join(rows)
        + "\n\nCurrent overlay mode is read from `CREDIT_POLICY_OVERLAY_MODE` "
        "(off / shadow / enforce); default is `shadow`."
    )


def _monitoring_section(mv) -> str:
    """§10 — Ongoing monitoring plan."""
    policy = mv.retraining_policy or {}
    cadence = policy.get("cadence_days", 90)
    min_samples = policy.get("min_samples", 10000)
    max_psi = policy.get("max_psi_before_retrain", 0.25)
    return "\n".join(
        [
            "## 10. Ongoing monitoring plan",
            "",
            f"- **Retraining cadence:** every {cadence} days minimum.",
            f"- **Minimum fresh samples before retrain:** {min_samples}",
            f"- **PSI alert threshold:** {max_psi} (per-feature); cumulative PSI > 0.5 triggers retrain.",
            "- **ECE re-validation cadence:** quarterly.",
            "- **KS regression trigger:** drop > 5pp vs champion baseline triggers retrain.",
            "- **Fairness audit cadence:** every training run pre-promotion (see fairness_gate.py).",
            "- **Drift dashboard:** `/api/ml-engine/drift/` (weekly DriftReport cron).",
        ]
    )


def _changelog_section(mv) -> str:
    """§11 — Diff vs previous ModelVersion on same segment."""
    # Avoid importing at module top so mrm_dossier remains testable without
    # the Django app registry loaded.
    try:
        from apps.ml_engine.models import ModelVersion
    except Exception:
        return "## 11. Change log\n\nUnavailable — ORM not ready."

    try:
        previous = ModelVersion.objects.filter(segment=mv.segment).exclude(pk=mv.pk).order_by("-created_at").first()
    except Exception:
        previous = None

    if previous is None:
        return f"## 11. Change log\n\nNo prior version on segment `{mv.segment}` — this is the first dossier."

    def _delta(name, cur, prev):
        if cur is None or prev is None:
            return f"- **{name}:** current={cur} prev={prev}"
        try:
            d = float(cur) - float(prev)
            arrow = "↑" if d > 0 else "↓" if d < 0 else "→"
            return f"- **{name}:** {cur:.4f} vs {prev:.4f} ({arrow}{abs(d):.4f})"
        except (TypeError, ValueError):
            return f"- **{name}:** current={cur} prev={prev}"

    lines = [
        "## 11. Change log",
        "",
        f"Comparison vs previous ModelVersion on segment `{mv.segment}`: `{previous.id}` (v{previous.version}).",
        "",
        _delta("AUC-ROC", mv.auc_roc, previous.auc_roc),
        _delta("KS", mv.ks_statistic, previous.ks_statistic),
        _delta("Brier", mv.brier_score, previous.brier_score),
        _delta("ECE", mv.ece, previous.ece),
    ]
    return "\n".join(lines)


def generate_dossier_markdown(mv) -> str:
    """Build the full MRM dossier markdown for a ModelVersion.

    Pure-functional — no side effects. Sections degrade gracefully when
    underlying data is missing so the dossier always renders all 11
    section headers (audit-visible evidence of gaps, rather than silent
    omission).
    """
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    sections: Iterable[str] = [
        f"# Model Risk Management Dossier — `{mv.id}`",
        f"_Generated {generated_at} — Format: APRA CPS 220 / SR 11-7_",
        "",
        _header_section(mv),
        "",
        _purpose_section(mv),
        "",
        _data_lineage_section(mv),
        "",
        _monotone_section(mv),
        "",
        _performance_section(mv),
        "",
        _calibration_section(mv),
        "",
        _psi_section(mv),
        "",
        _fairness_section(mv),
        "",
        _policy_section(mv),
        "",
        _monitoring_section(mv),
        "",
        _changelog_section(mv),
        "",
    ]
    return "\n".join(sections)


def write_dossier(mv, output_dir) -> str:
    """Write dossier to `<output_dir>/<model_id>/mrm.md`; return the path."""
    from pathlib import Path

    markdown = generate_dossier_markdown(mv)
    out_root = Path(output_dir) / str(mv.id)
    out_root.mkdir(parents=True, exist_ok=True)
    target = out_root / "mrm.md"
    target.write_text(markdown, encoding="utf-8")
    return str(target)
