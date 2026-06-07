"""L13/L14: DRF serializers for AgentRun replace the hand-built view dicts.

The serialized output must be byte-equal to the legacy dict shape (UUIDs as
str, timestamps via .isoformat(), computed applicant_id/applicant_name) so the
API contract does not drift. The list variant omits html_body (L14: avoid
re-rendering the 1k-LOC regex renderer per row in the paginated hot path); the
detail variant keeps it.
"""

import pytest

from apps.agents.models import AgentRun, BiasReport, MarketingEmail, NextBestOffer
from apps.agents.serializers import AgentRunSerializer
from apps.email_engine.services.html_renderer import render_html
from apps.loans.models import LoanApplication

pytestmark = pytest.mark.django_db


@pytest.fixture
def customer(django_user_model):
    return django_user_model.objects.create_user(
        username="ser_customer",
        email="ser@example.com",
        password="x",
        first_name="Jane",
        last_name="Doe",
        role="customer",
    )


@pytest.fixture
def populated_run(customer):
    app = LoanApplication.objects.create(
        applicant=customer,
        annual_income=90000,
        loan_amount=300000,
        loan_term_months=360,
        credit_score=720,
        employment_length=5,
        debt_to_income=0.25,
        purpose="home",
        home_ownership="rent",
        has_cosigner=False,
        status="denied",
    )
    run = AgentRun.objects.create(application=app, status=AgentRun.Status.COMPLETED, steps=[{"x": 1}])
    BiasReport.objects.create(
        agent_run=run,
        report_type="decision",
        bias_score=70,
        deterministic_score=65,
        score_source="hybrid",
        categories=["gender"],
        analysis="ok",
        flagged=False,
        requires_human_review=False,
    )
    NextBestOffer.objects.create(
        agent_run=run,
        application=app,
        offers=[{"name": "x"}],
        analysis="a",
        customer_retention_score=0.8,
        loyalty_factors=["tenure"],
        personalized_message="hi",
        marketing_message="promo",
    )
    MarketingEmail.objects.create(
        agent_run=run,
        application=app,
        subject="S",
        body="Hello body",
        passed_guardrails=True,
        guardrail_results={},
        generation_time_ms=10,
        attempt_number=1,
    )
    return run


_TOP_LEVEL_KEYS = {
    "id",
    "application_id",
    "applicant_id",
    "applicant_name",
    "status",
    "steps",
    "total_time_ms",
    "error",
    "bias_reports",
    "next_best_offers",
    "marketing_emails",
    "created_at",
    "updated_at",
}

_BIAS_KEYS = {
    "id",
    "report_type",
    "bias_score",
    "deterministic_score",
    "score_source",
    "categories",
    "analysis",
    "flagged",
    "requires_human_review",
    "ai_review_approved",
    "ai_review_reasoning",
    "created_at",
}


def test_serializer_has_all_legacy_fields(populated_run):
    data = AgentRunSerializer(populated_run, context={"include_html": True}).data
    assert set(data.keys()) == _TOP_LEVEL_KEYS


def test_id_and_application_id_are_strings(populated_run):
    data = AgentRunSerializer(populated_run, context={"include_html": True}).data
    assert data["id"] == str(populated_run.id)
    assert data["application_id"] == str(populated_run.application_id)
    assert data["created_at"] == populated_run.created_at.isoformat()
    assert data["updated_at"] == populated_run.updated_at.isoformat()


def test_applicant_name_computed(populated_run):
    data = AgentRunSerializer(populated_run, context={"include_html": True}).data
    assert data["applicant_name"] == "Jane Doe"
    assert data["applicant_id"] == populated_run.application.applicant.id


def test_bias_report_fields(populated_run):
    data = AgentRunSerializer(populated_run, context={"include_html": True}).data
    assert len(data["bias_reports"]) == 1
    assert set(data["bias_reports"][0].keys()) == _BIAS_KEYS
    br = populated_run.bias_reports.first()
    assert data["bias_reports"][0]["id"] == str(br.id)
    assert data["bias_reports"][0]["created_at"] == br.created_at.isoformat()


def test_list_marketing_email_omits_html_body(populated_run):
    data = AgentRunSerializer(populated_run, context={"include_html": False}).data
    assert len(data["marketing_emails"]) == 1
    assert "html_body" not in data["marketing_emails"][0]


def test_detail_marketing_email_includes_html_body(populated_run):
    data = AgentRunSerializer(populated_run, context={"include_html": True}).data
    me = populated_run.marketing_emails.first()
    assert data["marketing_emails"][0]["html_body"] == render_html(me.body, email_type="marketing")
