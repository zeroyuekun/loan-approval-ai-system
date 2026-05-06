"""Compliance-status derivation for the MRM dossier.

Pure-functional. Given a ModelVersion-like object with already-recorded gate
evidence (fairness metrics, PSI by feature, ECE, decile calibration), returns
a `(status, reasons)` tuple that `mrm_dossier._header_section` renders as the
§1 Header banner.

Lives in its own module so `mrm_dossier.py` stays under the ml_engine quality
bar's 500-LOC global cap. The split is mechanical — no behavioural change.

See `docs/superpowers/specs/2026-04-18-arm-c-ml-engine-quality-bar-design.md`
for the file-size discipline this module respects.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Compliance thresholds — surface in the header banner when breached so an
# auditor reading the first page sees gate failures, not a silent "Active:
# True" line. Values match _psi_section's "significant drift" boundary and
# the standard ECE acceptance ceiling for AU retail-credit scorecards.
# ---------------------------------------------------------------------------

PSI_FAIL_THRESHOLD = 0.25
ECE_FAIL_THRESHOLD = 0.05


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
