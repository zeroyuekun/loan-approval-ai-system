"""
API Contract Tests — validate that backend response shapes match
the TypeScript interfaces defined in frontend/src/types/index.ts.

These tests check key PRESENCE and type, NOT exact values.
They ensure the API contract between backend and frontend is not broken.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient


def _redis_available():
    try:
        import redis

        r = redis.Redis(host="localhost", port=6379, db=1, socket_connect_timeout=1)
        r.ping()
        return True
    except Exception:
        return False


skip_without_redis = pytest.mark.skipif(
    not _redis_available(),
    reason="Redis not available (tests run in Docker/CI)",
)
pytestmark = skip_without_redis

from django.conf import settings

from apps.accounts.models import CustomerProfile, CustomUser
from apps.agents.models import AgentRun, BiasReport, MarketingEmail, NextBestOffer
from apps.loans.models import LoanDecision
from apps.ml_engine.models import ModelVersion

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _disable_throttling(api_view_cls):
    """Return a patcher that disables throttle_classes on the given view."""
    return patch.object(api_view_cls, "throttle_classes", [])


@pytest.fixture(autouse=True)
def _no_throttling():
    """Globally disable all custom throttle classes for contract tests."""
    from apps.accounts.views import LoginView, RegisterView
    from apps.agents.views import BatchOrchestrateView, HumanReviewView, OrchestrateView
    from apps.ml_engine.views import PredictView

    with (
        _disable_throttling(LoginView),
        _disable_throttling(RegisterView),
        _disable_throttling(OrchestrateView),
        _disable_throttling(BatchOrchestrateView),
        _disable_throttling(HumanReviewView),
        _disable_throttling(PredictView),
    ):
        yield


@pytest.fixture
def auth_admin_client(api_client, admin_user):
    """Return an API client authenticated as admin."""
    api_client.force_authenticate(user=admin_user)
    return api_client


@pytest.fixture
def auth_customer_client(db):
    """Return an API client authenticated as a customer with a complete profile."""
    user = CustomUser.objects.create_user(
        username="contract_customer",
        email="contractcust@test.com",
        password="TestPass123!abc",
        role="customer",
        first_name="Contract",
        last_name="Customer",
    )
    # Update the auto-created profile with complete data for loan creation validation
    CustomerProfile.objects.update_or_create(
        user=user,
        defaults={
            "date_of_birth": "1990-01-15",
            "phone": "0412345678",
            "address_line_1": "123 Test St",
            "suburb": "Sydney",
            "state": "NSW",
            "postcode": "2000",
            "employer_name": "Test Corp",
            "occupation": "Engineer",
            "industry": "Technology",
            "employment_status": "Full-time",
            "years_in_current_role": 5,
            "gross_annual_income": Decimal("80000.00"),
            "housing_situation": "renting",
            "time_at_current_address_years": 3,
            "residency_status": "citizen",
            "primary_id_type": "drivers_licence",
            "primary_id_number": "DL12345678",
            "marital_status": "single",
        },
    )
    client = APIClient()
    client.force_authenticate(user=user)
    client._user = user  # stash for tests that need the user object
    return client


# ---------------------------------------------------------------------------
# Auth Contract Tests — frontend User interface
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAuthContracts:
    """Verify auth API responses match frontend TypeScript User type."""

    # Keys the frontend User interface requires
    USER_REQUIRED_KEYS = {"id", "username", "email", "role"}
    USER_ALL_KEYS = {"id", "username", "email", "role", "first_name", "last_name", "created_at"}

    def test_register_response_shape(self, api_client):
        """POST /api/v1/auth/register/ must return {user: User}."""
        response = api_client.post(
            "/api/v1/auth/register/",
            {
                "username": "contracttest",
                "email": "contract@test.com",
                "password": "TestPass123!abc",
                "password2": "TestPass123!abc",
            },
        )
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.data}"
        data = response.json()
        assert "user" in data, "Register response must have 'user' key (frontend User type)"
        user = data["user"]
        for key in self.USER_REQUIRED_KEYS:
            assert key in user, f"Missing key '{key}' in register user response (frontend User type)"
        assert isinstance(user["id"], int), "user.id must be int (frontend User.id: number)"
        assert isinstance(user["username"], str), "user.username must be str"
        assert isinstance(user["role"], str), "user.role must be str"

    def test_login_response_shape(self, api_client, db):
        """POST /api/v1/auth/login/ must return {user: User}."""
        # Create a user to log in with
        CustomUser.objects.create_user(
            username="logintest",
            email="login@test.com",
            password="TestPass123!abc",
            role="customer",
        )
        response = api_client.post(
            "/api/v1/auth/login/",
            {
                "username": "logintest",
                "password": "TestPass123!abc",
            },
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.data}"
        data = response.json()
        assert "user" in data, "Login response must have 'user' key (frontend User type)"
        user = data["user"]
        for key in self.USER_REQUIRED_KEYS:
            assert key in user, f"Missing key '{key}' in login user response (frontend User type)"
        assert isinstance(user["id"], int), "user.id must be int"

    def test_me_response_shape(self, auth_admin_client):
        """GET /api/v1/auth/me/ must return flat User object with all User keys."""
        response = auth_admin_client.get("/api/v1/auth/me/")
        assert response.status_code == 200
        data = response.json()
        for key in self.USER_ALL_KEYS:
            assert key in data, f"Missing key '{key}' in /me/ response (frontend User type)"
        assert isinstance(data["id"], int), "id must be int (frontend User.id: number)"
        assert isinstance(data["role"], str), "role must be str"
        assert isinstance(data["first_name"], str), "first_name must be str"
        assert isinstance(data["last_name"], str), "last_name must be str"


# ---------------------------------------------------------------------------
# Loan Application Contract Tests — frontend LoanApplication interface
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLoanApplicationContracts:
    """Verify loan API responses match frontend LoanApplication & PaginatedResponse types."""

    LIST_REQUIRED_KEYS = {"id", "loan_amount", "purpose", "status", "created_at"}
    DETAIL_REQUIRED_KEYS = {
        "id",
        "loan_amount",
        "annual_income",
        "credit_score",
        "purpose",
        "status",
        "applicant",
        "decision",
        "created_at",
        "updated_at",
    }

    def test_list_response_shape(self, auth_admin_client, sample_application):
        """GET /api/v1/loans/ must return PaginatedResponse<LoanApplication>."""
        response = auth_admin_client.get("/api/v1/loans/")
        assert response.status_code == 200
        data = response.json()
        # PaginatedResponse shape
        assert "results" in data, "List response must have 'results' (frontend PaginatedResponse.results)"
        assert "count" in data, "List response must have 'count' (frontend PaginatedResponse.count)"
        assert isinstance(data["results"], list), "results must be a list"
        assert isinstance(data["count"], int), "count must be an int"
        # Each result should have core loan keys
        if data["results"]:
            item = data["results"][0]
            for key in self.LIST_REQUIRED_KEYS:
                assert key in item, f"Missing key '{key}' in loan list item (frontend LoanApplication)"

    def test_detail_response_shape(self, auth_admin_client, sample_application):
        """GET /api/v1/loans/{id}/ must return full LoanApplication with nested applicant and decision."""
        response = auth_admin_client.get(f"/api/v1/loans/{sample_application.pk}/")
        assert response.status_code == 200
        data = response.json()
        for key in self.DETAIL_REQUIRED_KEYS:
            assert key in data, f"Missing key '{key}' in loan detail (frontend LoanApplication)"
        # Applicant must be a nested User object
        assert isinstance(data["applicant"], dict), "applicant must be dict (nested User)"
        for key in ("id", "username", "email", "role"):
            assert key in data["applicant"], f"Missing '{key}' in applicant (frontend User type)"
        # Decision can be null if no prediction has run
        assert "decision" in data, "Must have 'decision' key even if null (frontend LoanApplication.decision?)"
        # Status must be a string
        assert isinstance(data["status"], str), "status must be str"

    @patch("apps.loans.views.orchestrate_pipeline_task")
    def test_create_response_shape(self, mock_pipeline, auth_customer_client):
        """POST /api/v1/loans/ must return the created application with an id."""
        payload = {
            "annual_income": "80000.00",
            "credit_score": 750,
            "loan_amount": "30000.00",
            "loan_term_months": 36,
            "debt_to_income": "1.20",
            "employment_length": 5,
            "purpose": "personal",
            "home_ownership": "rent",
            "has_cosigner": False,
            "monthly_expenses": "2000.00",
            "existing_credit_card_limit": "5000.00",
            "number_of_dependants": 0,
            "employment_type": "payg_permanent",
            "applicant_type": "single",
            "has_hecs": False,
            "has_bankruptcy": False,
            "state": "NSW",
        }
        response = auth_customer_client.post("/api/v1/loans/", payload, format="json")
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.data}"
        data = response.json()
        assert "id" in data, "Created application must have 'id' (frontend LoanApplication.id)"

    def test_detail_with_decision_shape(self, auth_admin_client, sample_application):
        """When a LoanDecision exists, it must match frontend LoanDecision interface."""
        LoanDecision.objects.create(
            application=sample_application,
            decision="approved",
            confidence=0.92,
            risk_score=0.15,
            model_version="test-v1",
            reasoning="Test reasoning",
            feature_importances={"credit_score": 0.3, "income": 0.2},
        )
        response = auth_admin_client.get(f"/api/v1/loans/{sample_application.pk}/")
        assert response.status_code == 200
        data = response.json()
        decision = data["decision"]
        assert decision is not None, "Decision must be present when LoanDecision exists"
        decision_keys = {"id", "decision", "confidence", "model_version", "reasoning", "created_at"}
        for key in decision_keys:
            assert key in decision, f"Missing key '{key}' in decision (frontend LoanDecision)"
        assert isinstance(decision["confidence"], (int, float)), "confidence must be numeric"


# ---------------------------------------------------------------------------
# ML Model Metrics Contract Tests — frontend ModelMetrics interface
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMLMetricsContracts:
    """Verify ML metrics API responses match frontend ModelMetrics type."""

    REQUIRED_KEYS = {
        "id",
        "algorithm",
        "version",
        "accuracy",
        "precision",
        "recall",
        "f1_score",
        "auc_roc",
        "is_active",
        "created_at",
        "confusion_matrix",
        "feature_importances",
        "roc_curve_data",
        "training_params",
    }

    @pytest.fixture
    def active_model(self, db):
        """Create an active ModelVersion for metrics tests."""
        import os

        models_dir = str(settings.ML_MODELS_DIR)
        os.makedirs(models_dir, exist_ok=True)
        dummy_path = os.path.join(models_dir, "contract_test_model.joblib")
        with open(dummy_path, "wb") as f:
            f.write(b"dummy")
        return ModelVersion.objects.create(
            algorithm="xgb",
            version="contract-test-v1",
            file_path=dummy_path,
            is_active=True,
            accuracy=0.85,
            precision=0.80,
            recall=0.90,
            f1_score=0.85,
            auc_roc=0.92,
            confusion_matrix={"tp": 100, "fp": 10, "tn": 90, "fn": 5},
            feature_importances={"credit_score": 0.3},
            roc_curve_data={"fpr": [0, 0.1, 1], "tpr": [0, 0.9, 1]},
            training_params={"n_estimators": 100},
        )

    def test_metrics_response_shape(self, auth_admin_client, active_model):
        """GET /api/v1/ml/models/active/metrics/ must return ModelMetrics shape."""
        response = auth_admin_client.get("/api/v1/ml/models/active/metrics/")
        assert response.status_code == 200
        data = response.json()
        for key in self.REQUIRED_KEYS:
            assert key in data, f"Missing key '{key}' in metrics response (frontend ModelMetrics)"
        # Type checks matching frontend ModelMetrics interface
        assert isinstance(data["id"], str), "id must be str (frontend ModelMetrics.id: string)"
        assert isinstance(data["algorithm"], str), "algorithm must be str"
        assert isinstance(data["version"], str), "version must be str"
        assert isinstance(data["is_active"], bool), "is_active must be bool"
        assert isinstance(data["confusion_matrix"], dict), "confusion_matrix must be dict"
        assert isinstance(data["feature_importances"], (dict, list)), "feature_importances must be dict or list"
        assert isinstance(data["roc_curve_data"], dict), "roc_curve_data must be dict"
        assert isinstance(data["training_params"], dict), "training_params must be dict"

    def test_metrics_nullable_fields(self, auth_admin_client, active_model):
        """Metrics fields like brier_score, gini_coefficient can be null (frontend uses | null)."""
        response = auth_admin_client.get("/api/v1/ml/models/active/metrics/")
        data = response.json()
        # These fields exist in frontend ModelMetrics as optional nullable
        nullable_keys = [
            "brier_score",
            "gini_coefficient",
            "ks_statistic",
            "log_loss",
            "ece",
            "optimal_threshold",
        ]
        for key in nullable_keys:
            assert key in data, f"Missing nullable key '{key}' in metrics (frontend ModelMetrics)"

    def test_metrics_404_when_no_active_model(self, auth_admin_client, db):
        """GET /api/v1/ml/models/active/metrics/ returns 404 when no active model."""
        ModelVersion.objects.filter(is_active=True).delete()
        response = auth_admin_client.get("/api/v1/ml/models/active/metrics/")
        assert response.status_code == 404
        data = response.json()
        assert "error" in data, "404 response must have 'error' key"


# ---------------------------------------------------------------------------
# Agent Run Contract Tests — frontend AgentRun interface
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAgentRunContracts:
    """Verify agent run API responses match frontend AgentRun type."""

    AGENTRUN_REQUIRED_KEYS = {
        "id",
        "application_id",
        "status",
        "steps",
        "created_at",
        "updated_at",
        "bias_reports",
        "next_best_offers",
        "marketing_emails",
    }

    @pytest.fixture
    def agent_run_with_data(self, sample_application, db):
        """Create an AgentRun with bias reports, NBO, and marketing emails."""
        run = AgentRun.objects.create(
            application=sample_application,
            status="completed",
            steps=[
                {
                    "step_name": "prediction",
                    "status": "completed",
                    "started_at": "2025-01-01T00:00:00Z",
                    "completed_at": "2025-01-01T00:00:01Z",
                    "result_summary": {"decision": "approved"},
                    "error": None,
                },
            ],
            total_time_ms=1500,
            error="",
        )
        BiasReport.objects.create(
            agent_run=run,
            report_type="decision",
            bias_score=12.5,
            deterministic_score=10.0,
            score_source="composite",
            categories=["gender"],
            analysis="Test analysis",
            flagged=False,
            requires_human_review=False,
            ai_review_approved=True,
            ai_review_reasoning="Low risk",
        )
        NextBestOffer.objects.create(
            agent_run=run,
            application=sample_application,
            offers=[{"type": "credit_card", "amount": 5000, "reasoning": "Good history"}],
            analysis="Test NBO analysis",
            customer_retention_score=75.0,
            loyalty_factors=["tenure", "products"],
            personalized_message="Welcome offer",
            marketing_message="Special deal",
        )
        MarketingEmail.objects.create(
            agent_run=run,
            application=sample_application,
            subject="Your offer",
            body="Dear customer...",
            prompt_used="test prompt",
            generation_time_ms=500,
            attempt_number=1,
            passed_guardrails=True,
            guardrail_results=[{"check_name": "bias", "passed": True, "details": "ok"}],
        )
        return run

    def test_agent_run_detail_shape(self, auth_admin_client, agent_run_with_data, sample_application):
        """GET /api/v1/agents/runs/{loan_id}/ must return AgentRun shape."""
        response = auth_admin_client.get(f"/api/v1/agents/runs/{sample_application.pk}/")
        assert response.status_code == 200
        data = response.json()
        for key in self.AGENTRUN_REQUIRED_KEYS:
            assert key in data, f"Missing key '{key}' in agent run response (frontend AgentRun)"
        # Type assertions
        assert isinstance(data["id"], str), "AgentRun.id must be str (UUID)"
        assert isinstance(data["application_id"], str), "application_id must be str"
        assert isinstance(data["status"], str), "status must be str"
        assert isinstance(data["steps"], list), "steps must be list (frontend AgentStep[])"
        assert isinstance(data["bias_reports"], list), "bias_reports must be list"
        assert isinstance(data["next_best_offers"], list), "next_best_offers must be list"
        assert isinstance(data["marketing_emails"], list), "marketing_emails must be list"

    def test_agent_run_bias_report_shape(self, auth_admin_client, agent_run_with_data, sample_application):
        """Bias reports in agent run must match frontend BiasReport interface."""
        response = auth_admin_client.get(f"/api/v1/agents/runs/{sample_application.pk}/")
        data = response.json()
        assert len(data["bias_reports"]) > 0, "Expected at least one bias report"
        br = data["bias_reports"][0]
        bias_report_keys = {
            "id",
            "report_type",
            "bias_score",
            "categories",
            "analysis",
            "flagged",
            "requires_human_review",
            "created_at",
        }
        for key in bias_report_keys:
            assert key in br, f"Missing key '{key}' in bias report (frontend BiasReport)"
        assert isinstance(br["bias_score"], (int, float)), "bias_score must be numeric"
        assert isinstance(br["categories"], list), "categories must be list (frontend string[])"
        assert isinstance(br["flagged"], bool), "flagged must be bool"

    def test_agent_run_nbo_shape(self, auth_admin_client, agent_run_with_data, sample_application):
        """Next best offers must match frontend NextBestOffer interface."""
        response = auth_admin_client.get(f"/api/v1/agents/runs/{sample_application.pk}/")
        data = response.json()
        assert len(data["next_best_offers"]) > 0, "Expected at least one NBO"
        nbo = data["next_best_offers"][0]
        nbo_keys = {
            "id",
            "offers",
            "analysis",
            "customer_retention_score",
            "loyalty_factors",
            "personalized_message",
            "created_at",
        }
        for key in nbo_keys:
            assert key in nbo, f"Missing key '{key}' in NBO (frontend NextBestOffer)"
        assert isinstance(nbo["offers"], list), "offers must be list (frontend AlternativeOffer[])"
        assert isinstance(nbo["loyalty_factors"], list), "loyalty_factors must be list"
        assert isinstance(nbo["customer_retention_score"], (int, float)), "customer_retention_score must be numeric"

    def test_agent_run_marketing_email_shape(self, auth_admin_client, agent_run_with_data, sample_application):
        """Marketing emails must match frontend MarketingEmail interface."""
        response = auth_admin_client.get(f"/api/v1/agents/runs/{sample_application.pk}/")
        data = response.json()
        assert len(data["marketing_emails"]) > 0, "Expected at least one marketing email"
        me = data["marketing_emails"][0]
        me_keys = {
            "id",
            "subject",
            "body",
            "passed_guardrails",
            "guardrail_results",
            "generation_time_ms",
            "attempt_number",
            "created_at",
        }
        for key in me_keys:
            assert key in me, f"Missing key '{key}' in marketing email (frontend MarketingEmail)"
        assert isinstance(me["passed_guardrails"], bool), "passed_guardrails must be bool"
        assert isinstance(me["guardrail_results"], list), "guardrail_results must be list"
        assert isinstance(me["attempt_number"], int), "attempt_number must be int"

    def test_agent_run_step_shape(self, auth_admin_client, agent_run_with_data, sample_application):
        """Steps in agent run must match frontend AgentStep interface."""
        response = auth_admin_client.get(f"/api/v1/agents/runs/{sample_application.pk}/")
        data = response.json()
        assert len(data["steps"]) > 0, "Expected at least one step"
        step = data["steps"][0]
        step_keys = {"step_name", "status"}
        for key in step_keys:
            assert key in step, f"Missing key '{key}' in step (frontend AgentStep)"
        assert isinstance(step["step_name"], str), "step_name must be str"
        assert isinstance(step["status"], str), "status must be str"

    def test_agent_run_404_when_none(self, auth_admin_client, sample_application):
        """GET /api/v1/agents/runs/{loan_id}/ returns 404 when no run exists."""
        response = auth_admin_client.get(f"/api/v1/agents/runs/{sample_application.pk}/")
        assert response.status_code == 404
        data = response.json()
        assert "error" in data, "404 response must have 'error' key"

    def test_agent_run_list_shape(self, auth_admin_client, agent_run_with_data):
        """GET /api/v1/agents/runs/ must return PaginatedResponse shape."""
        response = auth_admin_client.get("/api/v1/agents/runs/")
        assert response.status_code == 200
        data = response.json()
        assert "results" in data, "List must have 'results' (frontend PaginatedResponse)"
        assert "count" in data, "List must have 'count' (frontend PaginatedResponse)"
        assert isinstance(data["results"], list), "results must be a list"
        assert isinstance(data["count"], int), "count must be int"
        if data["results"]:
            item = data["results"][0]
            for key in self.AGENTRUN_REQUIRED_KEYS:
                assert key in item, f"Missing key '{key}' in agent run list item (frontend AgentRun)"


# ---------------------------------------------------------------------------
# Model Versions List Contract Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestModelVersionListContracts:
    """Verify model version list endpoint shape."""

    def test_model_list_shape(self, auth_admin_client, db):
        """GET /api/v1/ml/models/ must return {models: [...]}."""
        import os

        models_dir = str(settings.ML_MODELS_DIR)
        os.makedirs(models_dir, exist_ok=True)
        dummy_path = os.path.join(models_dir, "list_test_model.joblib")
        with open(dummy_path, "wb") as f:
            f.write(b"dummy")
        ModelVersion.objects.create(
            algorithm="xgb",
            version="list-test-v1",
            file_path=dummy_path,
            is_active=True,
            accuracy=0.85,
            auc_roc=0.90,
        )
        response = auth_admin_client.get("/api/v1/ml/models/")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data, "Must have 'models' key"
        assert isinstance(data["models"], list), "models must be a list"
        if data["models"]:
            m = data["models"][0]
            for key in ("id", "algorithm", "version", "is_active", "auc_roc", "created_at"):
                assert key in m, f"Missing key '{key}' in model version list item"


# ---------------------------------------------------------------------------
# Auth Endpoint Access Control Contracts
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAccessControlContracts:
    """Verify that protected endpoints require authentication."""

    def test_loans_requires_auth(self, api_client):
        """GET /api/v1/loans/ must return 401 for unauthenticated requests."""
        response = api_client.get("/api/v1/loans/")
        assert response.status_code == 401, "Loans list must require authentication"

    def test_me_requires_auth(self, api_client):
        """GET /api/v1/auth/me/ must return 401 for unauthenticated requests."""
        response = api_client.get("/api/v1/auth/me/")
        assert response.status_code == 401, "/me/ must require authentication"

    def test_metrics_requires_auth(self, api_client):
        """GET /api/v1/ml/models/active/metrics/ must return 401 for unauthenticated."""
        response = api_client.get("/api/v1/ml/models/active/metrics/")
        assert response.status_code == 401, "Metrics must require authentication"

    def test_agent_runs_requires_auth(self, api_client):
        """GET /api/v1/agents/runs/ must return 401 for unauthenticated."""
        response = api_client.get("/api/v1/agents/runs/")
        assert response.status_code == 401, "Agent runs must require authentication"
