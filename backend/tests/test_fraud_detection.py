"""Tests for the FraudDetectionService — individual checks and composite result."""

from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.accounts.models import CustomUser
from apps.loans.models import FraudCheck, LoanApplication
from apps.loans.services.fraud_detection import FraudDetectionService


def _create_user(username="testuser", **kwargs):
    defaults = {
        "password": "TestPass123!",
        "email": f"{username}@example.com",
        "role": "customer",
    }
    defaults.update(kwargs)
    return CustomUser.objects.create_user(username=username, **defaults)


def _create_application(user, **overrides):
    defaults = {
        "applicant": user,
        "annual_income": Decimal("85000.00"),
        "credit_score": 750,
        "loan_amount": Decimal("350000.00"),
        "loan_term_months": 360,
        "debt_to_income": Decimal("4.12"),
        "employment_length": 5,
        "purpose": "home",
        "home_ownership": "mortgage",
        "employment_type": "payg_permanent",
        "applicant_type": "single",
        "state": "NSW",
    }
    defaults.update(overrides)
    return LoanApplication.objects.create(**defaults)


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    FIELD_ENCRYPTION_KEY="Q1bXXPr1cYO3Cjd7uP5J8nWRxzdBjQrTAosMayGV3CA=",
)
class FraudDetectionServiceTest(TestCase):
    """Test each fraud check individually and the composite run_checks method."""

    def setUp(self):
        cache.clear()
        from apps.accounts.models import _get_fernet

        _get_fernet.cache_clear()
        self.user = _create_user()
        self.service = FraudDetectionService()

    # ------------------------------------------------------------------
    # Duplicate detection
    # ------------------------------------------------------------------

    def test_duplicate_detection_passes_no_prior(self):
        app = _create_application(self.user)
        result = self.service._check_duplicate(app)
        self.assertTrue(result["passed"])
        self.assertEqual(result["risk_level"], "low")

    def test_duplicate_detection_flags_similar_app(self):
        """Same purpose, amount within 10%, within 30 days."""
        _create_application(self.user, loan_amount=Decimal("345000.00"), purpose="home")
        app = _create_application(self.user, loan_amount=Decimal("350000.00"), purpose="home")
        result = self.service._check_duplicate(app)
        self.assertFalse(result["passed"])
        self.assertEqual(result["risk_level"], "high")

    def test_duplicate_detection_passes_different_purpose(self):
        _create_application(self.user, loan_amount=Decimal("350000.00"), purpose="auto")
        app = _create_application(self.user, loan_amount=Decimal("350000.00"), purpose="home")
        result = self.service._check_duplicate(app)
        self.assertTrue(result["passed"])

    def test_duplicate_detection_passes_amount_outside_range(self):
        """Amount difference > 10% should not flag."""
        _create_application(self.user, loan_amount=Decimal("200000.00"), purpose="home")
        app = _create_application(self.user, loan_amount=Decimal("350000.00"), purpose="home")
        result = self.service._check_duplicate(app)
        self.assertTrue(result["passed"])

    # ------------------------------------------------------------------
    # Velocity check
    # ------------------------------------------------------------------

    def test_velocity_passes_under_limit(self):
        _create_application(self.user)
        _create_application(self.user)
        app = _create_application(self.user)
        result = self.service._check_velocity(app)
        # 3 total (2 prior + current) — limit is >3 in 7 days
        self.assertTrue(result["passed"])

    def test_velocity_flags_over_limit(self):
        for _ in range(3):
            _create_application(self.user)
        app = _create_application(self.user)
        result = self.service._check_velocity(app)
        # 4 total (3 prior + current excluded but count is 3 prior >= 3)
        self.assertFalse(result["passed"])
        self.assertEqual(result["risk_level"], "high")

    # ------------------------------------------------------------------
    # Income inconsistency
    # ------------------------------------------------------------------

    def test_income_inconsistency_skips_when_null(self):
        app = _create_application(self.user, income_verification_gap=None)
        result = self.service._check_income_inconsistency(app)
        self.assertTrue(result["passed"])
        self.assertIn("skipped", result["detail"])

    def test_income_inconsistency_passes_low_gap(self):
        app = _create_application(self.user, income_verification_gap=0.10)
        result = self.service._check_income_inconsistency(app)
        self.assertTrue(result["passed"])

    def test_income_inconsistency_flags_high_gap(self):
        app = _create_application(self.user, income_verification_gap=0.40)
        result = self.service._check_income_inconsistency(app)
        self.assertFalse(result["passed"])
        self.assertEqual(result["risk_level"], "medium")

    # ------------------------------------------------------------------
    # Document consistency
    # ------------------------------------------------------------------

    def test_document_consistency_skips_when_null(self):
        app = _create_application(self.user, document_consistency_score=None)
        result = self.service._check_document_consistency(app)
        self.assertTrue(result["passed"])

    def test_document_consistency_passes_high_score(self):
        app = _create_application(self.user, document_consistency_score=0.85)
        result = self.service._check_document_consistency(app)
        self.assertTrue(result["passed"])

    def test_document_consistency_flags_low_score(self):
        app = _create_application(self.user, document_consistency_score=0.50)
        result = self.service._check_document_consistency(app)
        self.assertFalse(result["passed"])
        self.assertEqual(result["risk_level"], "medium")

    # ------------------------------------------------------------------
    # Bankruptcy + high amount
    # ------------------------------------------------------------------

    def test_bankruptcy_high_amount_passes_no_bankruptcy(self):
        app = _create_application(self.user, has_bankruptcy=False, loan_amount=Decimal("100000"))
        result = self.service._check_bankruptcy_high_amount(app)
        self.assertTrue(result["passed"])

    def test_bankruptcy_high_amount_passes_low_amount(self):
        app = _create_application(self.user, has_bankruptcy=True, loan_amount=Decimal("40000"))
        result = self.service._check_bankruptcy_high_amount(app)
        self.assertTrue(result["passed"])

    def test_bankruptcy_high_amount_flags(self):
        app = _create_application(self.user, has_bankruptcy=True, loan_amount=Decimal("75000"))
        result = self.service._check_bankruptcy_high_amount(app)
        self.assertFalse(result["passed"])
        self.assertEqual(result["risk_level"], "high")

    # ------------------------------------------------------------------
    # Composite run_checks
    # ------------------------------------------------------------------

    def test_run_checks_all_pass(self):
        app = _create_application(self.user)
        result = self.service.run_checks(app)
        self.assertTrue(result["passed"])
        self.assertEqual(result["risk_score"], 0.0)
        self.assertEqual(len(result["checks"]), 5)
        self.assertEqual(len(result["flagged_reasons"]), 0)

    def test_run_checks_fails_on_high_risk(self):
        """Bankruptcy + high amount is high risk — should fail overall."""
        app = _create_application(self.user, has_bankruptcy=True, loan_amount=Decimal("75000"))
        result = self.service.run_checks(app)
        self.assertFalse(result["passed"])
        self.assertGreater(result["risk_score"], 0.0)
        self.assertGreater(len(result["flagged_reasons"]), 0)

    def test_run_checks_passes_with_medium_risk_only(self):
        """Medium risk (income gap) should not cause overall failure."""
        app = _create_application(self.user, income_verification_gap=0.40)
        result = self.service.run_checks(app)
        self.assertTrue(result["passed"])
        self.assertGreater(result["risk_score"], 0.0)
        self.assertGreater(len(result["flagged_reasons"]), 0)

    def test_run_checks_creates_fraud_check_record(self):
        """Integration test: run_checks result can be persisted to FraudCheck model."""
        app = _create_application(self.user)
        result = self.service.run_checks(app)
        fraud_check = FraudCheck.objects.create(
            application=app,
            passed=result["passed"],
            risk_score=result["risk_score"],
            checks=result["checks"],
            flagged_reasons=result["flagged_reasons"],
        )
        self.assertEqual(fraud_check.passed, True)
        self.assertEqual(fraud_check.risk_score, 0.0)
        self.assertEqual(len(fraud_check.checks), 5)

    def test_risk_score_bounded_zero_to_one(self):
        """Risk score should always be between 0 and 1."""
        # All checks fail: duplicate + velocity + income + docs + bankruptcy
        for _ in range(3):
            _create_application(self.user, purpose="home", loan_amount=Decimal("75000"))
        app = _create_application(
            self.user,
            purpose="home",
            loan_amount=Decimal("75000"),
            has_bankruptcy=True,
            income_verification_gap=0.50,
            document_consistency_score=0.30,
        )
        result = self.service.run_checks(app)
        self.assertGreaterEqual(result["risk_score"], 0.0)
        self.assertLessEqual(result["risk_score"], 1.0)
