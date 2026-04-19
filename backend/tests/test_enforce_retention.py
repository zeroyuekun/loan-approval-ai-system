"""Regression tests for the `enforce_retention` management command.

Covers the boundary semantics of the command as the documented retention
policy is the source of truth for AU regulatory compliance
(AML/CTF Act 2006, APRA CPG 235, Privacy Act APP 11.2). A silent
regression that either over-deletes (data-loss incident) or
under-deletes (compliance breach) is equally bad, so we pin the
behaviour explicitly at the cutoff boundaries.
"""

from datetime import timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.conf import settings as django_settings
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.models import CustomerProfile, CustomUser
from apps.loans.models import AuditLog, LoanApplication
from apps.ml_engine.models import DriftReport, ModelVersion, PredictionLog

SOFT_DELETE_DAYS = 90
PREDICTION_DAYS = 5 * 365
DRIFT_DAYS = 3 * 365


@pytest.fixture
def retention_user(db):
    return CustomUser.objects.create_user(
        username="retention_test",
        email="retention@test.com",
        password="testpass123",
        role="customer",
    )


@pytest.fixture
def retention_mv(db):
    return ModelVersion.objects.create(
        algorithm="rf",
        version="retention-test-v1",
        file_path=str(django_settings.ML_MODELS_DIR / "retention_test.joblib"),
        is_active=False,
    )


def _mk_application(user, deleted_days_ago: int | None) -> LoanApplication:
    app = LoanApplication.objects.create(
        applicant=user,
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
    )
    if deleted_days_ago is not None:
        app.deleted_at = timezone.now() - timedelta(days=deleted_days_ago)
        app.save(update_fields=["deleted_at"])
    return app


