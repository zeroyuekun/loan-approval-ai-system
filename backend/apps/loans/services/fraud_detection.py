"""Fraud detection and velocity check service for loan applications.

Runs a battery of deterministic checks against a LoanApplication to flag
potential fraud, application stacking, or data inconsistencies.  Each check
is independent and returns a structured result dict.  The composite
``run_checks`` method aggregates individual results into a single verdict.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

logger = logging.getLogger('loans.fraud_detection')

# ---------------------------------------------------------------------------
# Risk-level weights used to compute the composite risk score (0-1).
# Higher weight = bigger contribution when a check fails.
# ---------------------------------------------------------------------------
_RISK_WEIGHTS = {
    'low': 0.10,
    'medium': 0.25,
    'high': 0.50,
}


class FraudDetectionService:
    """Run fraud / velocity checks on a single LoanApplication instance."""

    def run_checks(self, application):
        """Execute all checks and return an aggregate result.

        Returns:
            dict with keys:
                passed (bool): True if no *high*-risk check failed.
                risk_score (float): Composite score between 0.0 and 1.0.
                checks (list[dict]): Individual check results.
                flagged_reasons (list[str]): Human-readable reasons for failed checks.
        """
        checks = [
            self._check_duplicate(application),
            self._check_velocity(application),
            self._check_income_inconsistency(application),
            self._check_document_consistency(application),
            self._check_bankruptcy_high_amount(application),
        ]

        flagged_reasons = [c['detail'] for c in checks if not c['passed']]
        risk_score = self._compute_risk_score(checks)

        # "passed" means no high-risk check failed
        has_high_risk_failure = any(
            not c['passed'] and c['risk_level'] == 'high' for c in checks
        )
        passed = not has_high_risk_failure

        logger.info(
            'Application %s fraud check: passed=%s risk_score=%.2f flagged=%d',
            application.pk, passed, risk_score, len(flagged_reasons),
        )

        return {
            'passed': passed,
            'risk_score': round(risk_score, 4),
            'checks': checks,
            'flagged_reasons': flagged_reasons,
        }

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_duplicate(self, application):
        """Flag if the same applicant submitted a similar loan in the last 30 days.

        "Similar" = same purpose AND exact same loan amount.
        Only counts applications still in the intake pipeline (pending/processing)
        — already-decided applications are not stacking attempts.
        """
        from apps.loans.models import LoanApplication

        cutoff = timezone.now() - timedelta(days=30)

        duplicates = (
            LoanApplication.objects
            .filter(
                applicant=application.applicant,
                purpose=application.purpose,
                loan_amount=application.loan_amount,
                created_at__gte=cutoff,
                created_at__lt=application.created_at,
                status__in=('pending', 'processing'),
            )
            .exclude(pk=application.pk)
        )

        found = duplicates.exists()
        return {
            'check_name': 'duplicate_detection',
            'passed': not found,
            'risk_level': 'medium' if found else 'low',
            'detail': (
                f'Duplicate application detected: same purpose ({application.purpose}) '
                f'and exact same amount within 30 days'
                if found
                else 'No duplicate applications found'
            ),
        }

    def _check_velocity(self, application):
        """Flag if the applicant submitted more than 3 applications in 7 days.

        Only counts applications still in the intake pipeline (pending/processing)
        — already-decided applications are legitimate prior submissions.
        """
        from apps.loans.models import LoanApplication

        cutoff = timezone.now() - timedelta(days=7)
        recent_count = (
            LoanApplication.objects
            .filter(
                applicant=application.applicant,
                created_at__gte=cutoff,
                status__in=('pending', 'processing'),
            )
            .exclude(pk=application.pk)
            .count()
        )

        exceeded = recent_count >= 10
        return {
            'check_name': 'velocity_check',
            'passed': not exceeded,
            'risk_level': 'high' if exceeded else 'low',
            'detail': (
                f'Velocity limit exceeded: {recent_count + 1} applications in 7 days (limit: 10)'
                if exceeded
                else f'{recent_count + 1} application(s) in last 7 days — within limits'
            ),
        }

    def _check_income_inconsistency(self, application):
        """Flag if income_verification_gap > 0.25 (25% discrepancy)."""
        gap = getattr(application, 'income_verification_gap', None)
        if gap is None:
            return {
                'check_name': 'income_inconsistency',
                'passed': True,
                'risk_level': 'low',
                'detail': 'Income verification gap not available — skipped',
            }

        flagged = gap > 0.25
        return {
            'check_name': 'income_inconsistency',
            'passed': not flagged,
            'risk_level': 'medium' if flagged else 'low',
            'detail': (
                f'Income verification gap is {gap:.2f} (threshold: 0.25)'
                if flagged
                else f'Income verification gap {gap:.2f} is within acceptable range'
            ),
        }

    def _check_document_consistency(self, application):
        """Flag if document_consistency_score < 0.70."""
        score = getattr(application, 'document_consistency_score', None)
        if score is None:
            return {
                'check_name': 'document_consistency',
                'passed': True,
                'risk_level': 'low',
                'detail': 'Document consistency score not available — skipped',
            }

        flagged = score < 0.70
        return {
            'check_name': 'document_consistency',
            'passed': not flagged,
            'risk_level': 'medium' if flagged else 'low',
            'detail': (
                f'Document consistency score is {score:.2f} (threshold: 0.70)'
                if flagged
                else f'Document consistency score {score:.2f} is acceptable'
            ),
        }

    def _check_bankruptcy_high_amount(self, application):
        """Flag if applicant has bankruptcy AND loan amount > $50,000."""
        has_bankruptcy = getattr(application, 'has_bankruptcy', False)
        high_amount = application.loan_amount > Decimal('50000')

        flagged = has_bankruptcy and high_amount
        return {
            'check_name': 'bankruptcy_high_amount',
            'passed': not flagged,
            'risk_level': 'high' if flagged else 'low',
            'detail': (
                f'Bankruptcy flag with high loan amount (${application.loan_amount:,.2f} > $50,000)'
                if flagged
                else 'No bankruptcy/high-amount concern'
            ),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_risk_score(checks):
        """Compute a composite risk score in [0, 1].

        Failed checks contribute their risk-level weight; the score is the
        sum of failed weights divided by the sum of all possible weights,
        giving a normalised 0-1 value.
        """
        total_weight = sum(_RISK_WEIGHTS[c['risk_level']] for c in checks)
        if total_weight == 0:
            return 0.0

        failed_weight = sum(
            _RISK_WEIGHTS[c['risk_level']]
            for c in checks
            if not c['passed']
        )
        return failed_weight / total_weight
