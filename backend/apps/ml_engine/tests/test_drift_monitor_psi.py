"""M1: single canonical on-demand PSI primitive (drift_monitor).

Confirms the on-demand /drift/ endpoint shares one PSI primitive with the
weekly DriftReport path, and that the module-level array-based ``compute_psi``
signature is preserved for the weekly report.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from apps.loans.models import LoanApplication
from apps.ml_engine.services.governance import drift_monitor

pytestmark = pytest.mark.django_db


def _make_loan(customer, credit_score):
    return LoanApplication.objects.create(
        applicant=customer,
        annual_income=90000,
        loan_amount=300000,
        loan_term_months=360,
        credit_score=credit_score,
        employment_length=5,
        debt_to_income=0.25,
        purpose="home",
        home_ownership="rent",
        has_cosigner=False,
        status="pending",
    )


@pytest.fixture
def customer(django_user_model):
    return django_user_model.objects.create_user(
        username="psi_customer",
        email="psi@example.com",
        password="x",
        role="customer",
    )


def test_compute_on_demand_feature_psi_returns_zero_for_identical(customer):
    """Identical recent vs reference distribution → low PSI, stable status."""
    # Reference histogram: credit scores spread evenly across 600-800.
    edges = list(np.linspace(600, 800, 11))
    # 20 applicants per bin → counts of 20 each.
    counts = [20] * 10
    ref_dist = {
        "credit_score": {
            "histogram_counts": counts,
            "histogram_edges": edges,
            "mean": 700,
            "std": 58,
        }
    }

    # Build 200 rows whose credit scores match the reference histogram shape.
    bin_centres = [(edges[i] + edges[i + 1]) / 2 for i in range(10)]
    for centre in bin_centres:
        for _ in range(20):
            _make_loan(customer, int(centre))

    fake_predictor = MagicMock()
    fake_predictor.reference_distribution = ref_dist
    fake_predictor.numeric_cols = ["credit_score"]

    model_version = MagicMock()
    model_version.id = "abc-123"

    with patch(
        "apps.ml_engine.services.predictor.ModelPredictor",
        return_value=fake_predictor,
    ):
        result = drift_monitor.compute_on_demand_feature_psi(model_version, days=30)

    assert "feature_psi" in result
    assert "credit_score" in result["feature_psi"]
    assert result["feature_psi"]["credit_score"]["psi"] < 0.10
    assert result["overall_status"] == "stable"


def test_compute_on_demand_insufficient_data(customer):
    """Fewer than 20 recent applications → insufficient_data sentinel."""
    _make_loan(customer, 700)
    fake_predictor = MagicMock()
    fake_predictor.reference_distribution = {"credit_score": {}}
    fake_predictor.numeric_cols = ["credit_score"]
    model_version = MagicMock()
    model_version.id = "abc-123"
    with patch(
        "apps.ml_engine.services.predictor.ModelPredictor",
        return_value=fake_predictor,
    ):
        result = drift_monitor.compute_on_demand_feature_psi(model_version, days=30)
    assert result.get("insufficient_data") is True
    assert result["application_count"] == 1


def test_compute_on_demand_no_reference_distribution():
    fake_predictor = MagicMock()
    fake_predictor.reference_distribution = {}
    model_version = MagicMock()
    with patch(
        "apps.ml_engine.services.predictor.ModelPredictor",
        return_value=fake_predictor,
    ):
        result = drift_monitor.compute_on_demand_feature_psi(model_version, days=30)
    assert result.get("error") == "no_reference_distribution"


def test_compute_psi_module_function_unchanged_for_arrays():
    """The weekly-report array-based signature is preserved."""
    arr = [1, 2, 3, 4] * 10
    assert drift_monitor.compute_psi(arr, arr) == pytest.approx(0.0, abs=1e-6)
