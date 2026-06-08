"""Tests for the KMS abstraction (PR-1 of security gap-closure).

Covers:
  - EnvKMS reads FIELD_ENCRYPTION_KEY as expected
  - EnvKMS raises KMSError when the env var is empty
  - get_kms_adapter() default (no setting) yields EnvKMS
  - get_kms_adapter() with KMS_BACKEND='aws' yields AWSKmsAdapter
  - AWSKmsAdapter.get_data_encryption_key() raises NotImplementedError
    (the AWS envelope path is gated off — see kms.AWSKmsAdapter)
  - reset_kms_adapter() invalidates the singleton (test isolation)
  - Existing get_fernet() consumer still works via the env path
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.accounts.services.kms import (
    AWSKmsAdapter,
    EnvKMS,
    KMSError,
    get_kms_adapter,
    reset_kms_adapter,
)
from apps.accounts.utils.encryption import clear_fernet_cache, get_fernet


@pytest.fixture(autouse=True)
def _reset_adapter():
    """Clear adapter + fernet caches between tests."""
    reset_kms_adapter()
    clear_fernet_cache()
    yield
    reset_kms_adapter()
    clear_fernet_cache()


class TestEnvKMS:
    @override_settings(FIELD_ENCRYPTION_KEY="some-raw-string-passed-through-unchanged")
    def test_returns_configured_key(self):
        """EnvKMS is just a passthrough — Fernet validation is the consumer's job."""
        adapter = EnvKMS()
        assert adapter.get_data_encryption_key() == "some-raw-string-passed-through-unchanged"

    @override_settings(FIELD_ENCRYPTION_KEY="")
    def test_raises_when_key_missing(self):
        adapter = EnvKMS()
        with pytest.raises(KMSError, match="FIELD_ENCRYPTION_KEY"):
            adapter.get_data_encryption_key()

    @override_settings(FIELD_ENCRYPTION_KEY="key1=,key2=,key3=")
    def test_returns_comma_separated_for_rotation(self):
        """EnvKMS passes the raw string through; consumer parses."""
        adapter = EnvKMS()
        assert adapter.get_data_encryption_key() == "key1=,key2=,key3="


class TestGetKMSAdapterFactory:
    def test_default_backend_is_env(self):
        with override_settings(KMS_BACKEND=None):
            adapter = get_kms_adapter()
        assert isinstance(adapter, EnvKMS)

    @override_settings(KMS_BACKEND="env")
    def test_explicit_env(self):
        adapter = get_kms_adapter()
        assert isinstance(adapter, EnvKMS)

    @override_settings(KMS_BACKEND="aws", AWS_KMS_KEY_ID="alias/test")
    def test_explicit_aws(self):
        adapter = get_kms_adapter()
        assert isinstance(adapter, AWSKmsAdapter)

    @override_settings(KMS_BACKEND="vault")
    def test_unknown_backend_raises(self):
        with pytest.raises(KMSError, match="Unknown KMS_BACKEND"):
            get_kms_adapter()

    @override_settings(KMS_BACKEND="env")
    def test_singleton(self):
        a1 = get_kms_adapter()
        a2 = get_kms_adapter()
        assert a1 is a2


class TestAWSKmsAdapter:
    """The AWS envelope-encryption path is intentionally gated off (Path A).

    The previous GenerateDataKey implementation discarded the CiphertextBlob and
    cached only the plaintext DEK, silently losing data after the cache TTL. Until
    real envelope encryption lands, get_data_encryption_key() raises
    NotImplementedError rather than risk data loss.
    """

    @override_settings(KMS_BACKEND="aws", AWS_KMS_KEY_ID="alias/test")
    def test_get_dek_raises_not_implemented(self):
        adapter = AWSKmsAdapter()
        with pytest.raises(NotImplementedError, match="AWS KMS envelope encryption"):
            adapter.get_data_encryption_key()

    @override_settings(KMS_BACKEND="aws", AWS_KMS_KEY_ID="")
    def test_get_dek_gated_regardless_of_key_id(self):
        """Gated off regardless of configuration — never reaches a key fetch."""
        adapter = AWSKmsAdapter()
        with pytest.raises(NotImplementedError):
            adapter.get_data_encryption_key()

    @override_settings(KMS_BACKEND="aws", AWS_KMS_KEY_ID="alias/test")
    def test_factory_still_builds_aws_adapter(self):
        """The factory wires KMS_BACKEND='aws' to AWSKmsAdapter; the guard fires
        only when a key is actually requested, so misconfiguration fails loud."""
        assert isinstance(get_kms_adapter(), AWSKmsAdapter)


class TestGetFernetWithKMS:
    """Verify existing get_fernet() consumer still works via the env path."""

    def test_get_fernet_succeeds_with_env_backend(self):
        from cryptography.fernet import Fernet

        valid_key = Fernet.generate_key().decode()
        with override_settings(KMS_BACKEND="env", FIELD_ENCRYPTION_KEY=valid_key):
            reset_kms_adapter()
            clear_fernet_cache()
            f = get_fernet()
            assert f is not None
            # Round-trip test — proves the DEK is valid for Fernet
            token = f.encrypt(b"plaintext")
            assert f.decrypt(token) == b"plaintext"

    @override_settings(KMS_BACKEND="env", FIELD_ENCRYPTION_KEY="")
    def test_get_fernet_raises_value_error_when_dek_missing(self):
        """Preserves the pre-PR-1 ValueError contract for callers."""
        with pytest.raises(ValueError, match="FIELD_ENCRYPTION_KEY"):
            get_fernet()
