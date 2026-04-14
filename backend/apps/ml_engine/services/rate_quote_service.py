"""Rate quote service — translates ML probability to a rate band plus factors.

Hand-tuned bands. NOT env-configurable; changing thresholds is a product
decision that warrants code review.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

BAND_EXCELLENT = "excellent"
BAND_STANDARD = "standard"
BAND_SUB_PRIME = "sub_prime"


@dataclass(frozen=True)
class RateBand:
    name: str
    probability_upper_exclusive: float  # probability of default threshold (exclusive)
    apr_min: Decimal
    apr_max: Decimal


_BANDS = (
    RateBand(BAND_EXCELLENT, 0.08, Decimal("6.50"), Decimal("8.50")),
    RateBand(BAND_STANDARD, 0.20, Decimal("8.50"), Decimal("13.50")),
    RateBand(BAND_SUB_PRIME, float("inf"), Decimal("13.50"), Decimal("22.00")),
)

# Fixed comparison-rate offset (AU-market convention: comparison rate ~0.5% above APR midpoint for typical fees).
_COMPARISON_RATE_FEE_OFFSET = Decimal("0.50")

# Plausible AU-market means for top-factor z-scoring. Deliberately simple and
# documented; swap for bureau means later if we have them.
_FEATURE_MEANS = {
    "credit_score": (700.0, 80.0),  # (mean, std)
    "employment_length": (6.0, 5.0),
    "debt_to_income": (0.25, 0.12),
    "annual_income": (85000.0, 35000.0),
    "monthly_expenses": (3500.0, 1500.0),
    "loan_amount": (25000.0, 20000.0),
    "loan_term_months": (48.0, 24.0),
}

# Features where higher = better for the borrower. Others treated as higher = worse.
_POSITIVE_WHEN_HIGH = {"credit_score", "employment_length", "annual_income"}


class RateQuoteService:
    def band_for_probability(self, probability: float) -> str:
        for band in _BANDS:
            if probability < band.probability_upper_exclusive:
                return band.name
        return _BANDS[-1].name  # unreachable due to inf sentinel; defensive

    def band_apr_range(self, band_name: str) -> tuple[Decimal, Decimal]:
        for band in _BANDS:
            if band.name == band_name:
                return band.apr_min, band.apr_max
        raise ValueError(f"Unknown band: {band_name}")

    def amortised_monthly_payment(self, principal: Decimal, apr_percent: Decimal, term_months: int) -> Decimal:
        if term_months <= 0:
            raise ValueError("term_months must be positive")
        r = (apr_percent / Decimal("100")) / Decimal("12")
        if r == 0:
            payment = principal / Decimal(term_months)
        else:
            one_plus_r_to_n = (Decimal("1") + r) ** term_months
            payment = principal * r * one_plus_r_to_n / (one_plus_r_to_n - Decimal("1"))
        return payment.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def comparison_rate_estimate(self, apr_min: Decimal, apr_max: Decimal) -> Decimal:
        midpoint = (apr_min + apr_max) / Decimal("2")
        return (midpoint + _COMPARISON_RATE_FEE_OFFSET).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def top_rate_factors(self, request_fields: dict, n: int = 3) -> list[dict]:
        scored = []
        for feature, (mean, std) in _FEATURE_MEANS.items():
            val = request_fields.get(feature)
            if val is None or std == 0:
                continue
            z = (float(val) - mean) / std
            impact = self._impact_for(feature, z)
            scored.append({"name": feature, "z_score": z, "impact": impact})
        scored.sort(key=lambda f: abs(f["z_score"]), reverse=True)
        return [{"name": f["name"], "impact": f["impact"]} for f in scored[:n]]

    @staticmethod
    def _impact_for(feature: str, z: float) -> str:
        if abs(z) < 0.3:
            return "neutral"
        positive_when_high = feature in _POSITIVE_WHEN_HIGH
        high = z > 0
        if positive_when_high == high:
            return "positive"
        return "negative"

    def build_quote(self, probability: float, request_fields: dict) -> dict:
        """Convenience bundle for the view."""
        band_name = self.band_for_probability(probability)
        apr_min, apr_max = self.band_apr_range(band_name)
        midpoint_apr = (apr_min + apr_max) / Decimal("2")
        monthly = self.amortised_monthly_payment(
            principal=Decimal(str(request_fields["loan_amount"])),
            apr_percent=midpoint_apr,
            term_months=int(request_fields["loan_term_months"]),
        )
        return {
            "band": band_name,
            "rate_min": apr_min,
            "rate_max": apr_max,
            "comparison_rate": self.comparison_rate_estimate(apr_min, apr_max),
            "estimated_monthly_repayment": monthly,
            "top_rate_factors": self.top_rate_factors(request_fields),
        }
