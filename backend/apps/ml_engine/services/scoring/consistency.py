"""Cross-validation checks for loan application data consistency.

These checks catch logically inconsistent combinations of features that
individually pass bounds validation but together don't make sense.
Each check returns a dict with the field(s) involved, severity, and
a human-readable explanation.

Severity levels:
  - error:   Almost certainly wrong data. Block prediction.
  - warning: Suspicious but possible. Flag for review, allow prediction.
"""

import math


def _safe_float(val, default=0.0):
    try:
        v = float(val)
        return default if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ValueError):
        return default


class DataConsistencyChecker:
    """Cross-validates relationships between loan application features."""

    def check_all(self, features: dict) -> dict:
        """Run all consistency checks and return a summary.

        Args:
            features: dict of application feature values (matches the
                      keys used by ModelPredictor.predict).

        Returns:
            {
                'consistent': bool,       # True if no errors
                'errors': [...],          # severity='error' findings
                'warnings': [...],        # severity='warning' findings
            }
        """
        findings = []
        findings.extend(self._check_home_loan_property(features))
        findings.extend(self._check_deposit_vs_property(features))
        findings.extend(self._check_deposit_vs_loan(features))
        findings.extend(self._check_lvr_sanity(features))
        findings.extend(self._check_dti_sanity(features))
        findings.extend(self._check_expenses_vs_income(features))
        findings.extend(self._check_credit_card_vs_income(features))
        findings.extend(self._check_employment_consistency(features))
        findings.extend(self._check_bankruptcy_vs_credit(features))
        findings.extend(self._check_loan_amount_vs_income(features))
        findings.extend(self._check_couple_income(features))

        errors = [f for f in findings if f["severity"] == "error"]
        warnings = [f for f in findings if f["severity"] == "warning"]

        return {
            "consistent": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_home_loan_property(self, f):
        if f.get("purpose") != "home":
            return []
        prop = _safe_float(f.get("property_value"))
        if prop <= 0:
            return [
                {
                    "fields": ["purpose", "property_value"],
                    "severity": "error",
                    "message": (
                        "Home loan application has no property value. A property value is required for LVR calculation."
                    ),
                }
            ]
        return []

    def _check_deposit_vs_property(self, f):
        if f.get("purpose") != "home":
            return []
        deposit = _safe_float(f.get("deposit_amount"))
        prop = _safe_float(f.get("property_value"))
        if deposit > 0 and prop > 0 and deposit > prop:
            return [
                {
                    "fields": ["deposit_amount", "property_value"],
                    "severity": "error",
                    "message": (
                        f"Deposit (${deposit:,.0f}) exceeds property value "
                        f"(${prop:,.0f}). Deposit cannot be greater than the "
                        f"property purchase price."
                    ),
                }
            ]
        return []

    def _check_deposit_vs_loan(self, f):
        deposit = _safe_float(f.get("deposit_amount"))
        loan = _safe_float(f.get("loan_amount"))
        if deposit > 0 and loan > 0 and deposit > loan * 1.5:
            return [
                {
                    "fields": ["deposit_amount", "loan_amount"],
                    "severity": "warning",
                    "message": (
                        f"Deposit (${deposit:,.0f}) is significantly larger than "
                        f"the loan amount (${loan:,.0f}). This is unusual; verify "
                        f"the figures are correct."
                    ),
                }
            ]
        return []

    def _check_lvr_sanity(self, f):
        if f.get("purpose") != "home":
            return []
        loan = _safe_float(f.get("loan_amount"))
        prop = _safe_float(f.get("property_value"))
        if prop <= 0 or loan <= 0:
            return []
        lvr = loan / prop
        if lvr > 1.0:
            return [
                {
                    "fields": ["loan_amount", "property_value"],
                    "severity": "error",
                    "message": (
                        f"Loan amount (${loan:,.0f}) exceeds property value "
                        f"(${prop:,.0f}), giving an LVR of {lvr:.0%}. "
                        f"Loan cannot exceed the property purchase price."
                    ),
                }
            ]
        return []

    def _check_dti_sanity(self, f):
        income = _safe_float(f.get("annual_income"))
        loan = _safe_float(f.get("loan_amount"))
        declared_dti = _safe_float(f.get("debt_to_income"))
        if income <= 0 or loan <= 0:
            return []
        # The new-loan component of DTI should be at least loan/income
        min_expected_dti = loan / income
        # Allow generous margin for existing debt not being itemised
        if declared_dti > 0 and declared_dti < min_expected_dti * 0.5:
            return [
                {
                    "fields": ["debt_to_income", "loan_amount", "annual_income"],
                    "severity": "warning",
                    "message": (
                        f"Declared DTI ({declared_dti:.2f}x) appears low relative "
                        f"to loan-to-income ratio ({min_expected_dti:.2f}x). "
                        f"The DTI should include both existing and new debt."
                    ),
                }
            ]
        return []

    def _check_expenses_vs_income(self, f):
        income = _safe_float(f.get("annual_income"))
        expenses = _safe_float(f.get("monthly_expenses"))
        if income <= 0 or expenses <= 0:
            return []
        monthly_income = income / 12
        findings = []

        # Expenses less than 15% of monthly income is suspiciously low
        if expenses < monthly_income * 0.15:
            findings.append(
                {
                    "fields": ["monthly_expenses", "annual_income"],
                    "severity": "warning",
                    "message": (
                        f"Declared monthly expenses (${expenses:,.0f}) are only "
                        f"{expenses / monthly_income:.0%} of monthly income "
                        f"(${monthly_income:,.0f}). Banks will apply the higher "
                        f"of declared expenses or the HEM benchmark."
                    ),
                }
            )

        # Expenses exceeding 90% of monthly income with a loan request
        if expenses > monthly_income * 0.90:
            findings.append(
                {
                    "fields": ["monthly_expenses", "annual_income"],
                    "severity": "warning",
                    "message": (
                        f"Declared monthly expenses (${expenses:,.0f}) consume "
                        f"{expenses / monthly_income:.0%} of monthly income. "
                        f"Very little surplus remains for loan repayments."
                    ),
                }
            )

        return findings

    def _check_credit_card_vs_income(self, f):
        income = _safe_float(f.get("annual_income"))
        cc_limit = _safe_float(f.get("existing_credit_card_limit"))
        if income <= 0 or cc_limit <= 0:
            return []
        if cc_limit > income * 0.8:
            return [
                {
                    "fields": ["existing_credit_card_limit", "annual_income"],
                    "severity": "warning",
                    "message": (
                        f"Total credit card limit (${cc_limit:,.0f}) exceeds "
                        f"80% of annual income (${income:,.0f}). Banks assess "
                        f"3% of the total limit as a monthly commitment "
                        f"regardless of the actual balance."
                    ),
                }
            ]
        return []

    def _check_employment_consistency(self, f):
        emp_type = f.get("employment_type", "")
        emp_length = _safe_float(f.get("employment_length"))
        findings = []

        # Casual with very long tenure is unusual
        if emp_type == "payg_casual" and emp_length > 10:
            findings.append(
                {
                    "fields": ["employment_type", "employment_length"],
                    "severity": "warning",
                    "message": (
                        f"Casual employment for {int(emp_length)} years is unusual. "
                        f"Verify this is not actually permanent part-time or "
                        f"full-time employment."
                    ),
                }
            )

        # Contract worker with very long tenure at the same role
        if emp_type == "contract" and emp_length > 15:
            findings.append(
                {
                    "fields": ["employment_type", "employment_length"],
                    "severity": "warning",
                    "message": (
                        f"Contract employment for {int(emp_length)} years is unusual. "
                        f"This may actually be permanent employment."
                    ),
                }
            )

        return findings

    def _check_bankruptcy_vs_credit(self, f):
        """Bankruptcy with a high credit score is contradictory.

        In Australia, a discharged bankrupt (5-7 years post-discharge) can
        rebuild their score to 550-650. Scores above 700 with a bankruptcy
        flag are almost certainly data errors. Scores 600-700 are suspicious
        but possible for late-stage discharged bankrupts, so we warn rather
        than block.
        """
        has_bankruptcy = f.get("has_bankruptcy")
        credit = _safe_float(f.get("credit_score"))
        if not has_bankruptcy:
            return []
        if credit > 700:
            return [
                {
                    "fields": ["has_bankruptcy", "credit_score"],
                    "severity": "error",
                    "message": (
                        f"Applicant declares bankruptcy but has a credit score "
                        f"of {int(credit)}. An undischarged bankrupt or someone "
                        f"within 7 years of discharge would not have a score "
                        f"above 700. Verify the bankruptcy declaration."
                    ),
                }
            ]
        if credit > 600:
            return [
                {
                    "fields": ["has_bankruptcy", "credit_score"],
                    "severity": "warning",
                    "message": (
                        f"Applicant declares bankruptcy with a credit score of "
                        f"{int(credit)}. This is possible for a late-stage "
                        f"discharged bankrupt (6-7 years) but unusual. "
                        f"Verify the bankruptcy status and discharge date."
                    ),
                }
            ]
        return []

    def _check_loan_amount_vs_income(self, f):
        purpose = f.get("purpose", "")
        income = _safe_float(f.get("annual_income"))
        loan = _safe_float(f.get("loan_amount"))
        if income <= 0 or loan <= 0:
            return []
        ratio = loan / income
        # Home loans can go up to 4.5x; non-home loans above 3x are odd
        if purpose != "home" and ratio > 3.0:
            return [
                {
                    "fields": ["loan_amount", "annual_income", "purpose"],
                    "severity": "warning",
                    "message": (
                        f"{purpose.title()} loan of ${loan:,.0f} is {ratio:.1f}x "
                        f"annual income (${income:,.0f}). Non-home-loan borrowing "
                        f"above 3x income is unusual. Verify the loan amount and "
                        f"purpose are correct."
                    ),
                }
            ]
        return []

    def _check_couple_income(self, f):
        applicant_type = f.get("applicant_type", "")
        income = _safe_float(f.get("annual_income"))
        if applicant_type == "couple" and 0 < income < 45000:
            return [
                {
                    "fields": ["applicant_type", "annual_income"],
                    "severity": "warning",
                    "message": (
                        f"Couple application with combined income of "
                        f"${income:,.0f} is very low. Verify whether this is "
                        f"combined household income or a single earner."
                    ),
                }
            ]
        return []
