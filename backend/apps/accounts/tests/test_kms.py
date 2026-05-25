"""Tests for the KMS abstraction (PR-1 of security gap-closure).

Covers:
  - EnvKMS reads FIELD_ENCRYPTION_KEY as expected
  - EnvKMS raises KMSError when the env var is empty
  - get_kms_adapter() default (no setting) yields EnvKMS
  - get_kms_adapter() with KMS_BACKEND='aws' yields AWSKmsAdapter
  - AWSKmsAdapter raises KMSError when AWS_KMS_KEY_ID is unset
  - AWSKmsAdapter raises KMSError when boto3 is not installed
  - AWSKmsAdapter caches the DEK within TTL and re-fetches after TTL
  - reset_kms_adapter() invalidates the singleton (test isolation)
  - Existing get_fernet() consumer still works via the env path
"""

from __future__ import annotations

import sys
import time
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from apps.accounts.services.kms import (
    AWSKmsAdapter,
    EnvKMS,
    KMSError,
    get_kms_adapter,
    reset_kms_adapter,
)
from apps.accounts.utils.encryption import get_fernet


@pytest.fixture(autouse=True)
def _reset_adapter():
    """Clear adapter + get_fernet caches between tests."""
    reset_kms_adapter()
    get_fernet.cache_clear()
    yield
    reset_kms_adapter()
    get_fernet.cache_clear()


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
    @override_settings(KMS_BACKEND="aws", AWS_KMS_KEY_ID="")
    def test_raises_when_key_id_missing(self):
        adapter = AWSKmsAdapter()
        with pytest.raises(KMSError, match="AWS_KMS_KEY_ID"):
            adapter.get_data_encryption_key()

    @override_settings(KMS_BACKEND="aws", AWS_KMS_KEY_ID="alias/test")
    def test_raises_when_boto3_unavailable(self):
        """If boto3 is not installed, AWSKmsAdapter must surface KMSError
        with a clear message — not crash on ImportError."""
        adapter = AWSKmsAdapter()
        # Force the import to fail inside get_data_encryption_key
        with patch.dict(sys.modules, {"boto3": None}):
            with pytest.raises(KMSError, match="boto3 is not installed"):
                adapter.get_data_encryption_key()

    @override_settings(KMS_BACKEND="aws", AWS_KMS_KEY_ID="alias/test", KMS_DEK_TTL=3600)
    def test_caches_dek_within_ttl(self):
        """After the first call, subsequent calls within TTL return the
        cached DEK without re-calling AWS."""
        pytest.importorskip("boto3")
        adapter = AWSKmsAdapter()
        fake_plaintext = b"0" * 32  # 32 random bytes (KeySpec=AES_256)
        fake_response = {"Plaintext": fake_plaintext}

        mock_client = MagicMock()
        mock_client.generate_data_key.return_value = fake_response

        with patch("boto3.client", return_value=mock_client) as mock_boto3_client:
            dek1 = adapter.get_data_encryption_key()
            dek2 = adapter.get_data_encryption_key()
            dek3 = adapter.get_data_encryption_key()

        assert dek1 == dek2 == dek3
        # boto3.client called once, generate_data_key called once
        assert mock_boto3_client.call_count == 1
        assert mock_client.generate_data_key.call_count == 1

    @override_settings(KMS_BACKEND="aws", AWS_KMS_KEY_ID="alias/test", KMS_DEK_TTL=0)
    def test_zero_ttl_means_no_cache(self):
        pytest.importorskip("boto3")
        adapter = AWSKmsAdapter()
        fake_plaintext = b"0" * 32
        fake_response = {"Plaintext": fake_plaintext}

        mock_client = MagicMock()
        mock_client.generate_data_key.return_value = fake_response

        with patch("boto3.client", return_value=mock_client):
            adapter.get_data_encryption_key()
            # Sleep just past 0s TTL boundary
            time.sleep(0.001)
            adapter.get_data_encryption_key()

        # With TTL=0, second call should refetch
        assert mock_client.generate_data_key.call_count == 2

    @override_settings(KMS_BACKEND="aws", AWS_KMS_KEY_ID="alias/test", KMS_DEK_TTL=3600)
    def test_rotate_invalidates_cache(self):
        pytest.importorskip("boto3")
        adapter = AWSKmsAdapter()
        fake_plaintext = b"0" * 32
        fake_response = {"Plaintext": fake_plaintext}

        mock_client = MagicMock()
        mock_client.generate_data_key.return_value = fake_response

        with patch("boto3.client", return_value=mock_client):
            adapter.get_data_encryption_key()
            adapter.rotate()  # invalidate cache
            adapter.get_data_encryption_key()

        # After rotate(), the next call refetches
        assert mock_client.generate_data_key.call_count == 2

    @override_settings(KMS_BACKEND="aws", AWS_KMS_KEY_ID="alias/test")
    def test_kms_error_wraps_aws_exception(self):
        pytest.importorskip("boto3")
        adapter = AWSKmsAdapter()
        mock_client = MagicMock()
        mock_client.generate_data_key.side_effect = RuntimeError("KMS denied access")

        with patch("boto3.client", return_value=mock_client):
            with pytest.raises(KMSError, match="AWS KMS DEK fetch failed"):
                adapter.get_data_encryption_key()


class TestGetFernetWithKMS:
    """Verify existing get_fernet() consumer still works via the env path."""

    def test_get_fernet_succeeds_with_env_backend(self):
        from cryptography.fernet import Fernet

        valid_key = Fernet.generate_key().decode()
        with override_settings(KMS_BACKEND="env", FIELD_ENCRYPTION_KEY=valid_key):
            reset_kms_adapter()
            get_fernet.cache_clear()
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
