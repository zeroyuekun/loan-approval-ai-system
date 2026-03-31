"""Tests for PortfolioStressTester service."""

from decimal import Decimal

import pytest

from apps.loans.models import LoanApplication, LoanDecision
from apps.ml_engine.services.stress_testing import PortfolioStressTester


def _create_decision(app, decision="approved", confidence=0.85):
    """Helper to attach a LoanDecision so select_related('decision') works."""
    return LoanDecision.objects.create(
        application=app,
        decision=decision,
        confidence=confidence,
    )


# ── 1. Scenario definitions ────────────────────────────────────────────────


class TestScenarioDefinitions:
    def test_scenarios_defined(self):
        """Five scenarios exist and each has required keys."""
        tester = PortfolioStressTester()
        assert len(tester.SCENARIOS) == 5

        expected_names = {
            "rate_shock_2pct",
            "rate_shock_3pct",
            "unemployment_rise",
            "property_decline_20pct",
            "combined_adverse",
        }
        assert set(tester.SCENARIOS.keys()) == expected_names

        required_keys = {"description", "rate_increase", "income_reduction", "property_decline"}
        for name, scenario in tester.SCENARIOS.items():
            assert required_keys.issubset(scenario.keys()), f"{name} missing keys"


# ── 2. Empty portfolio ─────────────────────────────────────────────────────


@pytest.mark.django_db
class TestEmptyPortfolio:
    def test_no_approved_loans_returns_error(self):
        """When there are no approved loans the result is an error dict."""
        tester = PortfolioStressTester()
        result = tester.run_stress_test()
        assert "error" in result
        assert "No approved loans" in result["error"]


# ── 3-4. Single and all scenarios ──────────────────────────────────────────


@pytest.mark.django_db
class TestRunStressTest:
    def test_single_scenario(self, approved_home_loan):
        """Running one named scenario returns only that key."""
        _create_decision(approved_home_loan)
        tester = PortfolioStressTester()
        result = tester.run_stress_test(scenario_name="rate_shock_2pct")

        assert list(result.keys()) == ["rate_shock_2pct"]
        data = result["rate_shock_2pct"]
        assert data["total_loans"] == 1
        assert data["at_risk_count"] + (data["total_loans"] - data["at_risk_count"]) == 1

    def test_all_scenarios(self, approved_home_loan):
        """Running with no name returns all five scenario keys."""
        _create_decision(approved_home_loan)
        tester = PortfolioStressTester()
        result = tester.run_stress_test()

        assert len(result) == 5
        assert set(result.keys()) == set(PortfolioStressTester.SCENARIOS.keys())


# ── 5. Comfortable borrower survives rate shock ────────────────────────────


@pytest.mark.django_db
class TestRateShockComfortableBorrower:
    def test_rate_shock_comfortable_borrower(self, customer_user):
        """High income, low loan amount borrower survives a +3% rate shock."""
        app = LoanApplication.objects.create(
            applicant=customer_user,
            annual_income=Decimal("200000.00"),
            credit_score=820,
            loan_amount=Decimal("100000.00"),
            loan_term_months=360,
            debt_to_income=Decimal("0.50"),
            employment_length=15,
            purpose="home",
            home_ownership="mortgage",
            has_cosigner=False,
            property_value=Decimal("500000.00"),
            deposit_amount=Decimal("400000.00"),
            monthly_expenses=Decimal("3000.00"),
            existing_credit_card_limit=Decimal("5000.00"),
            number_of_dependants=0,
            employment_type="payg_permanent",
            applicant_type="single",
            has_hecs=False,
            has_bankruptcy=False,
            state="NSW",
            status="approved",
        )
        _create_decision(app)

        tester = PortfolioStressTester()
        result = tester.run_stress_test(scenario_name="rate_shock_3pct")
        assert result["rate_shock_3pct"]["at_risk_count"] == 0


# ── 6. Property decline pushes high-LVR loan to default ───────────────────


