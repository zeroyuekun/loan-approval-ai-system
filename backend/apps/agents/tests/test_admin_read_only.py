"""Pipeline records are view-only in the Django admin.

AgentRun.status, BiasReport.flagged and its scores, and the generated
decision email (body, subject, guardrail results, sent_at) are evidence of
what the pipeline did. Editing them in the admin bypassed the state machine
and the audit trail (an admin could clear a bias flag, or mark an unsent
email sent). They change only through the pipeline and the audited human
review, mirroring LoanDecisionAdmin.
"""

import pytest
from django.contrib import admin
from django.test import RequestFactory

from apps.accounts.models import CustomUser
from apps.agents.models import AgentRun, BiasReport
from apps.email_engine.models import GeneratedEmail, GuardrailLog

pytestmark = pytest.mark.django_db


@pytest.fixture
def superuser_request():
    user = CustomUser.objects.create_superuser(username="root_admin", email="root@x.com", password="x")
    request = RequestFactory().get("/admin/")
    request.user = user
    return request


@pytest.mark.parametrize("model", [AgentRun, BiasReport, GeneratedEmail, GuardrailLog])
def test_pipeline_records_are_view_only_even_for_a_superuser(model, superuser_request):
    model_admin = admin.site._registry[model]
    assert model_admin.has_view_permission(superuser_request)
    assert not model_admin.has_add_permission(superuser_request)
    assert not model_admin.has_change_permission(superuser_request)
    assert not model_admin.has_delete_permission(superuser_request)
