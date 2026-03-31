"""KYC (Know Your Customer) identity verification service.

Integrates with identity verification providers to perform AML/CTF Act 2006
100-point identity checks and sanctions screening.

Providers:
- Australia Post Digital iD (sandbox): Government-backed identity verification
  via document + biometric checks. Free sandbox access.
- Didit (didit.me): 500 free verifications/month. ID document + liveness.

The 100-point system requires:
- Primary ID (70 points): Passport, birth certificate + photo ID
- Secondary ID (25 points): Driver's licence, Medicare card
- Supplementary (5 points): Utility bill, bank statement

References:
- AML/CTF Act 2006 (Cth) Part 2
- AML/CTF Rules Chapter 4: Customer identification
- AUSTRAC guidance: austrac.gov.au
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime

import httpx

logger = logging.getLogger(__name__)

# AML/CTF Act 2006 — 100-point ID check document point values
DOCUMENT_POINTS = {
    # Primary ID (70 points each)
    "passport": {"category": "primary", "points": 70},
    "birth_certificate": {"category": "primary", "points": 70},
    # Secondary ID (25 points each)
    "drivers_licence": {"category": "secondary", "points": 25},
    "medicare_card": {"category": "secondary", "points": 25},
    "photo_id": {"category": "secondary", "points": 25},
    "immicard": {"category": "secondary", "points": 25},
    # Supplementary (5 points each)
    "utility_bill": {"category": "supplementary", "points": 5},
    "bank_statement": {"category": "supplementary", "points": 5},
    "tax_assessment": {"category": "supplementary", "points": 5},
    "council_rates": {"category": "supplementary", "points": 5},
}

# Maximum points allowed per category (AML/CTF Rules Chapter 4)
MAX_PRIMARY_POINTS = 70
MAX_SECONDARY_POINTS = 50
MAX_SUPPLEMENTARY_POINTS = 30
MINIMUM_TOTAL_POINTS = 100


@dataclass
class VerificationResult:
    """Result from an identity verification check."""

    verified: bool
    total_points: int
    primary_id_points: int
    secondary_id_points: int
    supplementary_points: int
    sanctions_clear: bool
    provider: str  # 'australia_post' or 'didit'
    reference_id: str  # Provider's verification ID
    checks_performed: list[str] = field(default_factory=list)
    raw_response: dict = field(default_factory=dict)


class KYCService:
    """Orchestrates identity verification and sanctions screening."""

    AUSPOST_SANDBOX_URL = "https://digitalid-sandbox.auspost.com.au/api/v1"
    AUSPOST_PRODUCTION_URL = "https://digitalid.auspost.com.au/api/v1"
    DIDIT_AUTH_URL = "https://apx.didit.me/auth/v2/token"
    DIDIT_API_URL = "https://apx.didit.me/v2"

    def __init__(self):
        self.timeout = httpx.Timeout(30.0, connect=10.0)
        self.auspost_api_key = os.environ.get("AUSPOST_DIGITAL_ID_KEY", "")
        self.auspost_sandbox = os.environ.get("AUSPOST_DIGITAL_ID_SANDBOX", "true").lower() == "true"
        self.didit_client_id = os.environ.get("DIDIT_CLIENT_ID", "")
        self.didit_client_secret = os.environ.get("DIDIT_CLIENT_SECRET", "")

    def verify_identity(
        self,
        customer_profile,
        documents: list[dict] | None = None,
    ) -> VerificationResult:
        """Perform identity verification using available providers.

        Tries Australia Post Digital iD first (preferred for AU), falls back
        to Didit. Returns safe defaults on complete failure.

        Args:
            customer_profile: CustomerProfile instance with name, DOB, address.
            documents: Optional list of document dicts, e.g.
                       [{'type': 'passport', 'number': 'PA1234567'}]
        """
        documents = documents or []

        # Try Australia Post first (government-backed, preferred for AU)
        if self.auspost_api_key:
            result = self._verify_via_auspost(customer_profile, documents)
            if result is not None:
                return result
            logger.warning("Australia Post verification failed, falling back to Didit")

        # Fallback to Didit
        if self.didit_client_id and self.didit_client_secret:
            result = self._verify_via_didit(customer_profile, documents)
            if result is not None:
                return result
            logger.warning("Didit verification also failed")

        # Both providers unavailable — return safe default (not verified)
        logger.error("All KYC providers unavailable; returning unverified result")
        point_score = self.compute_point_score(documents)
        return VerificationResult(
            verified=False,
            total_points=point_score["total"],
            primary_id_points=point_score["primary"],
            secondary_id_points=point_score["secondary"],
            supplementary_points=point_score["supplementary"],
            sanctions_clear=False,
            provider="none",
            reference_id="",
            checks_performed=["point_score_only"],
            raw_response={"error": "All providers unavailable"},
        )

    def _verify_via_auspost(
        self,
        customer_profile,
        documents: list[dict],
    ) -> VerificationResult | None:
        """Verify via Australia Post Digital iD sandbox.

        Sandbox endpoint: POST /api/v1/verifications
        """
        url = f"{self._get_auspost_sandbox_url()}/verifications"
        point_score = self.compute_point_score(documents)

        payload = {
            "given_name": customer_profile.user.first_name,
            "family_name": customer_profile.user.last_name,
            "date_of_birth": (
                customer_profile.date_of_birth_date.isoformat() if customer_profile.date_of_birth_date else None
            ),
            "address": {
                "line_1": customer_profile.address_line_1,
                "suburb": customer_profile.suburb,
                "state": customer_profile.state,
                "postcode": customer_profile.postcode,
            },
            "documents": [{"type": d.get("type", ""), "number": d.get("number", "")} for d in documents],
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.auspost_api_key}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                data = response.json()

            verified = data.get("status") == "verified"
            sanctions_result = self.check_sanctions(
                full_name=(f"{customer_profile.user.first_name} {customer_profile.user.last_name}"),
                date_of_birth=customer_profile.date_of_birth_date,
            )

            return VerificationResult(
                verified=verified and point_score["sufficient"],
                total_points=point_score["total"],
                primary_id_points=point_score["primary"],
                secondary_id_points=point_score["secondary"],
                supplementary_points=point_score["supplementary"],
                sanctions_clear=sanctions_result["clear"],
                provider="australia_post",
                reference_id=data.get("verification_id", ""),
                checks_performed=["document", "biometric", "sanctions"],
                raw_response=data,
            )
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Australia Post API HTTP error: %s %s",
                exc.response.status_code,
                exc.response.text[:200],
            )
            return None
        except httpx.RequestError as exc:
            logger.error("Australia Post API request error: %s", exc)
            return None

    def _verify_via_didit(
        self,
        customer_profile,
        documents: list[dict],
    ) -> VerificationResult | None:
        """Verify via Didit API.

        Free tier: 500 verifications/month.
        Endpoint: POST /v2/verification-sessions
        """
        token = self._get_didit_token()
        if not token:
            logger.error("Failed to obtain Didit access token")
            return None

        point_score = self.compute_point_score(documents)
        url = f"{self.DIDIT_API_URL}/verification-sessions"

        payload = {
            "first_name": customer_profile.user.first_name,
            "last_name": customer_profile.user.last_name,
            "date_of_birth": (
                customer_profile.date_of_birth_date.isoformat() if customer_profile.date_of_birth_date else None
            ),
            "documents": [{"type": d.get("type", ""), "number": d.get("number", "")} for d in documents],
            "checks": ["document", "liveness"],
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                data = response.json()

            verified = data.get("status") == "verified"
            sanctions_result = self.check_sanctions(
                full_name=(f"{customer_profile.user.first_name} {customer_profile.user.last_name}"),
                date_of_birth=customer_profile.date_of_birth_date,
            )

            return VerificationResult(
                verified=verified and point_score["sufficient"],
                total_points=point_score["total"],
                primary_id_points=point_score["primary"],
                secondary_id_points=point_score["secondary"],
                supplementary_points=point_score["supplementary"],
                sanctions_clear=sanctions_result["clear"],
                provider="didit",
                reference_id=data.get("session_id", ""),
                checks_performed=["document", "liveness", "sanctions"],
                raw_response=data,
            )
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Didit API HTTP error: %s %s",
                exc.response.status_code,
                exc.response.text[:200],
            )
            return None
        except httpx.RequestError as exc:
            logger.error("Didit API request error: %s", exc)
            return None

    def check_sanctions(
        self,
        full_name: str,
        date_of_birth: date | None = None,
    ) -> dict:
        """Screen against sanctions lists.

        Returns:
            {
                'checked': bool,
                'clear': bool,
                'lists_checked': list,
                'date': str,  # ISO date string
            }

        Note: In sandbox mode, always returns clear=True.
        """
        today = datetime.now().strftime("%Y-%m-%d")

        # Sandbox mode — return safe clear result
        if self.auspost_sandbox:
            return {
                "checked": True,
                "clear": True,
                "lists_checked": [
                    "DFAT Consolidated List",
                    "UN Security Council",
                    "AUSTRAC PEP List",
                ],
                "date": today,
            }

        # Production sanctions screening would call a real API here.
        # For safety, default to not-clear when we can't verify.
        logger.warning(
            "Production sanctions screening not yet implemented; returning sanctions_clear=False for %s",
            full_name,
        )
        return {
            "checked": False,
            "clear": False,
            "lists_checked": [],
            "date": today,
        }

    def compute_point_score(self, documents: list[dict]) -> dict:
        """Compute AML/CTF 100-point ID check score from documents.

        Primary (70pts): passport, birth_certificate + photo_id
        Secondary (25pts): drivers_licence, medicare_card, photo_id, immicard
        Supplementary (5pts): utility_bill, bank_statement, tax_assessment,
                              council_rates

        Only one primary document may contribute points (max 70).
        Multiple secondary/supplementary documents are summed up to their
        category caps.

        Returns:
            {
                'total': int,
                'primary': int,
                'secondary': int,
                'supplementary': int,
                'sufficient': bool,  # True if total >= 100
            }
        """
        primary = 0
        secondary = 0
        supplementary = 0

        for doc in documents:
            doc_type = doc.get("type", "").lower().strip()
            info = DOCUMENT_POINTS.get(doc_type)
            if info is None:
                logger.warning("Unknown document type: %s", doc_type)
                continue

            category = info["category"]
            points = info["points"]

            if category == "primary":
                primary = min(primary + points, MAX_PRIMARY_POINTS)
            elif category == "secondary":
                secondary = min(secondary + points, MAX_SECONDARY_POINTS)
            elif category == "supplementary":
                supplementary = min(supplementary + points, MAX_SUPPLEMENTARY_POINTS)

        total = primary + secondary + supplementary
        return {
            "total": total,
            "primary": primary,
            "secondary": secondary,
            "supplementary": supplementary,
            "sufficient": total >= MINIMUM_TOTAL_POINTS,
        }

    def _get_auspost_sandbox_url(self) -> str:
        """Return sandbox or production URL."""
        if self.auspost_sandbox:
            return self.AUSPOST_SANDBOX_URL
        return self.AUSPOST_PRODUCTION_URL

    def _get_didit_token(self) -> str | None:
        """Get OAuth2 access token from Didit."""
        if not self.didit_client_id or not self.didit_client_secret:
            return None

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    self.DIDIT_AUTH_URL,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.didit_client_id,
                        "client_secret": self.didit_client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
                data = response.json()
                return data.get("access_token")
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Didit token request failed: %s %s",
                exc.response.status_code,
                exc.response.text[:200],
            )
            return None
        except httpx.RequestError as exc:
            logger.error("Didit token request error: %s", exc)
            return None

    @staticmethod
    def get_available_providers() -> list[str]:
        """Return list of configured KYC providers based on env vars."""
        providers = []
        if os.environ.get("AUSPOST_DIGITAL_ID_KEY", ""):
            providers.append("australia_post")
        if os.environ.get("DIDIT_CLIENT_ID", "") and os.environ.get("DIDIT_CLIENT_SECRET", ""):
            providers.append("didit")
        return providers
