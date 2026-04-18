"""Policy-variable recomputation for LVR-driven fields.

When a caller mutates an application's `loan_amount` or `property_value`
(e.g. via a stress scenario or counterfactual), the downstream LMI and
effective_loan_amount fields must be recomputed so the model sees policy
variables consistent with the new LVR — otherwise the scorer gets stale
inputs that no longer correspond to the stressed scenario.

Extracted from `predictor.py` (Arm C Phase 1) so the predictor orchestrator
stays focused on model invocation rather than LMI arithmetic.
"""

from __future__ import annotations

__all__ = ["recompute_lvr_driven_policy_vars"]


def recompute_lvr_driven_policy_vars(row):
    """Re-derive LVR-driven LMI features after mutating property_value or loan_amount.

    Policy variables (lmi_premium, effective_loan_amount) are a function of
    LVR, so whenever property_value or loan_amount is perturbed (e.g. by a
    stress scenario or counterfactual) the downstream fields must be
    recomputed. Otherwise the model sees stale policy vars that no longer
    correspond to the stressed LVR.

    Schedule (mirrors the generator/underwriter tables):
      - LVR ≤ 0.80         : no LMI
      - 0.80 < LVR ≤ 0.85  : 1%
      - 0.85 < LVR ≤ 0.90  : 2%
      - LVR > 0.90         : 3%

    LMI applies only to purpose in {home, investment}; personal loans are
    always charged 0%.

    Mutates `row` in place. Returns None.
    """
    property_value = float(row.get("property_value", 0.0) or 0.0)
    loan_amount = float(row.get("loan_amount", 0.0) or 0.0)
    lvr = (loan_amount / property_value) if property_value > 0 else 0.0

    if lvr > 0.90:
        rate = 0.03
    elif lvr > 0.85:
        rate = 0.02
    elif lvr > 0.80:
        rate = 0.01
    else:
        rate = 0.0

    is_home = row.get("purpose") in ("home", "investment")
    row["lmi_premium"] = round(loan_amount * rate * (1 if is_home else 0), 2)
    row["effective_loan_amount"] = round(loan_amount + row["lmi_premium"], 2)
