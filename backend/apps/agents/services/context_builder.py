import logging

logger = logging.getLogger("agents.orchestrator")


class ApplicationContextBuilder:
    """Builds profile context and evaluates conditions from application data."""

    def build_profile_context(self, application):
        try:
            profile = application.applicant.profile
        except AttributeError:  # RelatedObjectDoesNotExist is a subclass
            logger.info("Application %s: no customer profile available", application.pk)
            return None

        return {
            "savings_balance": getattr(profile, "savings_balance", None),
            "checking_balance": getattr(profile, "checking_balance", None),
            "account_tenure_years": getattr(profile, "account_tenure_years", None),
            "loyalty_tier": profile.get_loyalty_tier_display()
            if hasattr(profile, "get_loyalty_tier_display")
            else None,
            "num_products": getattr(profile, "num_products", None),
            "on_time_payment_pct": getattr(profile, "on_time_payment_pct", None),
            "previous_loans_repaid": getattr(profile, "previous_loans_repaid", None),
            "has_credit_card": getattr(profile, "has_credit_card", None),
            "has_mortgage": getattr(profile, "has_mortgage", None),
            "has_auto_loan": getattr(profile, "has_auto_loan", None),
            "gross_annual_income": profile.gross_annual_income_decimal
            if hasattr(profile, "gross_annual_income_decimal")
            else getattr(profile, "gross_annual_income", None),
            "superannuation_balance": getattr(profile, "superannuation_balance", None),
            "total_assets": profile.total_assets if hasattr(profile, "total_assets") else None,
            "total_monthly_liabilities": profile.total_monthly_liabilities
            if hasattr(profile, "total_monthly_liabilities")
            else None,
            "employment_status": getattr(profile, "employment_status", ""),
            "occupation": getattr(profile, "occupation", ""),
            "industry": getattr(profile, "industry", ""),
        }

    @staticmethod
    def evaluate_conditions(application) -> list:
        """Return condition dicts for risk factors that require documentation before finalising."""
        conditions: list[dict] = []

        # Income verification gap
        gap = getattr(application, "income_verification_gap", None)
        if gap is not None and gap > 0.15:
            conditions.append(
                {
                    "type": "income_verification",
                    "description": (
                        "We need additional documentation to verify your income before we can finalise your loan."
                    ),
                    "required": True,
                    "satisfied": False,
                    "satisfied_at": None,
                }
            )

        # Self-employed with short tenure
        if application.employment_type == "self_employed" and application.employment_length < 2:
            conditions.append(
                {
                    "type": "employment_verification",
                    "description": (
                        "As you are self-employed, we need your most recent business financials and tax returns to finalise your loan."
                    ),
                    "required": True,
                    "satisfied": False,
                    "satisfied_at": None,
                }
            )

        # Home purchase without property valuation
        if application.purpose == "home" and application.property_value is None:
            conditions.append(
                {
                    "type": "valuation_required",
                    "description": (
                        "Home loan requires an independent property valuation. "
                        "A certified valuation report must be provided."
                    ),
                    "required": True,
                    "satisfied": False,
                    "satisfied_at": None,
                }
            )

        # Large loan without cosigner and modest income
        loan_amount = float(application.loan_amount)
        annual_income = float(application.annual_income)
        if loan_amount > 500_000 and not application.has_cosigner and annual_income < 100_000:
            conditions.append(
                {
                    "type": "guarantor_needed",
                    "description": (
                        "Based on the loan amount and your current income, a guarantor or co-signer is required to proceed."
                    ),
                    "required": True,
                    "satisfied": False,
                    "satisfied_at": None,
                }
            )

        return conditions
