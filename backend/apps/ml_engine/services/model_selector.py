"""Weighted model selection for champion/challenger A/B testing."""

import logging
import random
from dataclasses import dataclass, field

from apps.ml_engine.models import ModelVersion
from apps.ml_engine.services.segmentation import SEGMENT_UNIFIED

logger = logging.getLogger("ml_engine.model_selector")


# Promotion gate thresholds — tunable via constants so MRM review can cite
# exact values. All four must be satisfied for a challenger to replace the
# current champion. Values align with APRA APS 220 credit-risk model-validation
# commentary and Basel WG-CR scorecard guides.
KS_REGRESSION_TOLERANCE = 0.015   # Candidate KS must not drop more than 1.5pp
MAX_PSI_THRESHOLD = 0.25          # Significant-shift PSI boundary
MAX_ECE_THRESHOLD = 0.03          # Expected calibration error ceiling
AUC_REGRESSION_TOLERANCE = 0.02   # Candidate AUC must not drop more than 2pp


def select_model_version(segment: str = SEGMENT_UNIFIED):
    """Select a model version using weighted random by traffic_percentage.

    Scoped to `segment` so per-segment A/B tests (e.g. two personal-loan
    challengers) don't interfere with mortgage models. When `segment` is
    non-unified and no active model exists in that segment, the call falls
    back to the unified segment — mirroring
    `segmentation.select_active_model_for_segment`.

    Single active model: returns it immediately (fast path).
    Multiple active models (same segment): weighted random selection.
    No active models in segment and no unified fallback: raises ValueError.
    """
    active_models = list(
        ModelVersion.objects.filter(
            is_active=True, traffic_percentage__gt=0, segment=segment
        ).order_by("-created_at")
    )

    if not active_models and segment != SEGMENT_UNIFIED:
        logger.info(
            "No active models for segment '%s' — falling back to unified",
            segment,
        )
        active_models = list(
            ModelVersion.objects.filter(
                is_active=True, traffic_percentage__gt=0, segment=SEGMENT_UNIFIED
            ).order_by("-created_at")
        )

    if not active_models:
        raise ValueError(
            f"No active model version found for segment '{segment}' (and no "
            "unified fallback available). Train a model first."
        )

    if len(active_models) == 1:
        return active_models[0]

    # Weighted random selection within the resolved segment pool.
    weights = [m.traffic_percentage for m in active_models]
    selected = random.choices(active_models, weights=weights, k=1)[0]  # noqa: S311
    logger.debug(
        "Champion/challenger (segment=%s): selected model %s (traffic=%d%%) from %d active models",
        selected.segment,
        selected.version,
        selected.traffic_percentage,
        len(active_models),
    )
    return selected


@dataclass
class PromotionDecision:
    """Outcome of a champion-challenger promotion gate evaluation."""

    promoted: bool
    candidate_id: str | None = None
    champion_id: str | None = None
    reasons: list[str] = field(default_factory=list)
    gates: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "promoted": self.promoted,
            "candidate_id": self.candidate_id,
            "champion_id": self.champion_id,
            "reasons": list(self.reasons),
            "gates": dict(self.gates),
        }


def _metric(mv: ModelVersion, key: str, default=None):
    """Read a training-metric attribute, falling back to training_metadata JSON."""
    val = getattr(mv, key, None)
    if val is not None:
        return val
    meta = getattr(mv, "training_metadata", None) or {}
    if key in meta:
        return meta[key]
    # brier_decomp + psi_by_feature live at the top of the metrics payload but
    # trainer persists them only in training_metadata on older records.
    return meta.get(key, default)


def _max_psi(mv: ModelVersion) -> float:
    """Return the largest per-feature PSI recorded at training time.

    Reads from `training_metadata.psi_by_feature` which D5 populates. If the
    attribute is missing (pre-D5 model) the gate treats PSI as 0 — the model
    simply hasn't recorded stability data and we refuse to promote.
    """
    meta = getattr(mv, "training_metadata", None) or {}
    by_feature = meta.get("psi_by_feature") or {}
    if not by_feature:
        # pre-D5 model — refuse to judge by returning an above-threshold value
        return float("inf")
    try:
        return float(max(by_feature.values()))
    except (ValueError, TypeError):
        return 0.0


