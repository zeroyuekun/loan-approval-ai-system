"""Age-at-loan-maturity eligibility gate.

Policy: deny if the applicant would be older than 67 at the end of the loan.
Source: Alex Bank published rule (see docs/research/2026-04-14-au-lending-research.md).
"""
import datetime
from dataclasses import dataclass


AGE_AT_MATURITY_LIMIT_YEARS = 67


@dataclass(frozen=True)
class EligibilityResult:
    passed: bool
    reason_code: str | None = None
    detail: str | None = None


class EligibilityChecker:
    """Pure, stateless policy gate. No DB writes, no side effects."""

    def check(self, application) -> EligibilityResult:
        dob = self._dob(application)
        if dob is None:
            return EligibilityResult(passed=True)

        today = datetime.date.today()
        current_age_years = self._years_between(dob, today)
        term_years = (application.loan_term_months or 0) / 12.0
        age_at_maturity = current_age_years + term_years

        if age_at_maturity > AGE_AT_MATURITY_LIMIT_YEARS:
            return EligibilityResult(
                passed=False,
                reason_code="R71",
                detail=(
                    f"Applicant would be {age_at_maturity:.1f} years old at loan "
                    f"maturity; policy limit is {AGE_AT_MATURITY_LIMIT_YEARS}."
                ),
            )
        return EligibilityResult(passed=True)

    @staticmethod
    def _dob(application) -> datetime.date | None:
        applicant = getattr(application, "applicant", None)
        profile = getattr(applicant, "profile", None) if applicant is not None else None
        if profile is None:
            return None
        return getattr(profile, "date_of_birth_date", None)

    @staticmethod
    def _years_between(start: datetime.date, end: datetime.date) -> float:
        delta_days = (end - start).days
        return delta_days / 365.25
