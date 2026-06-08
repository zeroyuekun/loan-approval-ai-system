"""L22 — single locked stuck-state remediation.

The watchdog (SIGKILL + reset), the orchestrator stale-reset, and Celery
autoretry all mutate the same application/AgentRun state.
``_cleanup_stuck_application`` must lock the application by pk, no-op when a
newer AgentRun already owns the work, and clear the dedup lock on revoke so a
legitimate retry is not starved.
"""

from decimal import Decimal

import pytest
from django.test import override_settings

from tests.conftest import skip_without_redis

CACHE_OVERRIDE = override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)


def _make_application(django_user_model, *, status="processing", suffix=""):
    customer = django_user_model.objects.create_user(
        username=f"l22_customer{suffix}",
        email=f"l22_customer{suffix}@test.com",
        password="testpass123",
        role="customer",
        first_name="L22",
        last_name="Customer",
    )
    from apps.loans.models import LoanApplication

    return LoanApplication.objects.create(
        applicant=customer,
        annual_income=Decimal("75000.00"),
        credit_score=720,
        loan_amount=Decimal("25000.00"),
        loan_term_months=36,
        debt_to_income=Decimal("1.50"),
        employment_length=5,
        purpose="personal",
        home_ownership="rent",
        has_cosigner=False,
        monthly_expenses=Decimal("2200.00"),
        existing_credit_card_limit=Decimal("8000.00"),
        number_of_dependants=0,
        employment_type="payg_permanent",
        applicant_type="single",
        has_hecs=False,
        has_bankruptcy=False,
        state="NSW",
        status=status,
    )


@pytest.mark.django_db
def test_cleanup_noops_when_completed_run_exists(django_user_model):
    from apps.agents.models import AgentRun
    from apps.agents.tasks import _cleanup_stuck_application

    app = _make_application(django_user_model, suffix="_completed")
    completed = AgentRun.objects.create(application=app, status=AgentRun.Status.COMPLETED, steps=[])

    _cleanup_stuck_application(str(app.id))

    app.refresh_from_db()
    completed.refresh_from_db()
    # A completed run owns it — cleanup must not stomp the status.
    assert app.status == "processing"
    assert completed.status == AgentRun.Status.COMPLETED


@pytest.mark.django_db
def test_cleanup_resets_when_only_failed_running_runs(django_user_model):
    from apps.agents.models import AgentRun
    from apps.agents.tasks import _cleanup_stuck_application

    app = _make_application(django_user_model, suffix="_running")
    running = AgentRun.objects.create(application=app, status=AgentRun.Status.RUNNING, steps=[])

    _cleanup_stuck_application(str(app.id))

    app.refresh_from_db()
    running.refresh_from_db()
    assert app.status == "review"
    assert running.status == AgentRun.Status.FAILED


@CACHE_OVERRIDE
@skip_without_redis
@pytest.mark.django_db
def test_cleanup_clears_dedup_lock(django_user_model):
    from django.core.cache import cache

    from apps.agents.tasks import _cleanup_stuck_application

    app = _make_application(django_user_model, suffix="_lock")
    lock_key = f"orchestrate_lock:{app.id}"
    cache.add(lock_key, "some-task-id", 600)
    assert cache.get(lock_key) is not None

    _cleanup_stuck_application(str(app.id), clear_lock=True)

    assert cache.get(lock_key) is None
