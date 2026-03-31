"""Tests for conditional approval flow.

Verifies that the orchestrator correctly identifies risk factors that require
conditions before full approval, and that the LoanApplication model properly
stores condition data.
"""

from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import CustomUser
from apps.agents.services.orchestrator import PipelineOrchestrator
from apps.loans.models import LoanApplication


class EvaluateConditionsTestCase(TestCase):
    """Unit tests for PipelineOrchestrator._evaluate_conditions."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="cond_test",
            password="testpass123",
            email="cond@test.com",
            role="customer",
        )
        self.base_kwargs = {
            "applicant": self.user,
            "annual_income": Decimal("120000.00"),
            "credit_score": 780,
            "loan_amount": Decimal("350000.00"),
            "loan_term_months": 360,
            "debt_to_income": Decimal("3.50"),
            "employment_length": 5,
            "purpose": "home",
            "home_ownership": "mortgage",
            "employment_type": "payg_permanent",
            "applicant_type": "single",
            "property_value": Decimal("500000.00"),
        }

    def _create_app(self, **overrides):
        kwargs = {**self.base_kwargs, **overrides}
        return LoanApplication.objects.create(**kwargs)

    def test_no_conditions_for_clean_application(self):
        """A clean application should have zero conditions."""
        app = self._create_app()
        conditions = PipelineOrchestrator._evaluate_conditions(app)
        self.assertEqual(conditions, [])

    def test_income_verification_gap_triggers_condition(self):
        """income_verification_gap > 0.15 should trigger income_verification."""
        app = self._create_app(income_verification_gap=0.25)
        conditions = PipelineOrchestrator._evaluate_conditions(app)
        types = [c["type"] for c in conditions]
        self.assertIn("income_verification", types)

    def test_income_verification_gap_at_threshold_no_condition(self):
        """income_verification_gap == 0.15 should NOT trigger (must exceed)."""
        app = self._create_app(income_verification_gap=0.15)
        conditions = PipelineOrchestrator._evaluate_conditions(app)
        types = [c["type"] for c in conditions]
        self.assertNotIn("income_verification", types)

    def test_income_verification_gap_none_no_condition(self):
        """Null income_verification_gap should not trigger."""
        app = self._create_app(income_verification_gap=None)
        conditions = PipelineOrchestrator._evaluate_conditions(app)
        types = [c["type"] for c in conditions]
        self.assertNotIn("income_verification", types)

    def test_self_employed_short_tenure_triggers_condition(self):
        """Self-employed with < 2 years should trigger employment_verification."""
        app = self._create_app(employment_type="self_employed", employment_length=1)
        conditions = PipelineOrchestrator._evaluate_conditions(app)
        types = [c["type"] for c in conditions]
        self.assertIn("employment_verification", types)

    def test_self_employed_at_two_years_no_condition(self):
        """Self-employed with exactly 2 years should NOT trigger."""
        app = self._create_app(employment_type="self_employed", employment_length=2)
        conditions = PipelineOrchestrator._evaluate_conditions(app)
        types = [c["type"] for c in conditions]
        self.assertNotIn("employment_verification", types)

    def test_payg_short_tenure_no_condition(self):
        """Non-self-employed with short tenure should NOT trigger."""
        app = self._create_app(employment_type="payg_permanent", employment_length=1)
        conditions = PipelineOrchestrator._evaluate_conditions(app)
        types = [c["type"] for c in conditions]
        self.assertNotIn("employment_verification", types)

    def test_home_purpose_no_property_value_triggers_condition(self):
        """Home loan without property_value should trigger valuation_required."""
        app = self._create_app(purpose="home", property_value=None)
        conditions = PipelineOrchestrator._evaluate_conditions(app)
        types = [c["type"] for c in conditions]
        self.assertIn("valuation_required", types)

    def test_home_purpose_with_property_value_no_condition(self):
        """Home loan with property_value should NOT trigger."""
        app = self._create_app(purpose="home", property_value=Decimal("600000.00"))
        conditions = PipelineOrchestrator._evaluate_conditions(app)
        types = [c["type"] for c in conditions]
        self.assertNotIn("valuation_required", types)

    def test_non_home_purpose_no_property_value_no_condition(self):
        """Non-home loan without property_value should NOT trigger."""
        app = self._create_app(purpose="personal", property_value=None)
        conditions = PipelineOrchestrator._evaluate_conditions(app)
        types = [c["type"] for c in conditions]
        self.assertNotIn("valuation_required", types)

    def test_large_loan_low_income_no_cosigner_triggers_guarantor(self):
        """Loan > 500k, income < 100k, no cosigner -> guarantor_needed."""
        app = self._create_app(
            loan_amount=Decimal("600000.00"),
            annual_income=Decimal("85000.00"),
            has_cosigner=False,
        )
        conditions = PipelineOrchestrator._evaluate_conditions(app)
        types = [c["type"] for c in conditions]
        self.assertIn("guarantor_needed", types)

    def test_large_loan_with_cosigner_no_condition(self):
        """Loan > 500k with cosigner should NOT trigger guarantor."""
        app = self._create_app(
            loan_amount=Decimal("600000.00"),
            annual_income=Decimal("85000.00"),
            has_cosigner=True,
        )
        conditions = PipelineOrchestrator._evaluate_conditions(app)
        types = [c["type"] for c in conditions]
        self.assertNotIn("guarantor_needed", types)

    def test_large_loan_high_income_no_cosigner_no_condition(self):
        """Loan > 500k with income >= 100k should NOT trigger guarantor."""
        app = self._create_app(
            loan_amount=Decimal("600000.00"),
            annual_income=Decimal("100000.00"),
            has_cosigner=False,
        )
        conditions = PipelineOrchestrator._evaluate_conditions(app)
        types = [c["type"] for c in conditions]
        self.assertNotIn("guarantor_needed", types)

    def test_loan_at_threshold_no_guarantor(self):
        """Loan == 500000 should NOT trigger (must exceed)."""
        app = self._create_app(
            loan_amount=Decimal("500000.00"),
            annual_income=Decimal("85000.00"),
            has_cosigner=False,
        )
        conditions = PipelineOrchestrator._evaluate_conditions(app)
        types = [c["type"] for c in conditions]
        self.assertNotIn("guarantor_needed", types)

    def test_multiple_conditions_can_fire(self):
        """Multiple risk factors should produce multiple conditions."""
        app = self._create_app(
            income_verification_gap=0.25,
            employment_type="self_employed",
            employment_length=1,
            purpose="home",
            property_value=None,
            loan_amount=Decimal("600000.00"),
            annual_income=Decimal("85000.00"),
            has_cosigner=False,
        )
        conditions = PipelineOrchestrator._evaluate_conditions(app)
        types = {c["type"] for c in conditions}
        self.assertEqual(
            types,
            {
                "income_verification",
                "employment_verification",
                "valuation_required",
                "guarantor_needed",
            },
        )

    def test_condition_dict_structure(self):
        """Each condition dict should have the correct keys and default values."""
        app = self._create_app(income_verification_gap=0.30)
        conditions = PipelineOrchestrator._evaluate_conditions(app)
        self.assertEqual(len(conditions), 1)
        cond = conditions[0]
        self.assertEqual(cond["type"], "income_verification")
        self.assertIsInstance(cond["description"], str)
        self.assertTrue(len(cond["description"]) > 0)
        self.assertTrue(cond["required"])
        self.assertFalse(cond["satisfied"])
        self.assertIsNone(cond["satisfied_at"])


class ConditionalApprovalModelTestCase(TestCase):
    """Tests for condition fields on LoanApplication."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="cond_model_test",
            password="testpass123",
            email="condmodel@test.com",
            role="customer",
        )
        self.app = LoanApplication.objects.create(
            applicant=self.user,
            annual_income=Decimal("75000.00"),
            credit_score=720,
            loan_amount=Decimal("25000.00"),
            loan_term_months=36,
            debt_to_income=Decimal("1.50"),
            employment_length=5,
            purpose="personal",
            home_ownership="rent",
            employment_type="payg_permanent",
            applicant_type="single",
        )

    def test_default_conditions_empty_list(self):
        """conditions field defaults to empty list."""
        self.assertEqual(self.app.conditions, [])

    def test_default_conditions_met_false(self):
        """conditions_met defaults to False."""
        self.assertFalse(self.app.conditions_met)

    def test_conditions_json_round_trip(self):
        """Conditions can be saved and loaded from database."""
        test_conditions = [
            {
                "type": "income_verification",
                "description": "Please provide payslips.",
                "required": True,
                "satisfied": False,
                "satisfied_at": None,
            },
            {
                "type": "valuation_required",
                "description": "Property valuation needed.",
                "required": True,
                "satisfied": True,
                "satisfied_at": "2026-03-25T10:00:00+00:00",
            },
        ]
        self.app.conditions = test_conditions
        self.app.save()
        self.app.refresh_from_db()
        self.assertEqual(len(self.app.conditions), 2)
        self.assertEqual(self.app.conditions[0]["type"], "income_verification")
        self.assertEqual(self.app.conditions[1]["satisfied_at"], "2026-03-25T10:00:00+00:00")

    def test_review_status_persists(self):
        """The 'review' status value persists in the database."""
        self.app.status = "review"
        self.app.save()
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "review")

    def test_review_status_is_valid_choice(self):
        """'review' should be a valid Status choice."""
        self.assertIn(
            "review",
            [choice[0] for choice in LoanApplication.Status.choices],
        )
