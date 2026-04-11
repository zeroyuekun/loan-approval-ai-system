"""Train-Synthetic-Test-Real (TSTR) validation framework.

Estimates real-world model performance by grounding synthetic training
metrics in live APRA Australian lending benchmarks via MacroDataService.

When the APRA comparison is available, this module reports a live,
data-driven fidelity score that replaces the pure-literature 5% AUC
degradation constant. It uses the ``actual_outcome`` column in the
synthetic test set to measure:

    1. Data fidelity — synthetic default rate vs APRA NPL rate
    2. Predictive fidelity — model AUC against actual default labels
       (as opposed to underwriting approval labels)
    3. APRA fidelity penalty — additional AUC degradation proportional
       to how far the synthetic default rate diverges from APRA actual

No foreign datasets are downloaded. All grounding data comes from
APRA Quarterly ADI Property Exposures via MacroDataService.

References:
    APRA Quarterly ADI Property Exposures (live via MacroDataService)
    Xu et al. (2019), "Modeling Tabular Data using Conditional GAN"
        — CTGAN achieves ~3% AUC degradation on tabular benchmarks.
    Jordon et al. (2022), "Synthetic Data — What, Why and How?"
        — General synthetic data degrades 5-15% vs real across domains.
    Assefa et al. (2020), "Generating Synthetic Data in Finance"
        — Credit risk synthetic validation, calibration methodology.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


class TSTRValidator:
    """Estimate real-world model performance from synthetic training metrics."""

    # Literature-based degradation constants
    BASE_DEGRADATION = 0.05  # Midpoint of CTGAN 3-8% range
    MIN_DEGRADATION = 0.01  # Floor: synthetic never matches real exactly
    CTGAN_RANGE = (0.03, 0.08)  # Published CTGAN degradation range
    GENERAL_RANGE = (0.05, 0.15)  # General synthetic data degradation range

    # APRA benchmark for approval rate alignment
    APRA_APPROVAL_RATE = 0.65

    # Confidence interval asymmetry (downside risk > upside surprise)
    CI_LOW_OFFSET = 0.03
    CI_HIGH_OFFSET = 0.02

    def compute_apra_fidelity(self, metrics: dict, y_prob, df_test_raw) -> dict:
        """Compare model + synthetic data against live APRA Australian benchmarks.

        This is the Aussie-real grounding that replaces the literature-only
        baseline. It pulls the latest APRA quarterly NPL and arrears figures
        via ``MacroDataService.get_apra_quarterly_arrears()`` (no network
        requests — the benchmarks ship in the codebase as a transcribed
        lookup updated when new APRA releases are published).

        Three signals are returned:

        1. ``synthetic_default_rate`` vs ``apra_npl_rate``: how well the
           synthetic data's simulated default rate matches APRA reality.
        2. ``actual_default_auc``: model AUC scored against the true
           ``actual_outcome`` column (default/arrears_90) rather than the
           underwriting ``approved`` label. This is the honest measure of
           how well the decision boundary aligns with real risk.
        3. ``apra_fidelity_penalty``: AUC degradation proportional to the
           divergence between synthetic default rate and APRA NPL. Capped
           at 0.03 (a 3 percentage-point AUC penalty).

        Returns a dict with ``available=False`` if APRA data or
        ``actual_outcome`` cannot be accessed.
        """
        try:
            from .macro_data_service import MacroDataService

            apra = MacroDataService().get_apra_quarterly_arrears()
        except Exception:
            logger.warning("APRA benchmarks unavailable for TSTR fidelity check", exc_info=True)
            return {"available": False, "reason": "APRA MacroDataService unavailable"}

        apra_npl = apra.get("npl_rate")
        if apra_npl is None:
            return {"available": False, "reason": "APRA NPL rate missing"}

        result = {
            "available": True,
            "apra_quarter": apra.get("quarter"),
            "apra_published_date": apra.get("published_date"),
            "apra_npl_rate": apra_npl,
            "apra_total_arrears_rate": apra.get("total_arrears_rate"),
            "source": "APRA Quarterly ADI Property Exposures (MacroDataService)",
        }

        if df_test_raw is None or "actual_outcome" not in df_test_raw.columns:
            result["available"] = False
            result["reason"] = "Test set has no actual_outcome column"
            return result

        # Signal 1: synthetic data's simulated default rate vs APRA actual.
        # Restrict to rows with a simulated outcome — denied loans carry NaN
        # because no outcome was simulated for them, and including them would
        # deflate the default rate.
        outcome_series = df_test_raw["actual_outcome"]
        approved_mask = outcome_series.notna()
        n_with_outcome = int(approved_mask.sum())
        result["n_test_rows_with_outcome"] = n_with_outcome
        if n_with_outcome == 0:
            result["available"] = False
            result["reason"] = "No test rows with simulated outcome"
            return result

        default_mask = outcome_series.loc[approved_mask].isin(["default", "arrears_90"])
        synthetic_default_rate = float(default_mask.mean())
        delta = abs(synthetic_default_rate - apra_npl)
        relative_error = delta / apra_npl if apra_npl > 0 else None

        result["synthetic_default_rate"] = round(synthetic_default_rate, 4)
        result["data_fidelity_delta"] = round(delta, 4)
        result["data_fidelity_relative_error"] = (
            round(relative_error, 4) if relative_error is not None else None
        )

        rel_err = relative_error if relative_error is not None else 1.0
        if rel_err < 0.25:
            result["data_fidelity_interpretation"] = "well-aligned"
        elif rel_err < 0.75:
            result["data_fidelity_interpretation"] = "moderately-aligned"
        else:
            result["data_fidelity_interpretation"] = "poorly-aligned"

        # Signal 2: model AUC against TRUE default labels (not approved labels).
        # The model predicts P(approved); we convert to a risk score via
        # (1 - P(approved)) and score it against actual_outcome — but only on
        # rows where an outcome was simulated (approved loans).
        min_defaults_for_auc = 5
        n_defaults = int(default_mask.sum())
        if (
            n_defaults >= min_defaults_for_auc
            and not default_mask.all()
            and y_prob is not None
        ):
            try:
                from sklearn.metrics import roc_auc_score

                approved_pos = approved_mask.to_numpy()
                risk_score_full = 1.0 - np.asarray(y_prob)
                risk_score_subset = risk_score_full[approved_pos]
                if len(risk_score_subset) == len(default_mask):
                    actual_default_auc = float(
                        roc_auc_score(default_mask.astype(int).values, risk_score_subset)
                    )
                    approval_auc = metrics.get("auc_roc", 0.80)
                    result["actual_default_auc"] = round(actual_default_auc, 4)
                    result["approval_label_auc"] = round(approval_auc, 4)
                    result["auc_gap_approved_vs_actual"] = round(
                        approval_auc - actual_default_auc, 4
                    )
                else:
                    result["actual_default_auc"] = None
                    result["actual_default_auc_note"] = (
                        f"Length mismatch: y_prob subset={len(risk_score_subset)} vs "
                        f"default_mask={len(default_mask)}"
                    )
            except Exception:
                logger.warning("Failed to compute actual_default_auc", exc_info=True)
                result["actual_default_auc"] = None
        else:
            result["actual_default_auc"] = None
            result["actual_default_auc_note"] = (
                f"Insufficient defaults in test set: {n_defaults} < {min_defaults_for_auc}"
            )

        # Signal 3: fidelity penalty, capped at 0.03 AUC points
        result["apra_fidelity_penalty"] = round(min(0.03, max(0.0, rel_err) * 0.03), 4)
        return result

    def estimate_real_world_auc(self, metrics: dict, apra_fidelity: dict = None) -> dict:
        """Compute estimated real-world AUC from synthetic training metrics.

        When ``apra_fidelity`` is supplied and ``actual_default_auc`` is
        available, that measured value is used directly as the real-world
        AUC estimate (it was scored against true default labels, not
        inferred from degradation heuristics). Otherwise, falls back to a
        multi-factor degradation model keyed to the APRA fidelity penalty
        (if available) or the literature-based 5% baseline.
        """
        synthetic_auc = metrics.get("auc_roc", 0.80)
        metadata = metrics.get("training_metadata", {})

        # Extract quality signals with safe defaults
        overfitting_gap = metadata.get("overfitting_gap", 0.0)
        cv_auc_std = metadata.get("cv_auc_std", 0.02)
        ece = metrics.get("ece") or metrics.get("calibration_data", {}).get("ece", 0.03)

        # Temporal PSI (if available from vintage analysis)
        temporal_psi = metrics.get("vintage_analysis", {}).get("temporal_psi", {})
        max_psi = temporal_psi.get("max_psi") if temporal_psi else None

        # Compute penalty adjustments
        overfitting_penalty = max(0, (overfitting_gap - 0.03)) * 0.5
        cv_penalty = max(0, (cv_auc_std - 0.02)) * 2.0
        calibration_penalty = max(0, (ece - 0.05)) * 1.0
        temporal_bonus = -0.005 if (max_psi is not None and max_psi < 0.10) else 0.0

        # APRA fidelity penalty replaces the literature baseline when available
        apra_penalty = 0.0
        apra_methodology = ""
        apra_available = bool(apra_fidelity and apra_fidelity.get("available"))
        if apra_available:
            apra_penalty = apra_fidelity.get("apra_fidelity_penalty", 0.0)
            apra_methodology = (
                f"Live APRA {apra_fidelity.get('apra_quarter')} benchmark: "
                f"synthetic default rate {apra_fidelity.get('synthetic_default_rate')} vs "
                f"APRA NPL {apra_fidelity.get('apra_npl_rate')} "
                f"({apra_fidelity.get('data_fidelity_interpretation')}). "
            )

        total_adjustment = overfitting_penalty + cv_penalty + calibration_penalty + temporal_bonus
        total_degradation = self.BASE_DEGRADATION * (1 + total_adjustment) + apra_penalty
        total_degradation = max(self.MIN_DEGRADATION, total_degradation)

        # Prefer the measured actual-default AUC when available — it's a direct
        # reading, not a heuristic.
        actual_default_auc = (apra_fidelity or {}).get("actual_default_auc")
        if actual_default_auc is not None and actual_default_auc > 0.5:
            estimated_real_auc = actual_default_auc
            estimate_source = "measured_actual_default_auc"
        else:
            estimated_real_auc = synthetic_auc - total_degradation
            estimate_source = "degradation_heuristic"

        estimated_real_auc = max(0.50, min(synthetic_auc - self.MIN_DEGRADATION, estimated_real_auc))

        methodology = (
            apra_methodology
            + (
                "Estimate taken directly from measured AUC on actual default labels. "
                if estimate_source == "measured_actual_default_auc"
                else (
                    "APRA-grounded degradation model: literature baseline 5% "
                    "plus data-fidelity penalty from APRA NPL comparison. "
                    if apra_available
                    else "Literature-based TSTR degradation: 5% base AUC drop "
                    "(Xu et al. 2019, CTGAN). APRA benchmark not available. "
                )
            )
            + "Penalties applied for overfitting, CV instability, and poor calibration. "
            "Temporal PSI stability provides a small bonus when score distributions "
            "are stable across origination vintages."
        )

        return {
            "synthetic_auc": round(synthetic_auc, 4),
            "estimated_real_auc": round(estimated_real_auc, 4),
            "estimated_range": [
                round(max(0.50, estimated_real_auc - self.CI_LOW_OFFSET), 4),
                round(min(synthetic_auc - 0.005, estimated_real_auc + self.CI_HIGH_OFFSET), 4),
            ],
            "total_degradation": round(total_degradation, 4),
            "estimate_source": estimate_source,
            "degradation_breakdown": {
                "base": self.BASE_DEGRADATION,
                "overfitting_penalty": round(overfitting_penalty, 4),
                "cv_instability_penalty": round(cv_penalty, 4),
                "calibration_penalty": round(calibration_penalty, 4),
                "temporal_bonus": round(temporal_bonus, 4),
                "apra_fidelity_penalty": round(apra_penalty, 4),
            },
            "methodology": methodology,
            "references": [
                "APRA Quarterly ADI Property Exposures (live via MacroDataService)",
                "Xu et al. (2019), Modeling Tabular Data using Conditional GAN",
                "Jordon et al. (2022), Synthetic Data — What, Why and How?",
                "Assefa et al. (2020), Generating Synthetic Data in Finance",
            ],
        }

    def compute_confidence_score(self, metrics: dict) -> dict:
        """Compute synthetic confidence score (0-1).

        Five sub-scores are averaged, each mapping an observable metric
        to a 0-1 range. Optional sub-scores are omitted if data is
        unavailable (average uses only available components).
        """
        metadata = metrics.get("training_metadata", {})

        sub_scores = {}
        available = []

        # 1. CV stability (cv_auc_std < 0.01 is excellent)
        cv_std = metadata.get("cv_auc_std")
        if cv_std is not None:
            sub_scores["cv_stability"] = round(max(0.0, 1.0 - cv_std / 0.05), 4)
            available.append(sub_scores["cv_stability"])

        # 2. Overfitting (gap < 0.02 is excellent)
        gap = metadata.get("overfitting_gap")
        if gap is not None:
            sub_scores["overfitting"] = round(max(0.0, 1.0 - gap / 0.10), 4)
            available.append(sub_scores["overfitting"])

        # 3. Calibration (ECE < 0.02 is excellent)
        ece = metrics.get("ece") or metrics.get("calibration_data", {}).get("ece")
        if ece is not None:
            sub_scores["calibration"] = round(max(0.0, 1.0 - ece / 0.10), 4)
            available.append(sub_scores["calibration"])

        # 4. Temporal PSI stability (optional — requires vintage analysis)
        temporal_psi = metrics.get("vintage_analysis", {}).get("temporal_psi", {})
        max_psi = temporal_psi.get("max_psi") if temporal_psi else None
        if max_psi is not None:
            sub_scores["temporal_stability"] = round(max(0.0, 1.0 - max_psi / 0.25), 4)
            available.append(sub_scores["temporal_stability"])
        else:
            sub_scores["temporal_stability"] = None

        # 5. Benchmark alignment (optional — approval rate vs APRA 65%)
        class_balance = metadata.get("class_balance")
        if class_balance is not None:
            alignment = max(0.0, 1.0 - abs(class_balance - self.APRA_APPROVAL_RATE) / 0.15)
            sub_scores["benchmark_alignment"] = round(alignment, 4)
            available.append(sub_scores["benchmark_alignment"])
        else:
            sub_scores["benchmark_alignment"] = None

        # Compute overall score
        if available:
            overall = round(sum(available) / len(available), 4)
        else:
            overall = 0.5  # Unknown — neutral default

        if overall >= 0.80:
            interpretation = "high"
        elif overall >= 0.60:
            interpretation = "moderate"
        else:
            interpretation = "low"

        return {
            "overall_score": overall,
            "interpretation": interpretation,
            "sub_scores": sub_scores,
            "n_components": len(available),
            "methodology": (
                "Composite of up to 5 quality signals: CV stability, "
                "overfitting gap, calibration error, temporal PSI, "
                "and benchmark alignment. Each mapped to 0-1 and averaged."
            ),
        }

    def validate(self, metrics: dict, y_prob=None, df_test_raw=None) -> dict:
        """Run full TSTR validation grounded in APRA benchmarks when available.

        Parameters
        ----------
        metrics : dict
            Training metrics dict from ``ModelTrainer.train``.
        y_prob : array-like, optional
            Model predicted approval probabilities on the test set. When
            supplied together with ``df_test_raw``, enables live APRA
            fidelity scoring against true default labels.
        df_test_raw : pd.DataFrame, optional
            Raw test set (with ``actual_outcome`` column preserved). Used
            to measure model AUC against true default labels rather than
            the underwriting ``approved`` label.
        """
        apra_fidelity = None
        if y_prob is not None and df_test_raw is not None:
            try:
                apra_fidelity = self.compute_apra_fidelity(metrics, y_prob, df_test_raw)
            except Exception:
                logger.warning("APRA fidelity computation failed", exc_info=True)

        real_auc = self.estimate_real_world_auc(metrics, apra_fidelity=apra_fidelity)
        confidence = self.compute_confidence_score(metrics)

        summary = (
            f"Estimated real-world AUC: {real_auc['estimated_real_auc']:.3f} "
            f"(synthetic: {real_auc['synthetic_auc']:.3f}, "
            f"degradation: -{real_auc['total_degradation']:.3f}, "
            f"source: {real_auc.get('estimate_source', 'n/a')}), "
            f"confidence: {confidence['overall_score']:.2f} ({confidence['interpretation']})"
        )
        if apra_fidelity and apra_fidelity.get("available"):
            summary += (
                f", APRA {apra_fidelity.get('apra_quarter')} "
                f"data fidelity: {apra_fidelity.get('data_fidelity_interpretation')}"
            )

        return {
            "estimated_real_world_auc": real_auc,
            "synthetic_confidence": confidence,
            "apra_fidelity": apra_fidelity,
            "summary": summary,
        }