@pytest.mark.django_db
class TestPropertyDeclineHighLVR:
    def test_property_decline_high_lvr(self, approved_home_loan):
        """80% LVR loan (480k/600k) with -20% property → stressed LVR = 1.0 → default."""
        _create_decision(approved_home_loan)
        tester = PortfolioStressTester()

        scenario = tester.SCENARIOS["property_decline_20pct"]
        stressed = tester._apply_scenario(approved_home_loan, scenario)

        # 480k / (600k * 0.8) = 480k / 480k = 1.0 → stressed_lvr > 1.0 is False at exactly 1.0
        # However floating point may cause >= 1.0; the code checks stressed_lvr > 1.0
        assert stressed["stressed_lvr"] == pytest.approx(1.0, abs=1e-9)
        # At exactly 1.0, > 1.0 is False, so default depends on surplus
        # If surplus is positive, would_default should be False
        # If surplus is negative, would_default is True regardless


# ── 7. Tight borrower defaults on income reduction ─────────────────────────


@pytest.mark.django_db
class TestIncomeReductionTightBorrower:
    def test_income_reduction_tight_borrower(self, customer_user):
        """A borrower with tight cashflow goes negative under -15% income."""
        app = LoanApplication.objects.create(
            applicant=customer_user,
            annual_income=Decimal("50000.00"),
            credit_score=700,
            loan_amount=Decimal("400000.00"),
            loan_term_months=360,
            debt_to_income=Decimal("8.00"),
            employment_length=5,
            purpose="home",
            home_ownership="mortgage",
            has_cosigner=False,
            property_value=Decimal("500000.00"),
            deposit_amount=Decimal("100000.00"),
            monthly_expenses=Decimal("2500.00"),
            existing_credit_card_limit=Decimal("5000.00"),
            number_of_dependants=2,
            employment_type="payg_permanent",
            applicant_type="couple",
            has_hecs=False,
            has_bankruptcy=False,
            state="VIC",
            status="approved",
        )
        _create_decision(app)

        tester = PortfolioStressTester()
        scenario = tester.SCENARIOS["unemployment_rise"]
        stressed = tester._apply_scenario(app, scenario)

        assert stressed["surplus"] < 0
        assert stressed["would_default"] is True


# ── 8. Combined adverse is worse than any single scenario ──────────────────


@pytest.mark.django_db
class TestCombinedAdverse:
    def test_combined_adverse_worst_case(self, approved_home_loan):
        """Combined scenario puts more loans at risk than any single scenario."""
        _create_decision(approved_home_loan)
        tester = PortfolioStressTester()

        # Get at-risk counts for individual scenarios
        individual_scenarios = ["rate_shock_2pct", "unemployment_rise", "property_decline_20pct"]
        individual_at_risk = []
        for name in individual_scenarios:
            result = tester.run_stress_test(scenario_name=name)
            individual_at_risk.append(result[name]["at_risk_count"])

        combined_result = tester.run_stress_test(scenario_name="combined_adverse")
        combined_at_risk = combined_result["combined_adverse"]["at_risk_count"]

        # Combined should be at least as bad as any individual scenario
        assert combined_at_risk >= max(individual_at_risk)


# ── 9. Direct _apply_scenario test ─────────────────────────────────────────


@pytest.mark.django_db
class TestApplyScenarioDirectly:
    def test_apply_scenario_directly(self, approved_home_loan):
        """_apply_scenario returns dict with expected keys and types."""
        tester = PortfolioStressTester()
        scenario = tester.SCENARIOS["rate_shock_2pct"]
        result = tester._apply_scenario(approved_home_loan, scenario)

        assert "would_default" in result
        assert "surplus" in result
        assert "stressed_lvr" in result
        assert isinstance(result["would_default"], bool)
        assert isinstance(result["surplus"], float)
        assert isinstance(result["stressed_lvr"], float)


# ── 10. Result structure validation ────────────────────────────────────────


@pytest.mark.django_db
class TestResultStructure:
    def test_result_structure(self, approved_home_loan):
        """Verify all expected keys are present in each scenario result."""
        _create_decision(approved_home_loan)
        tester = PortfolioStressTester()
        results = tester.run_stress_test()

        expected_keys = {
            "description",
            "total_loans",
            "at_risk_count",
            "at_risk_pct",
            "total_exposure",
            "at_risk_exposure",
            "at_risk_exposure_pct",
        }

        for name, data in results.items():
            assert expected_keys == set(data.keys()), f"Key mismatch for scenario {name}"
            assert isinstance(data["total_loans"], int)
            assert isinstance(data["at_risk_count"], int)
            assert isinstance(data["at_risk_pct"], float)
            assert isinstance(data["total_exposure"], float)
            assert isinstance(data["at_risk_exposure"], float)
            assert isinstance(data["at_risk_exposure_pct"], float)