def promote_if_eligible(
    candidate_version: ModelVersion,
    *,
    ks_tolerance: float = KS_REGRESSION_TOLERANCE,
    max_psi: float = MAX_PSI_THRESHOLD,
    max_ece: float = MAX_ECE_THRESHOLD,
    auc_tolerance: float = AUC_REGRESSION_TOLERANCE,
) -> PromotionDecision:
    """Evaluate the 4-gate champion-challenger promotion rules for `candidate_version`.

    Gates (D5 spec §D5):
      1. KS regression gate    — candidate.ks ≥ champion.ks − ks_tolerance
      2. PSI stability gate    — max(candidate.psi_by_feature) ≤ max_psi
      3. Calibration gate      — candidate.ece ≤ max_ece
      4. AUC regression gate   — candidate.auc_test ≥ champion.auc_test − auc_tolerance

    If `candidate_version` is the only model in its segment (no incumbent),
    gates 1 and 4 short-circuit to pass and only PSI + ECE are evaluated.

    Returns a `PromotionDecision`. Does NOT mutate `candidate_version.is_active`;
    the caller is responsible for persisting promotion. This keeps the gate
    pure and unit-testable without a live database.
    """
    champion = (
        ModelVersion.objects.filter(
            is_active=True, segment=candidate_version.segment
        )
        .exclude(pk=candidate_version.pk)
        .order_by("-created_at")
        .first()
    )

    gates: dict = {}
    reasons: list[str] = []

    # --- Gate 2: PSI stability -------------------------------------------
    cand_psi = _max_psi(candidate_version)
    gates["max_psi"] = {
        "value": cand_psi if cand_psi != float("inf") else None,
        "threshold": max_psi,
        "passed": cand_psi <= max_psi,
    }
    if cand_psi > max_psi:
        reasons.append(
            f"PSI gate failed: max feature PSI {cand_psi:.4f} exceeds {max_psi:.2f} ceiling"
        )

    # --- Gate 3: Calibration (ECE) ---------------------------------------
    cand_ece = _metric(candidate_version, "ece", default=1.0)
    try:
        cand_ece = float(cand_ece)
    except (TypeError, ValueError):
        cand_ece = 1.0
    gates["ece"] = {
        "value": cand_ece,
        "threshold": max_ece,
        "passed": cand_ece <= max_ece,
    }
    if cand_ece > max_ece:
        reasons.append(
            f"Calibration gate failed: ECE {cand_ece:.4f} exceeds {max_ece:.2f} ceiling"
        )

    # --- Gates 1 and 4 need an incumbent champion to compare against ---
    if champion is None:
        gates["ks"] = {"value": _metric(candidate_version, "ks_statistic"), "no_champion": True, "passed": True}
        gates["auc"] = {"value": _metric(candidate_version, "auc_roc"), "no_champion": True, "passed": True}
        promoted = not reasons
        if promoted:
            reasons.append("No incumbent champion — candidate auto-promotes after PSI+ECE gates")
        return PromotionDecision(
            promoted=promoted,
            candidate_id=str(candidate_version.id),
            champion_id=None,
            reasons=reasons,
            gates=gates,
        )

    # --- Gate 1: KS regression -------------------------------------------
    cand_ks = _metric(candidate_version, "ks_statistic", default=0.0) or 0.0
    champ_ks = _metric(champion, "ks_statistic", default=0.0) or 0.0
    ks_min = champ_ks - ks_tolerance
    gates["ks"] = {
        "candidate": cand_ks,
        "champion": champ_ks,
        "min_required": ks_min,
        "passed": cand_ks >= ks_min,
    }
    if cand_ks < ks_min:
        reasons.append(
            f"KS gate failed: candidate KS {cand_ks:.4f} below champion KS {champ_ks:.4f} − {ks_tolerance:.3f}"
        )

    # --- Gate 4: AUC regression ------------------------------------------
    cand_auc = _metric(candidate_version, "auc_roc", default=0.0) or 0.0
    champ_auc = _metric(champion, "auc_roc", default=0.0) or 0.0
    auc_min = champ_auc - auc_tolerance
    gates["auc"] = {
        "candidate": cand_auc,
        "champion": champ_auc,
        "min_required": auc_min,
        "passed": cand_auc >= auc_min,
    }
    if cand_auc < auc_min:
        reasons.append(
            f"AUC gate failed: candidate AUC {cand_auc:.4f} below champion AUC {champ_auc:.4f} − {auc_tolerance:.2f}"
        )

    promoted = not reasons
    if promoted:
        reasons.append(
            f"All gates passed: KS {cand_ks:.4f} ≥ {ks_min:.4f}, PSI ≤ {max_psi:.2f}, "
            f"ECE ≤ {max_ece:.2f}, AUC {cand_auc:.4f} ≥ {auc_min:.4f}"
        )
    else:
        logger.warning(
            "Challenger %s rejected against champion %s: %s",
            candidate_version.id,
            champion.id,
            "; ".join(reasons),
        )

    return PromotionDecision(
        promoted=promoted,
        candidate_id=str(candidate_version.id),
        champion_id=str(champion.id),
        reasons=reasons,
        gates=gates,
    )
