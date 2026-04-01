"""Tests for APP 12 customer data export endpoint."""

import pytest
from rest_framework.test import APIClient

from apps.agents.models import AgentRun, BiasReport, MarketingEmail
from apps.email_engine.models import GeneratedEmail
from apps.loans.models import LoanDecision
from apps.ml_engine.models import ModelVersion


@pytest.fixture
def auth_client(customer_user):
    client = APIClient()
    client.force_authenticate(user=customer_user)
    return client


@pytest.fixture
def full_application(sample_application):
    """Sample application with decision, email, agent run, bias report, marketing email."""
    app = sample_application

    mv = ModelVersion.objects.create(
        algorithm="rf",
        version="rf-v2",
        file_path="/app/ml_models/rf-v2.joblib",
        is_active=True,
    )

    # Decision
    LoanDecision.objects.create(
        application=app,
        decision="approved",
        confidence=0.92,
        risk_grade="AA",
        feature_importances={"credit_score": 0.3, "income": 0.25},
        shap_values={"credit_score": 0.15},
        reasoning="Strong credit profile",
        model_version=mv,
    )

    # Generated email
    GeneratedEmail.objects.create(
        application=app,
        decision="approved",
        subject="Your loan has been approved",
        body="Congratulations, your loan is approved.",
        prompt_used="test prompt",
    )

    # Agent run with bias report
    run = AgentRun.objects.create(
        application=app,
        status="completed",
        steps=[{"step_name": "predict", "status": "completed"}],
    )
    BiasReport.objects.create(
        agent_run=run,
        bias_score=12.5,
        categories=["age"],
        analysis="Low bias detected",
        flagged=False,
    )

    # Marketing email
    MarketingEmail.objects.create(
        agent_run=run,
        application=app,
        subject="Special offer for you",
        body="Check out our new products.",
        prompt_used="marketing prompt",
    )

    return app


@pytest.mark.django_db
class TestCustomerDataExport:
    URL = "/api/v1/auth/me/data-export/"

    def test_unauthenticated_returns_401(self):
        client = APIClient()
        resp = client.get(self.URL)
        assert resp.status_code == 401

    def test_basic_export_structure(self, auth_client):
        resp = auth_client.get(self.URL)
        assert resp.status_code == 200
        data = resp.json()
        assert "user" in data
        assert "loan_applications" in data
        assert "audit_logs" in data

    def test_export_includes_decision(self, auth_client, full_application):
        resp = auth_client.get(self.URL)
        data = resp.json()
        apps = data["loan_applications"]
        assert len(apps) >= 1

        app_data = next(a for a in apps if a["id"] == str(full_application.id))
        decision = app_data["decision"]
        assert decision is not None
        assert decision["decision"] == "approved"
        assert decision["confidence"] == 0.92
        assert decision["risk_grade"] == "AA"
        assert decision["feature_importances"] == {"credit_score": 0.3, "income": 0.25}
        assert decision["shap_values"] == {"credit_score": 0.15}
        assert decision["reasoning"] == "Strong credit profile"
        assert decision["model_version"] is not None

    def test_export_includes_emails(self, auth_client, full_application):
        resp = auth_client.get(self.URL)
        data = resp.json()
        app_data = next(a for a in data["loan_applications"] if a["id"] == str(full_application.id))
        assert len(app_data["emails"]) == 1
        assert app_data["emails"][0]["subject"] == "Your loan has been approved"
        assert app_data["emails"][0]["decision"] == "approved"

    def test_export_includes_agent_runs_with_bias(self, auth_client, full_application):
        resp = auth_client.get(self.URL)
        data = resp.json()
        app_data = next(a for a in data["loan_applications"] if a["id"] == str(full_application.id))
        assert len(app_data["agent_runs"]) == 1
        run = app_data["agent_runs"][0]
        assert run["status"] == "completed"
        assert len(run["bias_reports"]) == 1
        assert run["bias_reports"][0]["bias_score"] == 12.5
        assert run["bias_reports"][0]["categories"] == ["age"]

    def test_export_includes_marketing_emails(self, auth_client, full_application):
        resp = auth_client.get(self.URL)
        data = resp.json()
        app_data = next(a for a in data["loan_applications"] if a["id"] == str(full_application.id))
        assert len(app_data["marketing_emails"]) == 1
        assert app_data["marketing_emails"][0]["subject"] == "Special offer for you"

    def test_export_no_decision(self, auth_client, sample_application):
        """Application without a decision should export decision as null."""
        resp = auth_client.get(self.URL)
        data = resp.json()
        app_data = next(a for a in data["loan_applications"] if a["id"] == str(sample_application.id))
        assert app_data["decision"] is None

    def test_export_no_cross_user_leakage(self, db, sample_application):
        """Other users should not see this user's applications."""
        from apps.accounts.models import CustomUser

        other = CustomUser.objects.create_user(
            username="other", email="other@test.com", password="testpass123", role="customer"
        )
        client = APIClient()
        client.force_authenticate(user=other)
        resp = client.get(self.URL)
        data = resp.json()
        assert len(data["loan_applications"]) == 0
