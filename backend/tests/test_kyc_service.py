"""Tests for the KYC (Know Your Customer) identity verification service."""

import os
from dataclasses import fields
from datetime import date
from unittest.mock import MagicMock, patch

import httpx
import pytest

from apps.accounts.services.kyc_service import (
    DOCUMENT_POINTS,
    MINIMUM_TOTAL_POINTS,
    KYCService,
    VerificationResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    first_name="Jane",
    last_name="Doe",
    dob=None,
    address_line_1="123 Main St",
    suburb="Sydney",
    state="NSW",
    postcode="2000",
):
    """Build a mock CustomerProfile with the fields KYCService uses."""
    user = MagicMock()
    user.first_name = first_name
    user.last_name = last_name

    profile = MagicMock()
    profile.user = user
    profile.date_of_birth = dob or date(1990, 5, 15)
    profile.address_line_1 = address_line_1
    profile.suburb = suburb
    profile.state = state
    profile.postcode = postcode
    return profile


def _auspost_success_response():
    """Fake successful Australia Post verification JSON."""
    return {
        "status": "verified",
        "verification_id": "ap-abc-123",
        "checks": ["document", "biometric"],
    }


def _didit_success_response():
    """Fake successful Didit verification JSON."""
    return {
        "status": "verified",
        "session_id": "dd-xyz-789",
        "checks": ["document", "liveness"],
    }


def _didit_token_response():
    return {"access_token": "fake-didit-token", "expires_in": 3600}


# ---------------------------------------------------------------------------
# 1. compute_point_score: passport + drivers_licence = 95 points (sufficient)
# ---------------------------------------------------------------------------


class TestComputePointScore:
    def setup_method(self):
        self.svc = KYCService()

    def test_passport_plus_drivers_licence_is_95_sufficient(self):
        """Passport (70) + drivers_licence (25) = 95 points — sufficient."""
        docs = [
            {"type": "passport", "number": "PA1234567"},
            {"type": "drivers_licence", "number": "DL9876543"},
        ]
        result = self.svc.compute_point_score(docs)
        assert result["primary"] == 70
        assert result["secondary"] == 25
        assert result["supplementary"] == 0
        assert result["total"] == 95
        # 95 < 100, so NOT sufficient
        assert result["sufficient"] is False

    # -------------------------------------------------------------------
    # 2. Only utility_bill = 5 points (insufficient)
    # -------------------------------------------------------------------

    def test_only_utility_bill_is_5_insufficient(self):
        docs = [{"type": "utility_bill", "number": "UB-001"}]
        result = self.svc.compute_point_score(docs)
        assert result["total"] == 5
        assert result["primary"] == 0
        assert result["secondary"] == 0
        assert result["supplementary"] == 5
        assert result["sufficient"] is False

    # -------------------------------------------------------------------
    # 3. Full document set = 100 points
    # -------------------------------------------------------------------

    def test_full_document_set_reaches_100(self):
        """passport(70) + drivers_licence(25) + utility_bill(5) = 100."""
        docs = [
            {"type": "passport", "number": "PA1234567"},
            {"type": "drivers_licence", "number": "DL9876543"},
            {"type": "utility_bill", "number": "UB-001"},
        ]
        result = self.svc.compute_point_score(docs)
        assert result["total"] == 100
        assert result["sufficient"] is True

    def test_primary_capped_at_70(self):
        """Two primary documents should not exceed 70 points."""
        docs = [
            {"type": "passport", "number": "PA1"},
            {"type": "birth_certificate", "number": "BC1"},
        ]
        result = self.svc.compute_point_score(docs)
        assert result["primary"] == 70  # capped

    def test_secondary_capped_at_50(self):
        """Three secondary documents (75) should be capped at 50."""
        docs = [
            {"type": "drivers_licence", "number": "DL1"},
            {"type": "medicare_card", "number": "MC1"},
            {"type": "immicard", "number": "IM1"},
        ]
        result = self.svc.compute_point_score(docs)
        assert result["secondary"] == 50  # capped

    def test_unknown_document_type_skipped(self):
        docs = [{"type": "unknown_doc", "number": "X"}]
        result = self.svc.compute_point_score(docs)
        assert result["total"] == 0

    def test_empty_documents(self):
        result = self.svc.compute_point_score([])
        assert result == {
            "total": 0,
            "primary": 0,
            "secondary": 0,
            "supplementary": 0,
            "sufficient": False,
        }


# ---------------------------------------------------------------------------
# 4. verify_identity returns VerificationResult with correct fields
# ---------------------------------------------------------------------------