def _mk_prediction(mv, app, days_ago: int) -> PredictionLog:
    pl = PredictionLog.objects.create(
        model_version=mv,
        application=app,
        prediction="approved",
        probability=0.8,
        feature_importances={},
    )
    # `created_at` has auto_now_add=True so backdate via queryset.update()
    # to bypass the auto-set.
    PredictionLog.objects.filter(pk=pl.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
    pl.refresh_from_db()
    return pl


def _mk_drift(mv, days_ago: int) -> DriftReport:
    report_date = (timezone.now() - timedelta(days=days_ago)).date()
    dr = DriftReport.objects.create(
        model_version=mv,
        report_date=report_date,
        period_start=report_date - timedelta(days=7),
        period_end=report_date,
        num_predictions=100,
    )
    DriftReport.objects.filter(pk=dr.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
    dr.refresh_from_db()
    return dr


@pytest.mark.django_db(transaction=True)
class TestEnforceRetention:
    def test_dry_run_makes_no_changes(self, retention_user, retention_mv):
        """`--dry-run` must not touch the database even with expired rows."""
        expired_app = _mk_application(retention_user, deleted_days_ago=SOFT_DELETE_DAYS + 10)
        _mk_prediction(retention_mv, expired_app, days_ago=PREDICTION_DAYS + 10)
        _mk_drift(retention_mv, days_ago=DRIFT_DAYS + 10)

        before_apps = LoanApplication.all_objects.dead().count()
        before_preds = PredictionLog.objects.count()
        before_drift = DriftReport.objects.count()
        before_audits = AuditLog.objects.count()

        out = StringIO()
        call_command("enforce_retention", "--dry-run", stdout=out)

        assert LoanApplication.all_objects.dead().count() == before_apps
        assert PredictionLog.objects.count() == before_preds
        assert DriftReport.objects.count() == before_drift
        # Dry-run must not emit retention audit log rows
        assert AuditLog.objects.count() == before_audits
        assert "DRY RUN" in out.getvalue()

    def test_purges_past_soft_delete_cutoff(self, retention_user, retention_mv):
        """Soft-deleted rows older than 90 days get physically purged."""
        expired = _mk_application(retention_user, deleted_days_ago=SOFT_DELETE_DAYS + 5)
        fresh = _mk_application(retention_user, deleted_days_ago=SOFT_DELETE_DAYS - 5)
        active = _mk_application(retention_user, deleted_days_ago=None)

        call_command("enforce_retention", stdout=StringIO())

        # Expired soft-deleted row is physically gone
        assert not LoanApplication.all_objects.all_with_deleted().filter(pk=expired.pk).exists()
        # Fresh soft-deleted row survives
        assert LoanApplication.all_objects.all_with_deleted().filter(pk=fresh.pk).exists()
        # Active row untouched
        assert LoanApplication.objects.filter(pk=active.pk).exists()

    def test_boundary_exactly_at_cutoff_is_not_purged(self, retention_user):
        """A row deleted exactly 90 days ago is on the boundary — cutoff
        uses strict `<` comparison (`deleted_at__lt=cutoff`), so an
        *exact-match* row should survive. This pins the inequality
        direction so a future refactor can't silently flip it."""
        # Set deleted_at to ~89.9 days ago; strict-lt cutoff is 90d ago,
        # so this row is newer than cutoff and must survive.
        fresh = _mk_application(retention_user, deleted_days_ago=SOFT_DELETE_DAYS - 1)
        call_command("enforce_retention", stdout=StringIO())
        assert LoanApplication.all_objects.all_with_deleted().filter(pk=fresh.pk).exists()

    def test_archives_old_prediction_logs(self, retention_user, retention_mv):
        """PredictionLog rows older than 5 years get archived (deleted)."""
        active_app = _mk_application(retention_user, deleted_days_ago=None)
        old_pred = _mk_prediction(retention_mv, active_app, days_ago=PREDICTION_DAYS + 10)
        fresh_pred = _mk_prediction(retention_mv, active_app, days_ago=PREDICTION_DAYS - 10)

        call_command("enforce_retention", stdout=StringIO())

        assert not PredictionLog.objects.filter(pk=old_pred.pk).exists()
        assert PredictionLog.objects.filter(pk=fresh_pred.pk).exists()

    def test_archives_old_drift_reports(self, retention_mv):
        """DriftReport rows older than 3 years get archived (deleted)."""
        old_drift = _mk_drift(retention_mv, days_ago=DRIFT_DAYS + 10)
        fresh_drift = _mk_drift(retention_mv, days_ago=DRIFT_DAYS - 10)

        call_command("enforce_retention", stdout=StringIO())

        assert not DriftReport.objects.filter(pk=old_drift.pk).exists()
        assert DriftReport.objects.filter(pk=fresh_drift.pk).exists()

    def test_emits_audit_log_rows_on_purge(self, retention_user, retention_mv):
        """Every purge/archive operation leaves an AuditLog row behind."""
        _mk_application(retention_user, deleted_days_ago=SOFT_DELETE_DAYS + 10)
        active_app = _mk_application(retention_user, deleted_days_ago=None)
        _mk_prediction(retention_mv, active_app, days_ago=PREDICTION_DAYS + 10)
        _mk_drift(retention_mv, days_ago=DRIFT_DAYS + 10)

        before = AuditLog.objects.filter(action__startswith="retention_").count()
        call_command("enforce_retention", stdout=StringIO())
        after = AuditLog.objects.filter(action__startswith="retention_").count()

        assert after - before >= 2, (
            "Expected at least 2 retention_* audit rows (1 purge + 1 archive); "
            f"got {after - before}"
        )

        latest = AuditLog.objects.filter(action__startswith="retention_").order_by("-timestamp").first()
        assert latest is not None
        assert latest.details["count"] >= 1
        assert "cutoff" in latest.details
        assert "policy" in latest.details

    def test_no_expired_rows_no_changes(self, retention_user, retention_mv):
        """With only fresh data, the command is a no-op and emits no audit rows."""
        _mk_application(retention_user, deleted_days_ago=SOFT_DELETE_DAYS - 10)
        _mk_application(retention_user, deleted_days_ago=None)
        active_app = _mk_application(retention_user, deleted_days_ago=None)
        _mk_prediction(retention_mv, active_app, days_ago=PREDICTION_DAYS - 10)
        _mk_drift(retention_mv, days_ago=DRIFT_DAYS - 10)

        before_audits = AuditLog.objects.filter(action__startswith="retention_").count()
        call_command("enforce_retention", stdout=StringIO())
        after_audits = AuditLog.objects.filter(action__startswith="retention_").count()

        assert after_audits == before_audits

    def test_purges_customer_profile_soft_deletes(self, retention_user):
        """CustomerProfile soft-deletes are purged on the same schedule."""
        # The signal on CustomUser creation may or may not create a profile;
        # make sure we have a fresh one we control. Only set fields that
        # actually exist on the model — PII fields are encrypted and have
        # sensible blank defaults.
        CustomerProfile.objects.filter(user=retention_user).delete()
        profile = CustomerProfile.objects.create(
            user=retention_user,
            phone="0400000000",
            state="NSW",
            postcode="2000",
        )
        profile.deleted_at = timezone.now() - timedelta(days=SOFT_DELETE_DAYS + 5)
        profile.save(update_fields=["deleted_at"])

        call_command("enforce_retention", stdout=StringIO())

        assert not CustomerProfile.all_objects.all_with_deleted().filter(pk=profile.pk).exists()
