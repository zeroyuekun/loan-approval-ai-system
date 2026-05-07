"""Mode dispatcher for the pre-activation validation sign-off gate (SR 11-7).

Codex adversarial review (v1.10.7) flagged that the existing fairness gate
(PR #163) and champion-challenger promotion gate (PRs #164–#165) check
*performance metrics* but never enforce the governance artefact:
``ModelValidationReport`` is created by the ``validate_model`` management
command but neither the training task nor manual activation consults it.

This dispatcher closes that gap. It mirrors the warn|block|off pattern of
``fairness_gate_mode`` and ``promotion_gate_mode`` so operators learn one
mode pattern that applies across all three gates.

Behaviour by mode:

  - ``warn`` (default): gate runs, decision is returned, activation proceeds
    even if no approved sign-off exists. Useful for the initial roll-out
    phase where validation reports haven't been seeded yet — operators get
    visibility without breaking the existing demo flow.
  - ``block``: the dispatcher raises ``ValidationSignoffBlocked`` when no
    approved/signed-off report exists for the candidate. Callers (tasks.py
    and ``ModelActivateView``) interpret this depending on their context —
    tasks.py demotes the freshly-created candidate to ``is_active=False``
    rather than raising past the activation transaction; the view returns
    HTTP 409 unless the request carries an audited ``force=true`` flag.
  - ``off``: the gate is skipped entirely. Use only when validation reports
    are out of band (e.g. a private offline workflow).

The dispatcher is pure-functional. Settings access (``ML_VALIDATION_SIGNOFF_GATE_MODE``)
lives in the callers so the dispatcher is unit-testable without Django ORM boot.

See ``docs/superpowers/specs/2026-05-07-codex-adversarial-response-v1-10-7-design.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from apps.ml_engine.models import ModelValidationReport, ModelVersion

logger = logging.getLogger(__name__)


VALID_MODES = ("warn", "block", "off")
DEFAULT_MODE = "warn"


class ValidationSignoffBlocked(RuntimeError):
    """Raised by the dispatcher in ``block`` mode when no approved
    ModelValidationReport exists for the candidate. Carries a structured
    payload so callers can return it to API clients.
    """

    def __init__(self, message: str, payload: dict):
        super().__init__(message)
        self.payload = payload


@dataclass
class ValidationDecision:
    """Pure-data result of the gate check. Independent of caller context."""

    result: str  # "passed" | "blocked" | "skipped"
    reason: str  # "approved" | "no_report" | "report_not_approved" | "gate_off" | "bypass"
    candidate_id: Optional[str]
    report_id: Optional[str]
    report_outcome: Optional[str]
    signed_off: Optional[bool]

    def to_dict(self) -> dict:
        return {
            "result": self.result,
            "reason": self.reason,
            "candidate_id": self.candidate_id,
            "report_id": self.report_id,
            "report_outcome": self.report_outcome,
            "signed_off": self.signed_off,
        }


def normalize_mode(mode: str | None) -> str:
    """Coerce arbitrary input to a valid mode; unknown values collapse to warn.

    Mirrors the pattern in ``promotion_gate_mode.normalize_mode`` — a
    misconfigured deployment never silently disables the gate.
    """
    if mode in VALID_MODES:
        return mode
    if mode is not None:
        logger.warning(
            "Unknown ML_VALIDATION_SIGNOFF_GATE_MODE=%r — defaulting to %r",
            mode,
            DEFAULT_MODE,
        )
    return DEFAULT_MODE


def _check_signoff(candidate: ModelVersion) -> ValidationDecision:
    """Return the raw gate decision for a candidate ModelVersion.

    The candidate must have a saved primary key. Training-path callers that
    haven't yet persisted the candidate should use ``check_pre_activation``
    instead, which handles the no-PK case explicitly.
    """
    candidate_id = str(candidate.pk) if getattr(candidate, "pk", None) else None
    report = (
        ModelValidationReport.objects
        .filter(model_version_id=candidate.pk)
        .order_by("-validation_date", "-id")
        .first()
    )
    if report is None:
        return ValidationDecision(
            result="blocked",
            reason="no_report",
            candidate_id=candidate_id,
            report_id=None,
            report_outcome=None,
            signed_off=None,
        )
    if not report.signed_off or report.outcome != ModelValidationReport.Outcome.APPROVED:
        return ValidationDecision(
            result="blocked",
            reason="report_not_approved",
            candidate_id=candidate_id,
            report_id=str(report.id),
            report_outcome=report.outcome,
            signed_off=report.signed_off,
        )
    return ValidationDecision(
        result="passed",
        reason="approved",
        candidate_id=candidate_id,
        report_id=str(report.id),
        report_outcome=report.outcome,
        signed_off=True,
    )


def evaluate_validation_signoff_gate(
    candidate: ModelVersion,
    mode: str,
    *,
    bypass: bool = False,
) -> dict:
    """Decide whether activation should proceed given the candidate + mode.

    Args:
        candidate: The ``ModelVersion`` about to be promoted. Must already
            have a saved primary key (training-path callers persist the row
            before invoking this dispatcher).
        mode: One of "warn" | "block" | "off". Unknown values are coerced
            to "warn" via :func:`normalize_mode`.
        bypass: Audited break-glass override (e.g. ``?force=true`` on the
            manual activation endpoint). When true the gate is treated as
            ``off`` for this single call and the bypass is recorded in the
            decision payload.

    Returns:
        {
            "action": "activate" | "skip_check",
            "decision": ValidationDecision | None,
            "mode": str,
        }

    Raises:
        ValidationSignoffBlocked: in ``block`` mode when no approved
            sign-off exists. Callers must ensure this raise happens
            *before* the activation transaction so prior-active models
            keep serving.
    """
    mode = normalize_mode(mode)

    if mode == "off" or bypass:
        decision = ValidationDecision(
            result="skipped",
            reason="bypass" if bypass else "gate_off",
            candidate_id=str(candidate.pk) if getattr(candidate, "pk", None) else None,
            report_id=None,
            report_outcome=None,
            signed_off=None,
        )
        return {
            "action": "skip_check",
            "decision": decision,
            "mode": mode,
            "bypass": bypass,
        }

    decision = _check_signoff(candidate)

    if mode == "block" and decision.result == "blocked":
        raise ValidationSignoffBlocked(
            f"Activation blocked (mode=block): {decision.reason}. "
            "Create or sign off a ModelValidationReport for this candidate, "
            "or set ML_VALIDATION_SIGNOFF_GATE_MODE=warn after manual review.",
            payload=decision.to_dict(),
        )

    return {"action": "activate", "decision": decision, "mode": mode, "bypass": False}
