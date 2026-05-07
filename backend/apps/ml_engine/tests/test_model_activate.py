"""Regression tests for ModelActivateView.

Codex adversarial review (2026-05-07) flagged that this endpoint cleared
``is_active`` across ALL ModelVersion rows before turning the requested model
on. In a deployment with separate personal/home/unified champions, activating
one challenger silently broke scoring for every other segment until an
operator repaired traffic.

These tests pin the post-fix behaviour: activation is segment-scoped (only
models sharing the target segment are deactivated) and emits an AuditLog
entry with the previous active-segment snapshot.

See docs/superpowers/specs/2026-05-07-codex-adversarial-response-v1-10-7-design.md
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.loans.models import AuditLog
from apps.ml_engine.models import ModelVersion

# Inlined fixtures — backend/tests/conftest.py is not on the auto-discovery
# path for tests under backend/apps/ml_engine/tests/.


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user(db):
    return CustomUser.objects.create_user(
        username="admin_activate",
        email="admin_activate@test.com",
        password="x",
        role="admin",
        is_staff=True,
    )


@pytest.fixture
def authed_admin_client(api_client, admin_user):
    api_client.force_authenticate(user=admin_user)
    return api_client


@pytest.fixture
def models_dir(tmp_path, settings):
    """Sandbox ML_MODELS_DIR so ModelVersion.clean() accepts our fixture paths."""
    settings.ML_MODELS_DIR = str(tmp_path)
    return tmp_path


def _make_version(
    *,
    models_dir,
    version: str,
    segment: str,
    is_active: bool = False,
) -> ModelVersion:
    file_path = models_dir / f"{version}.joblib"
    file_path.write_bytes(b"\0" * 64)
    return ModelVersion.objects.create(
        algorithm="xgb",
        version=version,
        file_path=str(file_path),
        file_hash="a" * 64,
        is_active=is_active,
        segment=segment,
        traffic_percentage=100 if is_active else 0,
    )


@pytest.mark.django_db
class TestModelActivateSegmentSafety:
    def test_manual_activate_does_not_touch_other_segments(self, authed_admin_client, models_dir):
        active_personal = _make_version(
            models_dir=models_dir,
            version="v_personal_1",
            segment=ModelVersion.SEGMENT_PERSONAL,
            is_active=True,
        )
        active_home = _make_version(
            models_dir=models_dir,
            version="v_home_1",
            segment=ModelVersion.SEGMENT_HOME_OWNER_OCCUPIER,
            is_active=True,
        )
        active_unified = _make_version(
            models_dir=models_dir,
            version="v_unified_1",
            segment=ModelVersion.SEGMENT_UNIFIED,
            is_active=True,
        )
        challenger = _make_version(
            models_dir=models_dir,
            version="v_personal_2",
            segment=ModelVersion.SEGMENT_PERSONAL,
            is_active=False,
        )

        url = reverse("model-activate", kwargs={"pk": challenger.id})
        response = authed_admin_client.post(url)

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["segment"] == ModelVersion.SEGMENT_PERSONAL
        assert body["model_id"] == str(challenger.id)

        challenger.refresh_from_db()
        active_personal.refresh_from_db()
        active_home.refresh_from_db()
        active_unified.refresh_from_db()

        # Challenger is now the personal champion.
        assert challenger.is_active is True
        assert challenger.traffic_percentage == 100
        # Old personal champion was demoted (same segment).
        assert active_personal.is_active is False
        assert active_personal.traffic_percentage == 0
        # Other segments untouched — this is the fix.
        assert active_home.is_active is True
        assert active_home.traffic_percentage == 100
        assert active_unified.is_active is True
        assert active_unified.traffic_percentage == 100

    def test_manual_activate_first_time_for_segment(self, authed_admin_client, models_dir):
        active_unified = _make_version(
            models_dir=models_dir,
            version="v_unified_1",
            segment=ModelVersion.SEGMENT_UNIFIED,
            is_active=True,
        )
        # No active home model yet — activating the first one should leave
        # unified untouched and turn home on without complaint.
        first_home = _make_version(
            models_dir=models_dir,
            version="v_home_1",
            segment=ModelVersion.SEGMENT_HOME_OWNER_OCCUPIER,
            is_active=False,
        )

        url = reverse("model-activate", kwargs={"pk": first_home.id})
        response = authed_admin_client.post(url)

        assert response.status_code == 200, response.content

        first_home.refresh_from_db()
        active_unified.refresh_from_db()

        assert first_home.is_active is True
        assert active_unified.is_active is True

    def test_manual_activate_writes_audit_log(self, authed_admin_client, admin_user, models_dir):
        _make_version(
            models_dir=models_dir,
            version="v_personal_1",
            segment=ModelVersion.SEGMENT_PERSONAL,
            is_active=True,
        )
        _make_version(
            models_dir=models_dir,
            version="v_unified_1",
            segment=ModelVersion.SEGMENT_UNIFIED,
            is_active=True,
        )
        challenger = _make_version(
            models_dir=models_dir,
            version="v_personal_2",
            segment=ModelVersion.SEGMENT_PERSONAL,
            is_active=False,
        )

        url = reverse("model-activate", kwargs={"pk": challenger.id})
        authed_admin_client.post(url)

        log = AuditLog.objects.filter(
            user=admin_user,
            action="model_activate",
            resource_id=str(challenger.id),
        ).first()
        assert log is not None, "expected an AuditLog row for model_activate"
        assert log.details["segment"] == ModelVersion.SEGMENT_PERSONAL
        assert log.details["version"] == "v_personal_2"
        # Snapshot must list both segments that were active before the call.
        assert ModelVersion.SEGMENT_PERSONAL in log.details["previous_active_segments"]
        assert ModelVersion.SEGMENT_UNIFIED in log.details["previous_active_segments"]