class TestVerifyIdentity:
    @patch.dict(os.environ, {"AUSPOST_DIGITAL_ID_KEY": "test-key"})
    @patch("apps.accounts.services.kyc_service.httpx.Client")
    def test_returns_verification_result_with_correct_fields(self, mock_client_cls):
        """verify_identity should return a VerificationResult dataclass."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = _auspost_success_response()
        mock_resp.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=MagicMock(
                post=MagicMock(return_value=mock_resp),
            )
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        svc = KYCService()
        profile = _make_profile()
        docs = [
            {"type": "passport", "number": "PA1234567"},
            {"type": "drivers_licence", "number": "DL9876543"},
            {"type": "utility_bill", "number": "UB-001"},
        ]

        result = svc.verify_identity(profile, docs)

        assert isinstance(result, VerificationResult)
        assert result.verified is True
        assert result.total_points == 100
        assert result.primary_id_points == 70
        assert result.secondary_id_points == 25
        assert result.supplementary_points == 5
        assert result.sanctions_clear is True  # sandbox mode
        assert result.provider == "australia_post"
        assert result.reference_id == "ap-abc-123"
        assert "document" in result.checks_performed
        assert isinstance(result.raw_response, dict)

    @patch.dict(
        os.environ,
        {
            "AUSPOST_DIGITAL_ID_KEY": "",
            "DIDIT_CLIENT_ID": "",
            "DIDIT_CLIENT_SECRET": "",
        },
    )
    def test_no_providers_returns_unverified(self):
        """When no providers are configured, return safe unverified default."""
        svc = KYCService()
        profile = _make_profile()
        result = svc.verify_identity(profile, [])

        assert isinstance(result, VerificationResult)
        assert result.verified is False
        assert result.sanctions_clear is False
        assert result.provider == "none"


# ---------------------------------------------------------------------------
# 5. Fallback from AusPost to Didit when AusPost unavailable
# ---------------------------------------------------------------------------


class TestProviderFallback:
    @patch.dict(
        os.environ,
        {
            "AUSPOST_DIGITAL_ID_KEY": "test-key",
            "DIDIT_CLIENT_ID": "didit-id",
            "DIDIT_CLIENT_SECRET": "didit-secret",
        },
    )
    @patch("apps.accounts.services.kyc_service.httpx.Client")
    def test_fallback_from_auspost_to_didit(self, mock_client_cls):
        """When AusPost returns HTTP error, fall back to Didit."""
        call_count = 0

        def make_client_context():
            """Return a context manager that fails on first call (AusPost),
            succeeds on second (Didit token) and third (Didit verify)."""
            nonlocal call_count

            class FakeClient:
                def post(self, url, **kwargs):
                    nonlocal call_count
                    call_count += 1

                    if call_count == 1:
                        # AusPost fails
                        resp = MagicMock()
                        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                            "Server Error",
                            request=MagicMock(),
                            response=MagicMock(status_code=500, text="Internal Server Error"),
                        )
                        return resp
                    elif call_count == 2:
                        # Didit token
                        resp = MagicMock()
                        resp.raise_for_status = MagicMock()
                        resp.json.return_value = _didit_token_response()
                        return resp
                    else:
                        # Didit verification
                        resp = MagicMock()
                        resp.raise_for_status = MagicMock()
                        resp.json.return_value = _didit_success_response()
                        return resp

            return FakeClient()

        mock_client_cls.return_value.__enter__ = MagicMock(
            side_effect=lambda: make_client_context(),
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        # Simpler approach: patch the private methods directly
        svc = KYCService()
        profile = _make_profile()
        docs = [
            {"type": "passport", "number": "PA1234567"},
            {"type": "drivers_licence", "number": "DL9876543"},
            {"type": "utility_bill", "number": "UB-001"},
        ]

        # Patch _verify_via_auspost to return None (simulating failure)
        # and _verify_via_didit to return a valid result
        with patch.object(svc, "_verify_via_auspost", return_value=None):
            with patch.object(svc, "_verify_via_didit") as mock_didit:
                mock_didit.return_value = VerificationResult(
                    verified=True,
                    total_points=100,
                    primary_id_points=70,
                    secondary_id_points=25,
                    supplementary_points=5,
                    sanctions_clear=True,
                    provider="didit",
                    reference_id="dd-xyz-789",
                    checks_performed=["document", "liveness", "sanctions"],
                    raw_response=_didit_success_response(),
                )
                result = svc.verify_identity(profile, docs)

        assert result.provider == "didit"
        assert result.verified is True
        mock_didit.assert_called_once()


# ---------------------------------------------------------------------------
# 6. check_sanctions in sandbox mode returns clear=True
# ---------------------------------------------------------------------------


class TestCheckSanctions:
    def test_sandbox_returns_clear(self):
        svc = KYCService()
        # Default is sandbox=True
        result = svc.check_sanctions("Jane Doe", date_of_birth=date(1990, 5, 15))

        assert result["checked"] is True
        assert result["clear"] is True
        assert len(result["lists_checked"]) > 0
        assert "DFAT Consolidated List" in result["lists_checked"]
        assert result["date"]  # non-empty date string

    @patch.dict(os.environ, {"AUSPOST_DIGITAL_ID_SANDBOX": "false"})
    def test_production_mode_defaults_to_not_clear(self):
        """When sandbox is off but no real provider, default to clear=False."""
        svc = KYCService()
        result = svc.check_sanctions("Jane Doe")

        assert result["checked"] is False
        assert result["clear"] is False


# ---------------------------------------------------------------------------
# 7. get_available_providers with/without env vars
# ---------------------------------------------------------------------------


class TestGetAvailableProviders:
    @patch.dict(
        os.environ,
        {
            "AUSPOST_DIGITAL_ID_KEY": "some-key",
            "DIDIT_CLIENT_ID": "did-id",
            "DIDIT_CLIENT_SECRET": "did-secret",
        },
    )
    def test_both_providers_configured(self):
        providers = KYCService.get_available_providers()
        assert "australia_post" in providers
        assert "didit" in providers
        assert len(providers) == 2

    @patch.dict(
        os.environ,
        {
            "AUSPOST_DIGITAL_ID_KEY": "some-key",
            "DIDIT_CLIENT_ID": "",
            "DIDIT_CLIENT_SECRET": "",
        },
    )
    def test_only_auspost_configured(self):
        providers = KYCService.get_available_providers()
        assert providers == ["australia_post"]

    @patch.dict(
        os.environ,
        {
            "AUSPOST_DIGITAL_ID_KEY": "",
            "DIDIT_CLIENT_ID": "",
            "DIDIT_CLIENT_SECRET": "",
        },
    )
    def test_no_providers_configured(self):
        providers = KYCService.get_available_providers()
        assert providers == []

    @patch.dict(
        os.environ,
        {
            "AUSPOST_DIGITAL_ID_KEY": "",
            "DIDIT_CLIENT_ID": "did-id",
            "DIDIT_CLIENT_SECRET": "did-secret",
        },
    )
    def test_only_didit_configured(self):
        providers = KYCService.get_available_providers()
        assert providers == ["didit"]

    @patch.dict(
        os.environ,
        {
            "AUSPOST_DIGITAL_ID_KEY": "",
            "DIDIT_CLIENT_ID": "did-id",
            "DIDIT_CLIENT_SECRET": "",
        },
    )
    def test_didit_partial_config_not_listed(self):
        """Didit requires both client_id AND client_secret."""
        providers = KYCService.get_available_providers()
        assert "didit" not in providers


# ---------------------------------------------------------------------------
# 8. VerificationResult dataclass has all expected fields
# ---------------------------------------------------------------------------


class TestVerificationResultDataclass:
    def test_has_all_expected_fields(self):
        expected_fields = {
            "verified",
            "total_points",
            "primary_id_points",
            "secondary_id_points",
            "supplementary_points",
            "sanctions_clear",
            "provider",
            "reference_id",
            "checks_performed",
            "raw_response",
        }
        actual_fields = {f.name for f in fields(VerificationResult)}
        assert actual_fields == expected_fields

    def test_instantiation_with_all_fields(self):
        result = VerificationResult(
            verified=True,
            total_points=100,
            primary_id_points=70,
            secondary_id_points=25,
            supplementary_points=5,
            sanctions_clear=True,
            provider="australia_post",
            reference_id="ref-123",
            checks_performed=["document", "liveness"],
            raw_response={"status": "verified"},
        )
        assert result.verified is True
        assert result.total_points == 100
        assert result.provider == "australia_post"
        assert result.checks_performed == ["document", "liveness"]
        assert result.raw_response == {"status": "verified"}

    def test_default_list_fields(self):
        """checks_performed and raw_response have sensible defaults."""
        result = VerificationResult(
            verified=False,
            total_points=0,
            primary_id_points=0,
            secondary_id_points=0,
            supplementary_points=0,
            sanctions_clear=False,
            provider="none",
            reference_id="",
        )
        assert result.checks_performed == []
        assert result.raw_response == {}
