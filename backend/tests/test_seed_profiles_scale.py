"""Regression: seed_profiles writes on_time_payment_pct on the 0-100 scale.

Bug history: prior to v1.10.2 the seed_profiles management command wrote
random.uniform(0.75, 1.0) into on_time_payment_pct, but the field is a
percentage in [0, 100] (enforced by validators in CustomerProfile).
That mismatch produced near-zero percentages for every seeded customer
and silently corrupted training data realism.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.accounts.models import CustomerProfile

User = get_user_model()


@pytest.mark.django_db
def test_seed_profiles_on_time_payment_pct_is_on_0_to_100_scale():
    User.objects.create_user(
        username="seed_target",
        email="seed_target@example.com",
        password="x",
        role="customer",
    )

    call_command("seed_profiles")

    profiles = list(CustomerProfile.objects.all())
    assert profiles, "seed_profiles should populate at least one CustomerProfile"

    for profile in profiles:
        pct = float(profile.on_time_payment_pct)
        assert 0.0 <= pct <= 100.0, f"on_time_payment_pct={pct} outside the [0, 100] range for {profile.user.username}"
        # Seeded range is uniform(75, 100); anything below 1.0 indicates
        # the legacy 0-1 scale bug has regressed.
        assert pct >= 1.0, (
            f"on_time_payment_pct={pct} looks like the legacy 0-1 scale "
            f"for {profile.user.username} — seed command must write percent units"
        )
