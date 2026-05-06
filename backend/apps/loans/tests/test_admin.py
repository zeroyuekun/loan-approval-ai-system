"""Admin behaviour for LoanApplicationAdmin.

Covers the save_model override that:
  1. Defaults applicant to request.user when blank (so admins don't see
     "No email found for this application" after admin-creating an app).
  2. Enqueues orchestrate_pipeline_task on create only (not on update),
     mirroring loans/views.py:73 perform_create.
  3. Falls back to PipelineDispatchOutbox + warning message when Celery is
     unavailable, so the admin save itself never fails.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from apps.loans.admin import LoanApplicationAdmin
from apps.loans.models import LoanApplication, PipelineDispatchOutbox

User = get_user_model()


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="admin_test",
        password="test1234",
        email="admin@aussieloanai.test",
        role="admin",
    )


@pytest.fixture
def explicit_applicant(db):
    return User.objects.create_user(
        username="customer_test",
        password="test1234",
        email="customer@example.test",
        role="customer",
    )


@pytest.fixture
def admin_request(admin_user):
    """Fake admin request with messages middleware so messages.success/warning work."""
    rf = RequestFactory()
    req = rf.post("/admin/loans/loanapplication/add/")
    req.user = admin_user
    req.session = {}
    req._messages = FallbackStorage(req)
    return req


def _make_app(applicant=None, **overrides):
    defaults = dict(
        annual_income=80000,
        credit_score=720,
        loan_amount=25000,
        loan_term_months=36,
        debt_to_income=2.5,
        employment_length=5,
        purpose="personal",
        home_ownership="rent",
        status="pending",
    )
    defaults.update(overrides)
    return LoanApplication(applicant=applicant, **defaults)


def _admin():
    return LoanApplicationAdmin(LoanApplication, AdminSite())


def test_save_model_defaults_applicant_to_request_user_when_blank(admin_request, admin_user):
    """When admin creates an app without picking an applicant, default to themselves."""
    app = _make_app(applicant=None)
    with patch("apps.agents.tasks.orchestrate_pipeline_task") as mock_task:
        _admin().save_model(admin_request, app, form=None, change=False)
        mock_task.delay.assert_not_called()  # on_commit hasn't fired in test transaction

    app.refresh_from_db()
    assert app.applicant_id == admin_user.id


def test_save_model_does_not_override_explicit_applicant(admin_request, explicit_applicant):
    """If the admin picked a real applicant, that selection wins."""
    app = _make_app(applicant=explicit_applicant)
    with patch("apps.agents.tasks.orchestrate_pipeline_task"):
        _admin().save_model(admin_request, app, form=None, change=False)

    app.refresh_from_db()
    assert app.applicant_id == explicit_applicant.id


def test_save_model_enqueues_pipeline_on_create(admin_request, admin_user):
    """On create (change=False), orchestrate_pipeline_task is scheduled via on_commit."""
    app = _make_app(applicant=admin_user)
    with (
        patch("apps.agents.tasks.orchestrate_pipeline_task") as mock_task,
        patch("apps.loans.admin.transaction.on_commit", side_effect=lambda fn: fn()),
    ):
        _admin().save_model(admin_request, app, form=None, change=False)
        mock_task.delay.assert_called_once_with(str(app.pk))


def test_save_model_does_not_enqueue_on_update(admin_request, admin_user):
    """On update (change=True), no pipeline dispatch."""
    app = _make_app(applicant=admin_user)
    app.save()

    with (
        patch("apps.agents.tasks.orchestrate_pipeline_task") as mock_task,
        patch("apps.loans.admin.transaction.on_commit", side_effect=lambda fn: fn()),
    ):
        _admin().save_model(admin_request, app, form=None, change=True)
        mock_task.delay.assert_not_called()


def test_save_model_handles_celery_failure_gracefully(admin_request, admin_user):
    """If orchestrate_pipeline_task.delay() blows up, save still succeeds and
    application is queued in PipelineDispatchOutbox for retry."""
    app = _make_app(applicant=admin_user)
    mock_task = MagicMock()
    mock_task.delay.side_effect = ConnectionError("broker down")

    with (
        patch("apps.agents.tasks.orchestrate_pipeline_task", mock_task),
        patch("apps.loans.admin.transaction.on_commit", side_effect=lambda fn: fn()),
    ):
        _admin().save_model(admin_request, app, form=None, change=False)

    # App is saved
    assert LoanApplication.objects.filter(pk=app.pk).exists()
    # Outbox row exists for retry
    assert PipelineDispatchOutbox.objects.filter(application=app).exists()


def test_get_form_marks_applicant_optional_on_create(admin_request, admin_user):
    """The admin add form should accept an empty applicant field (we'll default it)."""
    form_class = _admin().get_form(admin_request, obj=None)
    assert form_class.base_fields["applicant"].required is False


def test_get_form_keeps_applicant_required_on_change(admin_request, admin_user):
    """When editing an existing application, the applicant field stays as model-defined."""
    app = _make_app(applicant=admin_user)
    app.save()
    form_class = _admin().get_form(admin_request, obj=app)
    # On the change form we don't override required — model has applicant as required FK
    assert form_class.base_fields["applicant"].required is True


def test_save_model_warns_when_applicant_has_no_email(admin_request, db):
    """If the resolved applicant has no email, surface a warning so admin knows."""
    no_email_user = User.objects.create_user(
        username="noemail",
        password="test1234",
        email="",  # explicitly empty
        role="customer",
    )
    app = _make_app(applicant=no_email_user)
    with (
        patch("apps.agents.tasks.orchestrate_pipeline_task"),
        patch("apps.loans.admin.transaction.on_commit", side_effect=lambda fn: fn()),
    ):
        _admin().save_model(admin_request, app, form=None, change=False)

    messages_storage = list(admin_request._messages)
    assert any("no email on file" in str(m).lower() for m in messages_storage)
