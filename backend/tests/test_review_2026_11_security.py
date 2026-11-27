"""Security fixes from the 2026-11-22 senior review."""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CustomUser

REFRESH_URL = "/api/v1/auth/refresh/"


def _customer(username, **extra):
    return CustomUser.objects.create_user(
        username=username, password="CorrectHorse-Battery-9", role="customer", **extra
    )


# --- Token refresh (login CSRF, inactive users) ---------------------------


@pytest.mark.django_db
def test_refresh_rejects_form_encoded_body():
    """A cross-site HTML form cannot send JSON, so a form post must be refused."""
    token = str(RefreshToken.for_user(_customer("rf_form")))
    resp = APIClient().post(REFRESH_URL, {"refresh": token}, format="multipart")
    assert resp.status_code == 415


@pytest.mark.django_db
def test_refresh_accepts_json_body():
    token = str(RefreshToken.for_user(_customer("rf_json")))
    resp = APIClient().post(REFRESH_URL, {"refresh": token}, format="json")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_refresh_rejects_inactive_user():
    user = _customer("rf_inactive")
    token = str(RefreshToken.for_user(user))
    user.is_active = False
    user.save(update_fields=["is_active"])
    resp = APIClient().post(REFRESH_URL, {"refresh": token}, format="json")
    assert resp.status_code == 401


# --- APP 12 export -------------------------------------------------------
# (covered in tests/test_data_export.py: sent-only emails, customer run view)


# --- Abuse limits ----------------------------------------------------------


def _clone_application(app, status):
    app.pk = None
    app.id = None
    app.status = status
    app.save()
    return app


@pytest.mark.django_db
def test_open_application_cap(sample_application, settings):
    from rest_framework.exceptions import ValidationError

    from apps.loans.views import _refuse_if_too_many_open

    settings.MAX_OPEN_APPLICATIONS_PER_CUSTOMER = 3
    user = sample_application.applicant
    sample_application.status = "pending"
    sample_application.save(update_fields=["status"])
    _clone_application(sample_application, "processing")
    _clone_application(sample_application, "approved")  # decided: does not count
    _clone_application(sample_application, "denied")  # decided: does not count
    _refuse_if_too_many_open(user)  # 2 open: allowed

    _clone_application(sample_application, "review")
    with pytest.raises(ValidationError):
        _refuse_if_too_many_open(user)  # 3 open: refused


def test_loan_create_has_its_own_throttle():
    from apps.loans.views import LoanApplicationViewSet, LoanCreateThrottle

    view = LoanApplicationViewSet()
    view.action = "create"
    assert any(isinstance(t, LoanCreateThrottle) for t in view.get_throttles())
    view.action = "list"
    assert not any(isinstance(t, LoanCreateThrottle) for t in view.get_throttles())


def test_orchestration_and_email_throttles_have_own_scope():
    from apps.agents.views import OrchestrationThrottle
    from apps.email_engine.views import EmailGenerationThrottle

    assert OrchestrationThrottle.scope == "orchestration"
    assert EmailGenerationThrottle.scope == "email_generation"


@pytest.mark.django_db
@pytest.mark.parametrize("url", ["/api/v1/agents/runs/?page=0", "/api/v1/emails/?page=-3"])
def test_non_positive_page_is_clamped(url):
    client = APIClient()
    client.force_authenticate(user=_customer("pager"))
    assert client.get(url).status_code == 200


# --- Request IDs, log redaction ---------------------------------------------------


@pytest.mark.django_db
def test_untrusted_request_id_is_replaced():
    resp = APIClient().get("/api/v1/health/", HTTP_X_REQUEST_ID="<script>" + "a" * 200)
    rid = resp["X-Request-ID"]
    assert "<" not in rid and len(rid) == 32


@pytest.mark.django_db
def test_plain_request_id_is_echoed():
    resp = APIClient().get("/api/v1/health/", HTTP_X_REQUEST_ID="abc-123")
    assert resp["X-Request-ID"] == "abc-123"


def test_pii_filter_redacts_exception_args_and_tracebacks():
    import logging

    from config.logging_filters import PiiMaskingFilter

    try:
        raise ValueError("could not mail jane@example.com")
    except ValueError as exc:
        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "send failed: %s", (exc,), exc_info=True)
        record.exc_info = __import__("sys").exc_info()
    PiiMaskingFilter().filter(record)
    assert "jane@example.com" not in record.getMessage()
    assert "jane@example.com" not in record.exc_text
    assert "[EMAIL_REDACTED]" in record.exc_text


def test_pii_filter_keeps_numeric_args():
    import logging

    from config.logging_filters import PiiMaskingFilter

    record = logging.LogRecord("t", logging.INFO, __file__, 1, "count=%d ratio=%.1f", (3, 0.5), None)
    PiiMaskingFilter().filter(record)
    assert record.getMessage() == "count=3 ratio=0.5"


def test_dockerignore_excludes_env_files():
    from pathlib import Path

    backend_root = Path(__file__).resolve().parents[1]
    rules = (backend_root / ".dockerignore").read_text().splitlines()
    assert ".env" in rules and ".env.*" in rules
