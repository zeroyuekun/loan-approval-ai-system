"""The one place that changes which model version serves a segment.

Used by the training task, the ``train_model`` command, the activate view
and the traffic view. Every activation:

1. Checks the artefact: path inside ML_MODELS_DIR, ``.joblib``, file present,
   SHA-256 matches. Not bypassable — a missing or tampered artefact would
   break (or subvert) every prediction in the segment.
2. Runs the governance gates (fairness, champion-challenger promotion,
   validation sign-off) in their configured modes. In ``block`` mode a
   failing gate refuses the activation. ``force=True`` is the audited
   break-glass that bypasses the governance gates (never the artefact check).
3. Locks the segment's rows (``select_for_update``) and switches models in
   one transaction, so two concurrent activations cannot leave two champions
   and the incumbent is only retired once the candidate is cleared to serve.
   Retired rows get ``traffic_percentage=0``. Other segments are untouched.
4. Writes an AuditLog row (who, from where, which gates, what it replaced),
   or a ``model_activation_blocked`` row when a gate refused.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction

from apps.loans.models import AuditLog
from apps.ml_engine.models import ModelVersion
from apps.ml_engine.services.governance.fairness_gate import check_fairness_gate
from apps.ml_engine.services.governance.fairness_gate_mode import (
    FairnessGateBlocked,
    evaluate_fairness_gate_for_activation,
)
from apps.ml_engine.services.governance.promotion_gate_mode import (
    PromotionGateBlocked,
    evaluate_promotion_gates_for_activation,
)
from apps.ml_engine.services.governance.promotion_gate_mode import normalize_mode as _promotion_mode
from apps.ml_engine.services.model_selector import promote_if_eligible
from apps.ml_engine.services.scoring.prediction_cache import (
    _validate_model_path,
    _verify_model_hash,
    clear_model_cache,
)
from apps.ml_engine.services.validation_gate_mode import (
    ValidationSignoffBlocked,
    evaluate_validation_signoff_gate,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ActivationBlocked",
    "ActivationRefused",
    "ArtefactUnusable",
    "activate_model_version",
    "set_traffic",
]


class ActivationRefused(RuntimeError):
    """Base class: the requested model change was not made."""


class ArtefactUnusable(ActivationRefused):
    """The model file is missing, outside ML_MODELS_DIR, or fails its hash check."""


class ActivationBlocked(ActivationRefused):
    """One or more governance gates in ``block`` mode refused the activation."""

    def __init__(self, message: str, *, blocked_gates: list[str], gates: dict):
        super().__init__(message)
        self.blocked_gates = blocked_gates
        self.gates = gates


class SegmentWouldBeEmpty(ActivationRefused):
    """The change would leave the segment with no model taking traffic."""


def _check_artefact(mv: ModelVersion) -> None:
    try:
        resolved = _validate_model_path(mv.file_path)
        _verify_model_hash(resolved, mv.file_hash, version_id=mv.id)
    except (ValueError, OSError) as exc:
        raise ArtefactUnusable(f"Model {mv.id} artefact is not usable: {exc}") from exc


def _evaluate_gates(mv: ModelVersion, *, force: bool) -> tuple[dict, list[str]]:
    """Run the three governance gates; return (records, blocked gate names).

    Each record keeps the shape the MRM dossier and dashboards already read
    from training_metadata (``fairness_gate``, ``promotion_gate``,
    ``validation_gate`` plus the ``*_mode`` the gate ran in).
    """
    gates: dict = {}
    blocked: list[str] = []

    fairness_mode = getattr(settings, "ML_FAIRNESS_GATE_MODE", "warn")
    promotion_mode = getattr(settings, "ML_PROMOTION_GATE_MODE", "warn")
    validation_mode = getattr(settings, "ML_VALIDATION_SIGNOFF_GATE_MODE", "warn")
    if force:
        fairness_mode = promotion_mode = "off"

    fairness_data = mv.fairness_metrics or {}
    try:
        decision = evaluate_fairness_gate_for_activation(fairness_data, fairness_mode)
        gates["fairness"] = {"mode": decision["mode"], "result": decision["gate_result"]}
    except FairnessGateBlocked as exc:
        blocked.append("fairness")
        gates["fairness"] = {
            "mode": "block",
            "result": check_fairness_gate(fairness_data) if fairness_data else None,
            "blocked": str(exc),
        }

    try:
        decision = evaluate_promotion_gates_for_activation(promote_if_eligible(mv), promotion_mode)
        payload = decision["decision"]
        gates["promotion"] = {"mode": decision["mode"], "result": payload.to_dict() if payload else None}
    except PromotionGateBlocked as exc:
        blocked.append("promotion")
        gates["promotion"] = {
            "mode": _promotion_mode(promotion_mode),
            "result": promote_if_eligible(mv).to_dict(),
            "blocked": str(exc),
        }

    try:
        decision = evaluate_validation_signoff_gate(mv, validation_mode, bypass=force)
        gates["validation"] = {"mode": decision["mode"], "result": decision["decision"].to_dict()}
    except ValidationSignoffBlocked as exc:
        blocked.append("validation")
        gates["validation"] = {"mode": "block", "result": exc.payload, "blocked": str(exc)}

    return gates, blocked


def _audit(action, mv, actor, ip_address, details):
    AuditLog.objects.create(
        user=actor,
        action=action,
        resource_type="ModelVersion",
        resource_id=str(mv.id),
        details={"version": mv.version, "segment": mv.segment, **details},
        ip_address=ip_address,
    )


def _lock_segment(segment: str) -> list[ModelVersion]:
    """Lock every row of the segment for the rest of the transaction."""
    return list(ModelVersion.objects.select_for_update().filter(segment=segment).order_by("pk"))


def activate_model_version(
    mv: ModelVersion,
    *,
    actor=None,
    source: str,
    force: bool = False,
    traffic_percentage: int = 100,
    ip_address: str | None = None,
) -> dict:
    """Put ``mv`` into service in its segment; return the gate records.

    ``traffic_percentage == 100`` makes ``mv`` the segment champion and
    retires every other active model in the segment. A smaller share adds
    it as a challenger next to the models already serving (the segment's
    traffic cap in ``ModelVersion.clean`` still applies).

    Raises ``ArtefactUnusable`` or ``ActivationBlocked``; in both cases no
    row has changed.
    """
    _check_artefact(mv)

    with transaction.atomic():
        rows = _lock_segment(mv.segment)
        mv.refresh_from_db()
        gates, blocked = _evaluate_gates(mv, force=force)
        previous_active = [r for r in rows if r.is_active and r.pk != mv.pk]

        if blocked:
            message = f"Activation of model {mv.id} blocked by: {', '.join(blocked)}"
            logger.warning(message)
            _audit(
                "model_activation_blocked",
                mv,
                actor,
                ip_address,
                {"source": source, "blocked_gates": blocked, "gates": gates},
            )
            # The audit row must survive the refusal, so it is written and
            # committed here rather than rolled back with an exception.
            blocked_exc = ActivationBlocked(message, blocked_gates=blocked, gates=gates)
        else:
            blocked_exc = None
            if traffic_percentage >= 100:
                ModelVersion.objects.filter(pk__in=[r.pk for r in previous_active]).update(
                    is_active=False, traffic_percentage=0
                )
            mv.is_active = True
            mv.traffic_percentage = traffic_percentage
            mv.save(update_fields=["is_active", "traffic_percentage"])
            validation = gates["validation"]
            _audit(
                "model_activate_force" if force else "model_activate",
                mv,
                actor,
                ip_address,
                {
                    "source": source,
                    "traffic_percentage": traffic_percentage,
                    "previous_active_ids": [str(r.pk) for r in previous_active] if traffic_percentage >= 100 else [],
                    "gates": gates,
                    "validation_gate_mode": validation["mode"],
                    "validation_gate_decision": validation["result"],
                    "force_bypass": force,
                },
            )
            transaction.on_commit(clear_model_cache)

    if blocked_exc is not None:
        raise blocked_exc
    return gates


def set_traffic(mv: ModelVersion, traffic_percentage: int, *, actor=None, ip_address: str | None = None) -> None:
    """Change ``mv``'s traffic share.

    - 0 retires it (``is_active=False``), unless that would leave the segment
      with no model taking traffic.
    - A share for an inactive model is an activation: it goes through
      ``activate_model_version`` (artefact check, gates, audit).
    - A share for a model already serving is a re-weighting under the
      segment lock (the segment cap in ``ModelVersion.clean`` applies).
    """
    if not mv.is_active and traffic_percentage > 0:
        activate_model_version(
            mv, actor=actor, source="traffic", traffic_percentage=traffic_percentage, ip_address=ip_address
        )
        return

    with transaction.atomic():
        rows = _lock_segment(mv.segment)
        mv.refresh_from_db()
        before = mv.traffic_percentage
        if traffic_percentage == 0:
            others_serving = [r for r in rows if r.pk != mv.pk and r.is_active and r.traffic_percentage > 0]
            if mv.is_active and not others_serving:
                raise SegmentWouldBeEmpty(
                    f"Model {mv.id} is the only model serving segment '{mv.segment}'; "
                    "activate a replacement before retiring it."
                )
            mv.is_active = False
        mv.traffic_percentage = traffic_percentage
        mv.save(update_fields=["is_active", "traffic_percentage"])
        _audit(
            "model_traffic_change",
            mv,
            actor,
            ip_address,
            {"from": before, "to": traffic_percentage, "is_active": mv.is_active},
        )
        transaction.on_commit(clear_model_cache)
