"""Regression: on_time_payment_pct is constrained to [0, 100].

D2 corrected the seed command that was writing the wrong scale, but the
model itself accepts any float. This test locks in Min/MaxValueValidators
so a future regression on any writer surface raises ValidationError.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.accounts.models import CustomerProfile

User = get_user_model()


@pytest.fixture
def profile():
    user = User.objects.create_user(
        username="pct_target",
        email="pct_target@example.com",
        password="x",
        role="customer",
    )
    # Profile may be auto-created by a post-save signal; otherwise make one.
    return CustomerProfile.objects.get_or_create(user=user)[0]


@pytest.mark.django_db
def test_on_time_payment_pct_rejects_negative(profile):
    profile.on_time_payment_pct = -0.1
    with pytest.raises(ValidationError) as exc:
        profile.full_clean()
    assert "on_time_payment_pct" in exc.value.message_dict


@pytest.mark.django_db
def test_on_time_payment_pct_rejects_above_100(profile):
    profile.on_time_payment_pct = 100.01
    with pytest.raises(ValidationError) as exc:
        profile.full_clean()
    assert "on_time_payment_pct" in exc.value.message_dict


@pytest.mark.django_db
def test_on_time_payment_pct_accepts_boundaries(profile):
    for value in (0.0, 100.0, 87.5):
        profile.on_time_payment_pct = value
        profile.full_clean()
