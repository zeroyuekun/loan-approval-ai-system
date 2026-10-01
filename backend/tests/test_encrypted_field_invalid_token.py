"""I6 — an undecryptable value is never served as plaintext, and an ordinary
save never encrypts the ciphertext a second time.

EncryptedCharField.from_db_value returned the raw ciphertext on InvalidToken
(a key replaced instead of prepended, a backup restored under another key).
The customer then saw "gAAAAA..." as their phone number, and the next save of
any field re-encrypted the ciphertext, so restoring the right key could no
longer recover it.
"""

import pytest
from cryptography.fernet import Fernet
from django.db import connection

from apps.accounts.models import CustomerProfile


def _raw(profile, column="phone"):
    with connection.cursor() as cur:
        cur.execute(f"SELECT {column} FROM accounts_customerprofile WHERE id = %s", [profile.pk])
        return cur.fetchone()[0]


def _set_raw(profile, value, column="phone"):
    with connection.cursor() as cur:
        cur.execute(f"UPDATE accounts_customerprofile SET {column} = %s WHERE id = %s", [value, profile.pk])


@pytest.fixture
def profile(customer_user):
    profile, _ = CustomerProfile.objects.get_or_create(user=customer_user)
    return profile


@pytest.fixture
def foreign_ciphertext():
    """A real Fernet token under a key this deployment does not hold."""
    return Fernet(Fernet.generate_key()).encrypt(b"0400111222").decode()


@pytest.mark.django_db
def test_undecryptable_value_is_not_served_as_plaintext(profile, foreign_ciphertext, caplog):
    _set_raw(profile, foreign_ciphertext)
    loaded = CustomerProfile.objects.get(pk=profile.pk)
    assert loaded.phone == ""
    assert "gAAAA" not in str(loaded.phone)
    assert any("undecryptable" in r.getMessage().lower() for r in caplog.records)


@pytest.mark.django_db
def test_saving_other_fields_leaves_the_undecryptable_ciphertext_untouched(profile, foreign_ciphertext):
    _set_raw(profile, foreign_ciphertext)
    loaded = CustomerProfile.objects.get(pk=profile.pk)
    loaded.state = "VIC"
    loaded.save()  # a full save, as DRF's ModelSerializer.update does
    assert _raw(profile) == foreign_ciphertext  # not ciphertext-of-ciphertext, not blanked


@pytest.mark.django_db
def test_a_new_value_replaces_the_undecryptable_one(profile, foreign_ciphertext):
    _set_raw(profile, foreign_ciphertext)
    loaded = CustomerProfile.objects.get(pk=profile.pk)
    loaded.phone = "0400999888"
    loaded.save()
    assert CustomerProfile.objects.get(pk=profile.pk).phone == "0400999888"


@pytest.mark.django_db
def test_legacy_plaintext_is_still_read_as_is(profile):
    _set_raw(profile, "0400123456")
    assert CustomerProfile.objects.get(pk=profile.pk).phone == "0400123456"
