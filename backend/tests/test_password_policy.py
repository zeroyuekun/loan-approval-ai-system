"""Every password set through Django's validators needs at least 12 characters.

Registration already asked customers for 12, but the shared validators
allowed 8, so staff passwords set through the admin or createsuperuser
could be shorter than a customer's.
"""

import pytest
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from apps.accounts.models import CustomUser


def _staff():
    return CustomUser(username="officer_jane", email="jane@lender.example", role=CustomUser.Role.LOAN_OFFICER)


def test_staff_password_under_twelve_characters_is_rejected():
    with pytest.raises(ValidationError) as exc:
        validate_password("Qz7!kLp2x", user=_staff())
    assert any(error.code == "password_too_short" for error in exc.value.error_list)


def test_twelve_character_password_is_accepted():
    validate_password("Qz7!kLp2xW#m", user=_staff())
