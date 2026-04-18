"""Hard credit policy overlay (AU responsible-lending gate).

Big-4 AU lenders wrap their ML model in a deterministic credit-policy rule
engine that can override the model. The model is probabilistic; the overlay
is categorical. Two kinds of verdict:

* **Hard-fail** (P01-P07): denies the application outright regardless of
  the model's score. Mirrors the "knockout rules" in CBA/NAB credit policy
  manuals — bankrupt, minor, >95% LVR with no LMI path, DTI above APRA's
  interventions, etc.

* **Refer** (P08-P12): flags the application for human review. The model
  may still score it as high probability but certain combinations demand
  eyes-on underwriting — large LTI, hardship history, self-employed new
  business, TMD mismatch.

Only a handful of applicants hit any given rule, but the ones who do
typically carry outsized default risk, and regulators (ASIC RG 209, APRA
APS 220) explicitly expect a categorical layer on top of any model.

Rollout is gated by env var `CREDIT_POLICY_OVERLAY_MODE`:
  * `off`     — overlay is evaluated but not applied; purely observational
  * `shadow`  — decisions are logged and attached to the response as
                `policy_decision`, but the model verdict stands
  * `enforce` — hard-fails override the model; refers route to a human
                review record (see D6)

Default is `shadow` until the rule set has been calibrated against backtest
data. Promotion to `enforce` is a separate ops change.

This module is pure policy — no Django imports at module load, no I/O. The
predictor calls `evaluate(application)` with either a LoanApplication row
or a feature dict; the overlay layer handles both uniformly.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# Env-var keys (settings.py can also honour these via os.environ).
OVERLAY_MODE_ENV = "CREDIT_POLICY_OVERLAY_MODE"
OVERLAY_MODE_OFF = "off"
OVERLAY_MODE_SHADOW = "shadow"
OVERLAY_MODE_ENFORCE = "enforce"
OVERLAY_MODES = (OVERLAY_MODE_OFF, OVERLAY_MODE_SHADOW, OVERLAY_MODE_ENFORCE)


# Thresholds centralised here so that the MRM dossier and audit views can
# cite the exact values used at decision time.
MAX_DTI = 8.0                 # APRA intervention threshold (2021 letter)
REFER_LTI = 9.0               # NAB LTI ceiling
MAX_LVR_HOME = 0.95           # LMI cap for owner-occupier
MAX_LVR_ANY = 1.00            # Hard no-negative-equity boundary
MIN_CREDIT_SCORE = 450        # Bureau floor for any automated approval
MIN_EMP_TENURE_MONTHS_SE = 24 # Self-employed minimum trading history


@dataclass
class PolicyResult:
    """Outcome of running the overlay against one application."""
    hard_fails: list[str] = field(default_factory=list)
    refers: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    evaluated_rules: list[str] = field(default_factory=list)
    # code → raw reason text (without the "Pxx (hard-fail/refer): " prefix).
    # Used by D6 audit trail to populate LoanApplication.referral_rationale.
    rationale_by_code: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.hard_fails and not self.refers

    @property
    def has_hard_fail(self) -> bool:
        return bool(self.hard_fails)

    @property
    def has_refer(self) -> bool:
        return bool(self.refers)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "hard_fails": list(self.hard_fails),
            "refers": list(self.refers),
            "rationale": list(self.rationale),
            "rationale_by_code": dict(self.rationale_by_code),
            "evaluated_rules": list(self.evaluated_rules),
        }


def _get(application, key: str, default: Any = None) -> Any:
    """Support both dict-style and attribute-style access uniformly."""
    if isinstance(application, dict):
        return application.get(key, default)
    return getattr(application, key, default)


def _f(value, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Individual rule checks. Each returns (code, rationale_line) on hit, or None.
# Keeping them as small functions makes them trivially unit-testable and
# easy for reviewers to map to the AU lending policy source they codify.
# ---------------------------------------------------------------------------

def _p01_visa_ineligible(application) -> tuple | None:
    """P01: Non-resident / bridging visa → hard-fail.

    Falls back to "not evaluable" if the application has no visa field;
    typical of the current synthetic-data schema but real production data
    would populate this from the identity-verification provider.
    """
    visa = _get(application, "visa_status") or _get(application, "residency_status")
    if visa is None:
        return None  # not evaluable → skip
    ineligible = {"bridging", "student", "working_holiday", "tourist", "visitor"}
    if str(visa).lower() in ineligible:
        return ("P01", f"Visa status '{visa}' not eligible for unsecured/secured lending under bank policy")
    return None


def _p02_age_ineligible(application) -> tuple | None:
    """P02: Age < 18 or > 75 at loan maturity → hard-fail.

    Not evaluable without a DOB; returns None when DOB is missing. When
    present, the check runs against the assumed-date-of-scoring (today)
    plus loan_term_months at maturity.
    """
    dob = _get(application, "date_of_birth")
    if dob is None:
        return None
    try:
        from datetime import date
        today = date.today()
        years_old = (today - dob).days / 365.25 if hasattr(dob, "year") else None
        if years_old is None:
            return None
        term_months = _f(_get(application, "loan_term_months", 0))
        age_at_maturity = years_old + (term_months / 12.0)
        if years_old < 18:
            return ("P02", f"Applicant under 18 (age {years_old:.1f}) — cannot contract for credit")
        if age_at_maturity > 75:
            return ("P02", f"Age at maturity {age_at_maturity:.1f} exceeds 75-year responsible-lending ceiling")
        return None
    except Exception:
        return None


def _p03_bankruptcy(application) -> tuple | None:
    if bool(_get(application, "has_bankruptcy", False)):
        return ("P03", "Undischarged bankrupt or within 7-year bankruptcy window")
    return None


def _p04_active_ato_debt(application) -> tuple | None:
    """P04: Active ATO tax debt flag → hard-fail.

    Requires an `has_ato_debt_default` or similar flag; not currently in
    the LoanApplication schema so evaluates to None when absent. Retained
    as a documented policy slot so the production integration of Equifax
    CCR + ATO default feed (expected 2026) drops in without a migration.
    """
    ato_debt = _get(application, "has_ato_debt_default")
    if ato_debt is None:
        return None
    if bool(ato_debt):
        return ("P04", "Active ATO tax-debt default — AU lender policy universally hard-fails")
    return None


def _p05_credit_score_floor(application) -> tuple | None:
    score = _f(_get(application, "credit_score"), default=None) if _get(application, "credit_score") is not None else None
    if score is None:
        return None
    if score < MIN_CREDIT_SCORE:
        return (
            "P05",
            f"Credit score {score:.0f} below minimum floor {MIN_CREDIT_SCORE} — "
            "applications this low require manual underwriting and are outside AA-approval scope",
        )
    return None


def _p06_lvr_ceiling(application) -> tuple | None:
    property_value = _f(_get(application, "property_value", 0))
    loan_amount = _f(_get(application, "loan_amount", 0))
    purpose = _get(application, "purpose")

    if property_value <= 0 or purpose not in ("home", "investment"):
        return None

    lvr = loan_amount / property_value
    if lvr >= MAX_LVR_ANY:
        return (
            "P06",
            f"LVR {lvr:.1%} at or above 100% — loan would be in immediate negative equity",
        )
    if lvr > MAX_LVR_HOME and purpose == "home":
        return (
            "P06",
            f"LVR {lvr:.1%} exceeds 95% policy ceiling for owner-occupier; outside LMI provider appetite",
        )
    return None


def _p07_dti_ceiling(application) -> tuple | None:
    dti = _f(_get(application, "debt_to_income"))
    if dti > MAX_DTI:
        return (
            "P07",
            f"DTI {dti:.1f}× exceeds APRA intervention ceiling of {MAX_DTI:.1f}×",
        )
    return None


def _p08_lti_refer(application) -> tuple | None:
    annual_income = _f(_get(application, "annual_income"))
    loan_amount = _f(_get(application, "loan_amount"))
    if annual_income <= 0:
        return None
    lti = loan_amount / annual_income
    if lti > REFER_LTI:
        return (
            "P08",
            f"Loan-to-income {lti:.1f}× above {REFER_LTI:.0f}× refer threshold — manual review",
        )
    return None


def _p09_high_risk_postcode_refer(application) -> tuple | None:
    rate = _f(_get(application, "postcode_default_rate"))
    if rate > 0.08:  # 8% historical default rate → refer
        return (
            "P09",
            f"Postcode default rate {rate:.1%} above 8% — geographic concentration risk requires review",
        )
    return None


def _p10_self_employed_short_history_refer(application) -> tuple | None:
    employment_type = _get(application, "employment_type")
    if employment_type != "self_employed":
        return None
    # Treat employment_length as years; convert to months.
    years = _f(_get(application, "employment_length"))
    months = years * 12
    if months < MIN_EMP_TENURE_MONTHS_SE:
        return (
            "P10",
            f"Self-employed with {months:.0f} months trading history "
            f"(< {MIN_EMP_TENURE_MONTHS_SE} months required) — manual underwriting",
        )
    return None


def _p11_hardship_history_refer(application) -> tuple | None:
    flags = _f(_get(application, "num_hardship_flags"))
    if flags > 0:
        return (
            "P11",
            f"{int(flags)} hardship flag(s) on file — AFCA 2023 guidance requires human review",
        )
    return None


def _p12_tmd_mismatch_refer(application) -> tuple | None:
    """P12: TMD / Target Market Determination mismatch refer.

    Personal-loan TMD typically caps at $50k; unsecured over $50k is refer
    territory for most AU challengers. Home-loan TMD is self-selecting by
    the product definition and handled elsewhere.
    """
    purpose = _get(application, "purpose")
    loan_amount = _f(_get(application, "loan_amount"))
    if purpose == "personal" and loan_amount > 50_000:
        return (
            "P12",
            f"Personal loan ${loan_amount:,.0f} exceeds $50k TMD band — refer to TMD-aware underwriting",
        )
    return None


_HARD_FAIL_RULES = [
    _p01_visa_ineligible,
    _p02_age_ineligible,
    _p03_bankruptcy,
    _p04_active_ato_debt,
    _p05_credit_score_floor,
    _p06_lvr_ceiling,
    _p07_dti_ceiling,
]

_REFER_RULES = [
    _p08_lti_refer,
    _p09_high_risk_postcode_refer,
    _p10_self_employed_short_history_refer,
    _p11_hardship_history_refer,
    _p12_tmd_mismatch_refer,
]


# ---------------------------------------------------------------------------
# Declarative catalogue (used by the MRM dossier and admin UI).
# Keeping this declarative block beside the rule functions keeps the
# code / severity / one-line description in one place without coupling
# the runtime evaluation to docstring parsing.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PolicyRuleSpec:
    code: str
    severity: str  # "hard_fail" or "refer"
    description: str


POLICY_RULES: list[PolicyRuleSpec] = [
    PolicyRuleSpec("P01", "hard_fail", "Non-resident / ineligible visa (bridging/student/tourist) — decline"),
    PolicyRuleSpec("P02", "hard_fail", "Applicant age < 18 or age at maturity > 75"),
    PolicyRuleSpec("P03", "hard_fail", "Undischarged bankruptcy or within 7yr window — decline"),
    PolicyRuleSpec("P04", "hard_fail", "Active ATO tax-debt default flag — decline"),
    PolicyRuleSpec("P05", "hard_fail", f"Credit score below floor {MIN_CREDIT_SCORE} — decline"),
    PolicyRuleSpec(
        "P06",
        "hard_fail",
        f"LVR > {MAX_LVR_HOME:.0%} owner-occupier or ≥ {MAX_LVR_ANY:.0%} any — decline",
    ),
    PolicyRuleSpec("P07", "hard_fail", f"DTI exceeds APRA intervention ceiling {MAX_DTI:.1f}× — decline"),
    PolicyRuleSpec("P08", "refer", f"LTI > {REFER_LTI:.0f}× — refer to manual underwriting"),
    PolicyRuleSpec("P09", "refer", "Postcode default rate > 8% — geographic concentration review"),
    PolicyRuleSpec(
        "P10",
        "refer",
        f"Self-employed with < {MIN_EMP_TENURE_MONTHS_SE}mo trading history — refer",
    ),
    PolicyRuleSpec("P11", "refer", "Hardship flag(s) on file — AFCA 2023 mandates human review"),
    PolicyRuleSpec("P12", "refer", "Personal loan > $50k TMD band — refer to TMD-aware underwriting"),
]


def evaluate(application) -> PolicyResult:
    """Run the full overlay against one application and return a PolicyResult.

    All rules always run (even if the mode is `off`) so the result can be
    logged for analysis; only the *effect* on the final decision depends on
    the mode. The caller decides whether to honour hard_fails / refers.
    """
    result = PolicyResult()

    for rule in _HARD_FAIL_RULES:
        hit = rule(application)
        result.evaluated_rules.append(rule.__name__)
        if hit is not None:
            code, rationale = hit
            result.hard_fails.append(code)
            result.rationale.append(f"{code} (hard-fail): {rationale}")
            result.rationale_by_code[code] = rationale

    for rule in _REFER_RULES:
        hit = rule(application)
        result.evaluated_rules.append(rule.__name__)
        if hit is not None:
            code, rationale = hit
            result.refers.append(code)
            result.rationale.append(f"{code} (refer): {rationale}")
            result.rationale_by_code[code] = rationale

    return result


def current_mode() -> str:
    """Read the active overlay mode from settings or the environment.

    Settings wins if defined (so Django config is authoritative); otherwise
    the raw env var is used. Unknown values collapse to `shadow` so a
    misconfigured deployment never silently downgrades safety.
    """
    try:
        from django.conf import settings

        mode = getattr(settings, "CREDIT_POLICY_OVERLAY_MODE", None)
    except Exception:
        mode = None
    if not mode:
        mode = os.environ.get(OVERLAY_MODE_ENV, OVERLAY_MODE_SHADOW)
    mode = (mode or OVERLAY_MODE_SHADOW).lower()
    if mode not in OVERLAY_MODES:
        logger.warning(
            "Unknown CREDIT_POLICY_OVERLAY_MODE=%r — defaulting to '%s'", mode, OVERLAY_MODE_SHADOW
        )
        return OVERLAY_MODE_SHADOW
    return mode


def apply_overlay_to_decision(decision: str, result: PolicyResult, mode: str) -> str:
    """Transform the model decision according to the overlay mode + result.

    Returns the resulting decision label. In `off` or `shadow` modes the
    input decision is returned unchanged — shadow mode relies on the
    caller to attach `result.to_dict()` to the response so the log captures
    what *would* have happened under enforce.
    """
    if mode != OVERLAY_MODE_ENFORCE:
        return decision
    if result.has_hard_fail:
        return "denied"
    if result.has_refer and decision == "approved":
        # Approve-path with refer rules hit → route to human review instead.
        return "review"
    return decision
