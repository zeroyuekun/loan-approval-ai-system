"""Risk-based pricing tiers (D4).

Maps a PD score + product segment to an indicative interest-rate band and
pricing-tier label. AU challenger banks publish coarse pricing bands by
customer risk grade; this module centralises the mapping so the decision
payload, email templates, and admin UI all quote the same numbers.

Bands are deliberately conservative relative to Big-4 headline rates so
that generated quotes are defensible as "indicative only" — final pricing
is always underwriter-signed. The tier band is documented to the applicant
alongside a disclaimer that actual rate depends on full credit assessment.

Numerical bands follow spec §D4:

  Personal  Tier A  PD ≤ 0.03   7.0–9.5%
            Tier B  PD ≤ 0.07   9.5–14.0%
            Tier C  PD ≤ 0.15   14.0–19.0%
            Tier D  PD ≤ 0.25   19.0–24.0%
            Decline PD > 0.25

  Home      Tier A  PD ≤ 0.01   6.0–6.5%
            Tier B  PD ≤ 0.03   6.5–7.2%
            Tier C  PD ≤ 0.06   7.2–8.0%
            Tier D  PD ≤ 0.10   8.0–9.0%
            Decline PD > 0.10

PD (probability of default) is simply (1 − approval_probability) for the
current model. Downstream callers pass `pd_score` directly; the module
does not read from the model object.
"""

from __future__ import annotations

from dataclasses import dataclass

# Segment identifiers. Accept both the D2 SEGMENT_* constants and the raw
# "home"/"personal" strings so this module doesn't force callers to import
# segmentation to quote a tier. The helper below resolves both forms.
SEGMENT_PERSONAL = "personal"
SEGMENT_HOME = "home"  # covers owner-occupier + investor + any secured home product
SEGMENT_INVESTMENT = "investment"

# PD cutoffs + rate bands are indicative only. Bands are (min_rate, max_rate)
# APR. The Decline tier carries no rate — pricing is not offered.
_PERSONAL_TIERS: list[tuple[str, float, tuple[float, float]]] = [
    ("A", 0.03, (7.0, 9.5)),
    ("B", 0.07, (9.5, 14.0)),
    ("C", 0.15, (14.0, 19.0)),
    ("D", 0.25, (19.0, 24.0)),
]
_HOME_TIERS: list[tuple[str, float, tuple[float, float]]] = [
    ("A", 0.01, (6.0, 6.5)),
    ("B", 0.03, (6.5, 7.2)),
    ("C", 0.06, (7.2, 8.0)),
    ("D", 0.10, (8.0, 9.0)),
]


@dataclass
class PricingTier:
    """Indicative pricing decision attached to an approved application.

    Attributes:
        tier: "A", "B", "C", "D", or "Decline". "Decline" means the PD
            exceeded every band — the caller should treat it as a deny
            even if the model alone would have approved.
        rate_min: lower bound of the APR band in %; None if Decline.
        rate_max: upper bound of the APR band in %; None if Decline.
        segment: the pricing segment used ("personal" or "home").
        pd_score: the PD that drove the tier decision (for audit).
        rationale: short string explaining tier assignment — used in
            decision waterfalls and adverse-action letters.
    """

    tier: str
    segment: str
    pd_score: float
    rate_min: float | None = None
    rate_max: float | None = None
    rationale: str = ""

    @property
    def approved(self) -> bool:
        return self.tier != "Decline"

    def midpoint(self) -> float | None:
        if self.rate_min is None or self.rate_max is None:
            return None
        return round((self.rate_min + self.rate_max) / 2.0, 2)

    def band_label(self) -> str:
        """Human-readable rate band ("7.0%–9.5%" or "Not offered")."""
        if self.rate_min is None or self.rate_max is None:
            return "Not offered"
        return f"{self.rate_min:.1f}%–{self.rate_max:.1f}%"

    def to_dict(self) -> dict:
        return {
            "tier": self.tier,
            "segment": self.segment,
            "pd_score": round(float(self.pd_score), 4),
            "rate_min": self.rate_min,
            "rate_max": self.rate_max,
            "rate_midpoint": self.midpoint(),
            "rate_band": self.band_label(),
            "approved": self.approved,
            "rationale": self.rationale,
        }


def _resolve_segment(segment: str) -> str:
    """Normalise a segment string to either 'personal' or 'home'.

    Accepts the D2 constants (home_owner_occupier / home_investor / personal),
    the raw LoanApplication.purpose values ("home", "investment", "personal"),
    and the unified fallback (routes to personal for pricing purposes, since
    unified-model approvals default to the widest risk tolerance band).
    """
    if segment is None:
        return SEGMENT_PERSONAL
    s = str(segment).lower()
    if s in ("home", "home_owner_occupier", "owner_occupier"):
        return SEGMENT_HOME
    if s in ("investment", "home_investor", "investor"):
        # Investment home loans price slightly above owner-occupier, but
        # using the home band is the regulator-safe default at this tier
        # granularity. A later revision may split into a dedicated investor
        # table; see spec §D4 follow-up.
        return SEGMENT_HOME
    if s in ("personal", "education", "auto", "unified"):
        return SEGMENT_PERSONAL
    raise ValueError(f"Unknown segment for pricing: {segment!r}")


def get_tier(pd_score: float, segment: str) -> PricingTier:
    """Map (PD, segment) to a PricingTier.

    Boundary handling: tier cutoffs are inclusive (`PD <= cutoff` wins the
    tier). PD values strictly greater than every tier cutoff return
    "Decline" with no rate band. Negative PDs (numerical noise) are
    clamped to 0. PD > 1.0 is accepted and routes to Decline.
    """
    try:
        pd_score = float(pd_score)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"pd_score must be numeric, got {pd_score!r}") from exc

    pd_score = max(0.0, pd_score)

    resolved = _resolve_segment(segment)
    tiers = _HOME_TIERS if resolved == SEGMENT_HOME else _PERSONAL_TIERS

    for tier_label, cutoff, (lo, hi) in tiers:
        if pd_score <= cutoff:
            return PricingTier(
                tier=tier_label,
                segment=resolved,
                pd_score=pd_score,
                rate_min=lo,
                rate_max=hi,
                rationale=(
                    f"PD {pd_score:.4f} ≤ {cutoff} → {resolved} tier {tier_label}, indicative {lo:.1f}–{hi:.1f}% APR"
                ),
            )

    # PD above every cutoff → decline
    top_cutoff = tiers[-1][1]
    return PricingTier(
        tier="Decline",
        segment=resolved,
        pd_score=pd_score,
        rate_min=None,
        rate_max=None,
        rationale=(f"PD {pd_score:.4f} exceeds maximum priced tier cutoff ({top_cutoff}) — risk outside appetite"),
    )
