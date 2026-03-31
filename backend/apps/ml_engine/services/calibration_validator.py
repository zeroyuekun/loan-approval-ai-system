"""Calibration validation service — compares system predictions against APRA benchmarks.

Performs three-way calibration checking:
1. Internal: predicted default rate vs system's actual default rate
2. External: system's actual default rate vs APRA published benchmarks
3. Combined: overall calibration assessment with recommendations

This addresses SR 11-7's requirement for "outcomes analysis" and provides
evidence that the model's predictions are grounded in real-world Australian
lending performance data published by APRA.

References:
    - APRA Quarterly ADI Property Exposures: apra.gov.au
    - SR 11-7 (Federal Reserve, 2011): outcomes analysis requirement
    - RBA Financial Stability Review: rba.gov.au/publications/fsr/
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Acceptable variance from APRA benchmark before flagging
DEFAULT_ACCEPTABLE_VARIANCE = 0.005  # +/- 0.5 percentage points


class CalibrationValidator:
    """Validates model calibration against APRA aggregate benchmarks."""

    def __init__(self, apra_benchmarks: dict = None):
        """
        Args:
            apra_benchmarks: APRA quarterly data dict. If None, fetches latest
                from MacroDataService.
        """
        if apra_benchmarks is not None:
            self._apra = apra_benchmarks
        else:
            from backend.apps.ml_engine.services.macro_data_service import (
                MacroDataService,
            )

            service = MacroDataService()
            self._apra = service.get_apra_quarterly_arrears()

    # ------------------------------------------------------------------
    # Public validators
    # ------------------------------------------------------------------

    def validate_prediction_calibration(
        self,
        system_default_rate: float,
        system_arrears_90_rate: float,
        predicted_default_rate: float,
        total_applications: int,
        acceptable_variance: float = DEFAULT_ACCEPTABLE_VARIANCE,
    ) -> dict:
        """Three-way calibration check.

        Compares:
        - Predicted vs actual default rate (internal calibration)
        - Actual arrears vs APRA benchmark (external calibration)

        Returns:
            {
                'internal_calibration': {
                    'predicted_default_rate': float,
                    'actual_default_rate': float,
                    'gap': float,
                    'status': 'well_calibrated' | 'optimistic' | 'pessimistic'
                },
                'external_calibration': {
                    'system_arrears_90_rate': float,
                    'apra_benchmark_rate': float,
                    'gap': float,
                    'status': 'aligned' | 'above_benchmark' | 'below_benchmark'
                },
                'overall_status': 'pass' | 'review' | 'fail',
                'recommendations': [str],
                'apra_quarter': str,
                'apra_published_date': str,
                'validated_at': str,
            }
        """
        apra_arrears_90 = self._apra.get("arrears_90_rate", 0.0047)
        apra_quarter = self._apra.get("quarter", "unknown")
        apra_published = self._apra.get("published_date", "unknown")

        # --- Internal calibration: predicted vs actual ---
        internal_gap = predicted_default_rate - system_default_rate
        if abs(internal_gap) <= acceptable_variance:
            internal_status = "well_calibrated"
        elif internal_gap > 0:
            internal_status = "pessimistic"
        else:
            internal_status = "optimistic"

        # --- External calibration: actual vs APRA benchmark ---
        external_gap = system_arrears_90_rate - apra_arrears_90
        if abs(external_gap) <= acceptable_variance:
            external_status = "aligned"
        elif external_gap > 0:
            external_status = "above_benchmark"
        else:
            external_status = "below_benchmark"

        # --- Overall status ---
        internal_exceeds = abs(internal_gap) > acceptable_variance
        external_exceeds = abs(external_gap) > acceptable_variance

        if internal_exceeds and external_exceeds:
            overall_status = "fail"
        elif internal_exceeds or external_exceeds:
            overall_status = "review"
        else:
            overall_status = "pass"

        # --- Recommendations ---
        recommendations = self._build_calibration_recommendations(
            internal_gap=internal_gap,
            internal_status=internal_status,
            external_gap=external_gap,
            external_status=external_status,
            overall_status=overall_status,
            system_arrears_90_rate=system_arrears_90_rate,
            apra_arrears_90=apra_arrears_90,
            predicted_default_rate=predicted_default_rate,
            system_default_rate=system_default_rate,
            total_applications=total_applications,
            apra_quarter=apra_quarter,
            acceptable_variance=acceptable_variance,
        )

        result = {
            "internal_calibration": {
                "predicted_default_rate": round(predicted_default_rate, 6),
                "actual_default_rate": round(system_default_rate, 6),
                "gap": round(internal_gap, 6),
                "status": internal_status,
            },
            "external_calibration": {
                "system_arrears_90_rate": round(system_arrears_90_rate, 6),
                "apra_benchmark_rate": round(apra_arrears_90, 6),
                "gap": round(external_gap, 6),
                "status": external_status,
            },
            "overall_status": overall_status,
            "recommendations": recommendations,
            "apra_quarter": apra_quarter,
            "apra_published_date": apra_published,
            "validated_at": datetime.utcnow().isoformat() + "Z",
        }

        logger.info(
            "Calibration validation: overall=%s, internal=%s (gap=%.4f), external=%s (gap=%.4f), n=%d",
            overall_status,
            internal_status,
            internal_gap,
            external_status,
            external_gap,
            total_applications,
        )
        return result

    def validate_by_state(
        self,
        state_outcomes: dict,
    ) -> dict:
        """Compare state-level outcomes to APRA state benchmarks.

        Args:
            state_outcomes: Mapping of state code to outcomes dict, e.g.
                {'NSW': {'default_rate': 0.005, 'count': 120}, ...}

        Returns:
            dict mapping state to {system_rate, apra_rate, gap, status}
        """
        apra_by_state = self._apra.get("by_state", {})
        apra_quarter = self._apra.get("quarter", "unknown")
        results = {}

        for state, outcomes in state_outcomes.items():
            state_upper = state.upper()
            system_rate = outcomes.get("default_rate", 0.0)
            count = outcomes.get("count", 0)
            apra_rate = apra_by_state.get(state_upper)

            if apra_rate is None:
                logger.warning(
                    "No APRA benchmark for state %s — skipping",
                    state_upper,
                )
                results[state_upper] = {
                    "system_rate": round(system_rate, 6),
                    "apra_rate": None,
                    "gap": None,
                    "status": "no_benchmark",
                    "count": count,
                }
                continue

            gap = system_rate - apra_rate
            if abs(gap) <= DEFAULT_ACCEPTABLE_VARIANCE:
                status = "aligned"
            elif gap > 0:
                status = "above_benchmark"
            else:
                status = "below_benchmark"

            results[state_upper] = {
                "system_rate": round(system_rate, 6),
                "apra_rate": round(apra_rate, 6),
                "gap": round(gap, 6),
                "status": status,
                "count": count,
            }

            if status != "aligned":
                logger.info(
                    "State %s calibration: system=%.4f vs APRA=%.4f (gap=%.4f, n=%d, APRA %s)",
                    state_upper,
                    system_rate,
                    apra_rate,
                    gap,
                    count,
                    apra_quarter,
                )

        return results

    def validate_portfolio_composition(
        self,
        lvr_80_plus_pct: float,
        dti_6_plus_pct: float,
    ) -> dict:
        """Compare portfolio risk composition to APRA benchmarks.

        APRA publishes: 30.8% of new loans have LVR >= 80%, 6.1% have DTI >= 6.
        If the system's portfolio deviates significantly, it suggests the
        synthetic data generator needs recalibration.

        Args:
            lvr_80_plus_pct: Proportion of portfolio with LVR >= 80% (0-1 scale).
            dti_6_plus_pct: Proportion of portfolio with DTI >= 6 (0-1 scale).

        Returns:
            dict with lvr and dti calibration details.
        """
        apra_lvr = self._apra.get("lvr_80_plus_pct", 0.308)
        apra_dti = self._apra.get("dti_6_plus_pct", 0.061)
        apra_quarter = self._apra.get("quarter", "unknown")

        lvr_gap = lvr_80_plus_pct - apra_lvr
        dti_gap = dti_6_plus_pct - apra_dti

        # Use a wider variance for composition (2 percentage points)
        composition_variance = 0.02

        def _composition_status(gap: float) -> str:
            if abs(gap) <= composition_variance:
                return "aligned"
            return "above_benchmark" if gap > 0 else "below_benchmark"

        lvr_status = _composition_status(lvr_gap)
        dti_status = _composition_status(dti_gap)

        recommendations = []
        if lvr_status != "aligned":
            recommendations.append(
                f"Portfolio LVR>=80% share ({lvr_80_plus_pct:.1%}) differs from "
                f"APRA benchmark ({apra_lvr:.1%}) by {abs(lvr_gap):.1%}pp "
                f"(APRA Quarterly ADI Statistics, {apra_quarter}) "
                f"— synthetic data generator may need recalibration."
            )
        if dti_status != "aligned":
            recommendations.append(
                f"Portfolio DTI>=6 share ({dti_6_plus_pct:.1%}) differs from "
                f"APRA benchmark ({apra_dti:.1%}) by {abs(dti_gap):.1%}pp "
                f"(APRA Quarterly ADI Statistics, {apra_quarter}) "
                f"— synthetic data generator may need recalibration."
            )

        result = {
            "lvr_80_plus": {
                "system_pct": round(lvr_80_plus_pct, 4),
                "apra_benchmark_pct": round(apra_lvr, 4),
                "gap": round(lvr_gap, 4),
                "status": lvr_status,
            },
            "dti_6_plus": {
                "system_pct": round(dti_6_plus_pct, 4),
                "apra_benchmark_pct": round(apra_dti, 4),
                "gap": round(dti_gap, 4),
                "status": dti_status,
            },
            "recommendations": recommendations,
            "apra_quarter": apra_quarter,
        }

        logger.info(
            "Portfolio composition: LVR=%s (gap=%.4f), DTI=%s (gap=%.4f)",
            lvr_status,
            lvr_gap,
            dti_status,
            dti_gap,
        )
        return result

    def generate_calibration_report(
        self,
        system_default_rate: float,
        system_arrears_90_rate: float,
        predicted_default_rate: float,
        total_applications: int,
        state_outcomes: dict = None,
        lvr_80_plus_pct: float = None,
        dti_6_plus_pct: float = None,
    ) -> dict:
        """Generate comprehensive calibration report combining all checks.

        This is the main entry point for calibration validation.

        Args:
            system_default_rate: Observed default rate in the system.
            system_arrears_90_rate: Observed 90+ day arrears rate.
            predicted_default_rate: Model's predicted default rate.
            total_applications: Number of applications in the assessment window.
            state_outcomes: Optional state-level outcomes for geographic validation.
            lvr_80_plus_pct: Optional proportion of portfolio with LVR >= 80%.
            dti_6_plus_pct: Optional proportion of portfolio with DTI >= 6.

        Returns:
            Comprehensive calibration report dict.
        """
        report = {
            "report_type": "calibration_validation",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "apra_quarter": self._apra.get("quarter", "unknown"),
            "apra_published_date": self._apra.get("published_date", "unknown"),
            "total_applications": total_applications,
        }

        # Core prediction calibration
        report["prediction_calibration"] = self.validate_prediction_calibration(
            system_default_rate=system_default_rate,
            system_arrears_90_rate=system_arrears_90_rate,
            predicted_default_rate=predicted_default_rate,
            total_applications=total_applications,
        )

        # State-level calibration (optional)
        if state_outcomes:
            report["state_calibration"] = self.validate_by_state(state_outcomes)

        # Portfolio composition (optional)
        if lvr_80_plus_pct is not None and dti_6_plus_pct is not None:
            report["portfolio_composition"] = self.validate_portfolio_composition(
                lvr_80_plus_pct=lvr_80_plus_pct,
                dti_6_plus_pct=dti_6_plus_pct,
            )

        # Aggregate recommendations from all sections
        all_recommendations = list(report["prediction_calibration"].get("recommendations", []))
        if "state_calibration" in report:
            for state, state_data in report["state_calibration"].items():
                if state_data.get("status") == "above_benchmark":
                    all_recommendations.append(
                        f"State {state} default rate ({state_data['system_rate']:.4f}) "
                        f"exceeds APRA benchmark ({state_data['apra_rate']:.4f}) by "
                        f"{abs(state_data['gap']):.4f}pp "
                        f"(APRA Quarterly ADI Statistics, {report['apra_quarter']}) "
                        f"— investigate state-level risk factors."
                    )
        if "portfolio_composition" in report:
            all_recommendations.extend(report["portfolio_composition"].get("recommendations", []))

        report["all_recommendations"] = all_recommendations

        # Overall summary status
        overall = report["prediction_calibration"]["overall_status"]
        report["overall_status"] = overall

        logger.info(
            "Calibration report generated: overall=%s, recommendations=%d, n=%d",
            overall,
            len(all_recommendations),
            total_applications,
        )
        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_calibration_recommendations(
        *,
        internal_gap: float,
        internal_status: str,
        external_gap: float,
        external_status: str,
        overall_status: str,
        system_arrears_90_rate: float,
        apra_arrears_90: float,
        predicted_default_rate: float,
        system_default_rate: float,
        total_applications: int,
        apra_quarter: str,
        acceptable_variance: float,
    ) -> list[str]:
        """Build specific, actionable recommendations."""
        recommendations = []

        if internal_status == "optimistic":
            recommendations.append(
                f"Model is optimistic: predicted default rate "
                f"({predicted_default_rate:.2%}) is below actual "
                f"({system_default_rate:.2%}) by {abs(internal_gap):.2%}pp "
                f"— consider retraining with updated outcomes data."
            )
        elif internal_status == "pessimistic":
            recommendations.append(
                f"Model is pessimistic: predicted default rate "
                f"({predicted_default_rate:.2%}) exceeds actual "
                f"({system_default_rate:.2%}) by {abs(internal_gap):.2%}pp "
                f"— review threshold calibration."
            )

        if external_status == "above_benchmark":
            recommendations.append(
                f"System arrears rate ({system_arrears_90_rate:.2%}) exceeds "
                f"APRA benchmark ({apra_arrears_90:.2%}) by "
                f"{abs(external_gap):.2%}pp "
                f"(APRA Quarterly ADI Statistics, {apra_quarter}) "
                f"— synthetic data generator may need recalibration."
            )
        elif external_status == "below_benchmark":
            recommendations.append(
                f"System arrears rate ({system_arrears_90_rate:.2%}) is below "
                f"APRA benchmark ({apra_arrears_90:.2%}) by "
                f"{abs(external_gap):.2%}pp "
                f"(APRA Quarterly ADI Statistics, {apra_quarter}) "
                f"— model may be overly conservative."
            )

        if overall_status == "pass":
            recommendations.append(
                f"Calibration within acceptable bounds "
                f"(+/- {acceptable_variance:.1%}pp of APRA benchmarks, "
                f"{apra_quarter}). No action required."
            )

        if total_applications < 100:
            recommendations.append(
                f"Sample size ({total_applications}) is small — "
                f"calibration results may not be statistically significant. "
                f"Consider waiting for more outcomes data."
            )

        return recommendations
