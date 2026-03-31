"""Train-Synthetic-Test-Real (TSTR) validation framework.

Estimates real-world model performance from synthetic training metrics
using literature-based degradation models and observable quality signals.

In credit risk modelling, models trained on synthetic data exhibit
measurable AUC degradation when evaluated on real loan portfolios.
This module quantifies that expected gap and produces a confidence
score reflecting how trustworthy the synthetic metrics are.

References:
    Xu et al. (2019), "Modeling Tabular Data using Conditional GAN"
        — CTGAN achieves ~3% AUC degradation on tabular benchmarks.
    Jordon et al. (2022), "Synthetic Data — What, Why and How?"
        — General synthetic data degrades 5-15% vs real across domains.
    Assefa et al. (2020), "Generating Synthetic Data in Finance"
        — Credit risk synthetic validation, calibration methodology.
"""

from __future__ import annotations


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

    def estimate_real_world_auc(self, metrics: dict) -> dict:
        """Compute estimated real-world AUC from synthetic training metrics.

        Applies a multi-factor degradation model: a literature-based baseline
        (5% AUC drop) modulated by observable model quality signals that
        predict larger or smaller synthetic-to-real transfer gaps.
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

        total_adjustment = overfitting_penalty + cv_penalty + calibration_penalty + temporal_bonus
        total_degradation = self.BASE_DEGRADATION * (1 + total_adjustment)
        total_degradation = max(self.MIN_DEGRADATION, total_degradation)

        estimated_real_auc = synthetic_auc - total_degradation
        estimated_real_auc = max(0.50, min(synthetic_auc - self.MIN_DEGRADATION, estimated_real_auc))

        return {
            "synthetic_auc": round(synthetic_auc, 4),
            "estimated_real_auc": round(estimated_real_auc, 4),
            "estimated_range": [
                round(max(0.50, estimated_real_auc - self.CI_LOW_OFFSET), 4),
                round(min(synthetic_auc - 0.005, estimated_real_auc + self.CI_HIGH_OFFSET), 4),
            ],
            "total_degradation": round(total_degradation, 4),
            "degradation_breakdown": {
                "base": self.BASE_DEGRADATION,
                "overfitting_penalty": round(overfitting_penalty, 4),
                "cv_instability_penalty": round(cv_penalty, 4),
                "calibration_penalty": round(calibration_penalty, 4),
                "temporal_bonus": round(temporal_bonus, 4),
            },
            "methodology": (
                "Literature-based TSTR degradation model: 5% base AUC drop "
                "(Xu et al. 2019, CTGAN) with penalties for overfitting, "
                "CV instability, and poor calibration. Temporal PSI stability "
                "provides a small bonus when score distributions are stable "
                "across origination vintages."
            ),
            "references": [
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

    def validate(self, metrics: dict) -> dict:
        """Run full TSTR validation. Convenience method combining both."""
        real_auc = self.estimate_real_world_auc(metrics)
        confidence = self.compute_confidence_score(metrics)

        # One-line summary for logging
        summary = (
            f"Estimated real-world AUC: {real_auc['estimated_real_auc']:.3f} "
            f"(synthetic: {real_auc['synthetic_auc']:.3f}, "
            f"degradation: -{real_auc['total_degradation']:.3f}), "
            f"confidence: {confidence['overall_score']:.2f} ({confidence['interpretation']})"
        )

        return {
            "estimated_real_world_auc": real_auc,
            "synthetic_confidence": confidence,
            "summary": summary,
        }
