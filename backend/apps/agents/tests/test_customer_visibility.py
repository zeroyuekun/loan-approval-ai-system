"""I5 — the customer role sees only what was actually issued to them.

Withheld (guardrail-failed or bias-held) decision-email drafts and internal
agent-run artefacts (bias analyses, NBO retention strategy and score, blocked
marketing drafts, raw step errors) are staff-only.
"""

from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.agents.models import AgentRun, BiasReport, MarketingEmail, NextBestOffer
from apps.email_engine.models import GeneratedEmail, GuardrailLog
from apps.loans.models import LoanApplication

pytestmark = pytest.mark.django_db


@pytest.fixture
def customer():
    return CustomUser.objects.create_user(username="vis_customer", password="x", role="customer", email="c@x.com")


@pytest.fixture
def officer():
    return CustomUser.objects.create_user(username="vis_officer", password="x", role="officer")


@pytest.fixture
def application(customer):
    return LoanApplication.objects.create(
        applicant=customer,
        annual_income=Decimal("75000"),
        credit_score=700,
        loan_amount=Decimal("20000"),
        loan_term_months=36,
        debt_to_income=Decimal("1.5"),
        employment_length=4,
        purpose="personal",
        home_ownership="rent",
        has_cosigner=False,
        status="denied",
    )


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _email(application, *, passed, sent):
    email = GeneratedEmail.objects.create(
        application=application,
        decision="denied",
        subject="Withheld draft" if not sent else "Your application",
        body="draft body with a hallucinated 12.99% rate" if not sent else "issued body",
        prompt_used="p",
        passed_guardrails=passed,
        sent_at=timezone.now() if sent else None,
    )
    GuardrailLog.objects.create(email=email, check_name="hallucinated_numbers", passed=passed, details="12.99%")
    return email


@pytest.fixture
def run_with_internals(application):
    run = AgentRun.objects.create(
        application=application,
        status=AgentRun.Status.COMPLETED,
        error="Email guardrails failed: hallucinated_numbers",
        steps=[
            {
                "step_name": "bias_check",
                "status": "failed",
                "started_at": "2026-01-01T00:00:00",
                "completed_at": "2026-01-01T00:00:01",
                "result_summary": {"bias_score": 72},
                "error": "anthropic.APIStatusError: 500 internal",
            }
        ],
    )
    BiasReport.objects.create(agent_run=run, bias_score=72, categories=["age"], analysis="internal", flagged=True)
    NextBestOffer.objects.create(
        agent_run=run,
        application=application,
        offers=[{"name": "Secured loan", "amount": 10000}],
        analysis="retention strategy: high churn risk",
        customer_retention_score=31,
        loyalty_factors=["tenure"],
        personalized_message="hi",
    )
    MarketingEmail.objects.create(
        agent_run=run, application=application, subject="Blocked", body="blocked draft", prompt_used="p", sent=False
    )
    MarketingEmail.objects.create(
        agent_run=run,
        application=application,
        subject="Sent offer",
        body="sent body",
        prompt_used="p",
        passed_guardrails=True,
        sent=True,
        sent_at=timezone.now(),
    )
    return run


def test_customer_cannot_read_withheld_email(customer, application):
    _email(application, passed=False, sent=False)
    resp = _client(customer).get(f"/api/v1/emails/{application.id}/")
    assert resp.status_code == 404


def test_customer_cannot_read_unsent_passing_draft(customer, application):
    """Passing but never sent (e.g. held by the bias check) is still a draft."""
    _email(application, passed=True, sent=False)
    resp = _client(customer).get(f"/api/v1/emails/{application.id}/")
    assert resp.status_code == 404


def test_customer_sees_issued_email_without_guardrail_internals(customer, application):
    _email(application, passed=True, sent=True)
    _email(application, passed=False, sent=False)  # newer withheld draft must not shadow it
    resp = _client(customer).get(f"/api/v1/emails/{application.id}/")
    assert resp.status_code == 200
    assert resp.data["body"] == "issued body"
    assert resp.data["guardrail_checks"] == []


def test_customer_email_list_excludes_unsent(customer, application):
    _email(application, passed=True, sent=True)
    _email(application, passed=False, sent=False)
    resp = _client(customer).get("/api/v1/emails/")
    assert resp.status_code == 200
    assert [r["subject"] for r in resp.data["results"]] == ["Your application"]


def test_staff_still_sees_withheld_email(officer, application):
    _email(application, passed=False, sent=False)
    resp = _client(officer).get(f"/api/v1/emails/{application.id}/")
    assert resp.status_code == 200
    assert resp.data["guardrail_checks"][0]["details"] == "12.99%"


def _assert_customer_safe(run_data):
    assert run_data["bias_reports"] == []
    assert run_data["error"] in (None, "")
    for offer in run_data["next_best_offers"]:
        assert "analysis" not in offer
        assert "customer_retention_score" not in offer
        assert "loyalty_factors" not in offer
        assert offer["offers"] == [{"name": "Secured loan", "amount": 10000}]
    assert [m["subject"] for m in run_data["marketing_emails"]] == ["Sent offer"]
    for m in run_data["marketing_emails"]:
        assert "guardrail_results" not in m
    for step in run_data["steps"]:
        assert step.get("error") is None
        assert not step.get("result_summary")
        assert step["step_name"] == "bias_check"


def test_customer_agent_run_detail_hides_internals(customer, application, run_with_internals):
    resp = _client(customer).get(f"/api/v1/agents/runs/{application.id}/")
    assert resp.status_code == 200
    _assert_customer_safe(resp.data)


def test_customer_agent_run_list_hides_internals(customer, application, run_with_internals):
    resp = _client(customer).get("/api/v1/agents/runs/")
    assert resp.status_code == 200
    assert len(resp.data["results"]) == 1
    _assert_customer_safe(resp.data["results"][0])


def test_staff_agent_run_keeps_internals(officer, application, run_with_internals):
    resp = _client(officer).get(f"/api/v1/agents/runs/{application.id}/")
    assert resp.status_code == 200
    assert resp.data["bias_reports"][0]["analysis"] == "internal"
    assert resp.data["next_best_offers"][0]["customer_retention_score"] == 31
    assert len(resp.data["marketing_emails"]) == 2
    assert resp.data["steps"][0]["error"].startswith("anthropic")
