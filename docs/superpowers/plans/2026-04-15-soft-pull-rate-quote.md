# Soft-Pull Rate Quote Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `POST /api/v1/ml/quote/` that returns an indicative rate range and monthly repayment for an authenticated user without creating a LoanApplication, running the orchestrator, or hitting any credit bureau.

**Architecture:** New `QuoteView` validates a request via `QuoteRequestSerializer`, builds a duck-typed application object, runs `EligibilityChecker` and `ModelPredictor.predict()` synchronously, translates the probability to a rate band via `RateQuoteService`, persists a `QuoteLog` row, returns the response.

**Tech Stack:** Django 5, DRF, existing `ModelPredictor`, new `QuoteLog` model.

**Spec:** `docs/superpowers/specs/2026-04-15-soft-pull-rate-quote-design.md`

---

## Context for implementers (read this first)

- `ModelPredictor.predict(application)` at `backend/apps/ml_engine/services/predictor.py:352` uses `getattr(application, ...)` throughout — a duck-typed `SimpleNamespace` with the right attributes works. No real `LoanApplication` required.
- Attributes `.predict` reads: `annual_income, credit_score, loan_amount, loan_term_months, debt_to_income, employment_length, has_cosigner, purpose, home_ownership, number_of_dependants, employment_type, applicant_type, has_hecs, has_bankruptcy, state`, plus many optional fields handled via `_num()`/`_flag()` fallbacks. Defaults from the serializer cover the required ones; optional ones use imputation values.
- `.predict()` returns a dict containing at least `probability` (float between 0 and 1 — probability of default).
- `EligibilityChecker` at `backend/apps/agents/services/eligibility_checker.py` accepts any object with `.applicant.profile.date_of_birth_date` and `.loan_term_months`.
- `CustomerProfile.date_of_birth_date` property at `backend/apps/accounts/models.py:252` returns a `datetime.date | None`.
- Test convention: use `@pytest.mark.django_db`, `get_user_model()`, `APIClient`. Existing tests at `backend/apps/agents/tests/test_orchestrator_eligibility.py` are a reference.

---

## Task 1: Add `QuoteLog` model + migration

**Files:**
- Modify: `backend/apps/ml_engine/models.py`
- Create: `backend/apps/ml_engine/migrations/NNNN_quotelog.py` (via makemigrations)

- [ ] **Step 1: Add the model**

Append to `backend/apps/ml_engine/models.py`:

```python
import hashlib
import uuid

from django.conf import settings


class QuoteLog(models.Model):
    """Soft-pull rate quote log. Not a LoanApplication — no credit impact."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="quote_logs",
    )
    inputs_hash = models.CharField(max_length=64, db_index=True)
    rate_min = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    rate_max = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    comparison_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    estimated_monthly_repayment = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    eligible = models.BooleanField(default=True)
    ineligible_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self):
        return f"QuoteLog({self.id}, user={self.user_id}, eligible={self.eligible})"


def compute_inputs_hash(payload: dict) -> str:
    """SHA256 of a canonical-JSON representation of the quote request."""
    import json as _json
    canonical = _json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

(If `import uuid`, `import hashlib`, or `from django.conf import settings` are already present in this file, don't re-add them — merge with the existing imports.)

- [ ] **Step 2: Generate the migration**

Run:
```bash
docker compose exec -T backend python manage.py makemigrations ml_engine
```
Expected: a new migration file like `NNNN_quotelog.py` with `CreateModel(name='QuoteLog', ...)`.

- [ ] **Step 3: Apply the migration**

Run:
```bash
docker compose exec -T backend python manage.py migrate ml_engine
```
Expected: `Applying ml_engine.NNNN_quotelog... OK`.

- [ ] **Step 4: Commit**

```bash
git add backend/apps/ml_engine/models.py backend/apps/ml_engine/migrations/
git commit -m "feat(ml_engine): add QuoteLog model for soft-pull rate quotes"
```

---

## Task 2: Implement `RateQuoteService`

**Files:**
- Create: `backend/apps/ml_engine/services/rate_quote_service.py`
- Create: `backend/apps/ml_engine/tests/__init__.py` (if missing)
- Create: `backend/apps/ml_engine/tests/test_rate_quote_service.py`

- [ ] **Step 1: Ensure the tests package exists**

Run:
```bash
ls backend/apps/ml_engine/tests/__init__.py 2>/dev/null || ( mkdir -p backend/apps/ml_engine/tests && touch backend/apps/ml_engine/tests/__init__.py )
```

- [ ] **Step 2: Write the failing tests**

Create `backend/apps/ml_engine/tests/test_rate_quote_service.py`:

```python
"""Tests for RateQuoteService — rate band mapping, amortisation, top factors."""
from decimal import Decimal

import pytest

from apps.ml_engine.services.rate_quote_service import (
    BAND_EXCELLENT,
    BAND_STANDARD,
    BAND_SUB_PRIME,
    RateQuoteService,
)


@pytest.fixture
def service():
    return RateQuoteService()


def test_band_excellent_when_probability_below_0_08(service):
    band = service.band_for_probability(0.05)
    assert band == BAND_EXCELLENT


def test_band_standard_when_probability_between_0_08_and_0_20(service):
    band = service.band_for_probability(0.15)
    assert band == BAND_STANDARD


def test_band_sub_prime_when_probability_above_0_20(service):
    band = service.band_for_probability(0.35)
    assert band == BAND_SUB_PRIME


def test_band_boundary_at_0_20_maps_to_sub_prime(service):
    # Boundary rule: probability == 0.20 goes to the upper (worse) band.
    band = service.band_for_probability(0.20)
    assert band == BAND_SUB_PRIME


def test_amortisation_25k_60mo_8_375_percent(service):
    payment = service.amortised_monthly_payment(
        principal=Decimal("25000"), apr_percent=Decimal("8.375"), term_months=60
    )
    # Verified externally: P = 25000 * (r / (1 - (1+r)**-60)) with r = 0.08375/12
    # ~ 511.95. Allow +/-$1 tolerance for rounding.
    assert abs(payment - Decimal("511.95")) < Decimal("1.00"), payment


def test_top_factors_highlights_strong_credit_and_weak_dti(service):
    request_fields = {
        "credit_score": 820,
        "employment_length": 15,
        "debt_to_income": 0.5,
        "annual_income": 95000,
        "monthly_expenses": 2800,
        "loan_amount": 20000,
        "loan_term_months": 48,
    }
    factors = service.top_rate_factors(request_fields, n=3)
    names = [f["name"] for f in factors]
    assert "credit_score" in names
    assert "debt_to_income" in names
    cs = next(f for f in factors if f["name"] == "credit_score")
    dti = next(f for f in factors if f["name"] == "debt_to_income")
    assert cs["impact"] == "positive"
    assert dti["impact"] == "negative"
```

- [ ] **Step 3: Confirm tests fail**

Run:
```bash
cd backend && python -m pytest apps/ml_engine/tests/test_rate_quote_service.py -v --no-cov 2>&1 | tail -10
```
Expected: ImportError / ModuleNotFoundError for `rate_quote_service`.

- [ ] **Step 4: Implement the service**

Create `backend/apps/ml_engine/services/rate_quote_service.py`:

```python
"""Rate quote service — translates ML probability to a rate band plus factors.

Hand-tuned bands. NOT env-configurable; changing thresholds is a product
decision that warrants code review.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


BAND_EXCELLENT = "excellent"
BAND_STANDARD = "standard"
BAND_SUB_PRIME = "sub_prime"


@dataclass(frozen=True)
class RateBand:
    name: str
    probability_upper_exclusive: float  # probability of default threshold (exclusive)
    apr_min: Decimal
    apr_max: Decimal


_BANDS = (
    RateBand(BAND_EXCELLENT, 0.08, Decimal("6.50"), Decimal("8.50")),
    RateBand(BAND_STANDARD, 0.20, Decimal("8.50"), Decimal("13.50")),
    RateBand(BAND_SUB_PRIME, float("inf"), Decimal("13.50"), Decimal("22.00")),
)

# Fixed comparison-rate offset (AU-market convention: comparison rate ~0.5% above APR midpoint for typical fees).
_COMPARISON_RATE_FEE_OFFSET = Decimal("0.50")

# Plausible AU-market means for top-factor z-scoring. Deliberately simple and
# documented; swap for bureau means later if we have them.
_FEATURE_MEANS = {
    "credit_score": (700.0, 80.0),         # (mean, std)
    "employment_length": (6.0, 5.0),
    "debt_to_income": (0.25, 0.12),
    "annual_income": (85000.0, 35000.0),
    "monthly_expenses": (3500.0, 1500.0),
    "loan_amount": (25000.0, 20000.0),
    "loan_term_months": (48.0, 24.0),
}

# Features where higher = better for the borrower. Others treated as higher = worse.
_POSITIVE_WHEN_HIGH = {"credit_score", "employment_length", "annual_income"}


class RateQuoteService:
    def band_for_probability(self, probability: float) -> str:
        for band in _BANDS:
            if probability < band.probability_upper_exclusive:
                return band.name
        return _BANDS[-1].name  # unreachable due to inf sentinel; defensive

    def band_apr_range(self, band_name: str) -> tuple[Decimal, Decimal]:
        for band in _BANDS:
            if band.name == band_name:
                return band.apr_min, band.apr_max
        raise ValueError(f"Unknown band: {band_name}")

    def amortised_monthly_payment(
        self, principal: Decimal, apr_percent: Decimal, term_months: int
    ) -> Decimal:
        if term_months <= 0:
            raise ValueError("term_months must be positive")
        r = (apr_percent / Decimal("100")) / Decimal("12")
        if r == 0:
            payment = principal / Decimal(term_months)
        else:
            one_plus_r_to_n = (Decimal("1") + r) ** term_months
            payment = principal * r * one_plus_r_to_n / (one_plus_r_to_n - Decimal("1"))
        return payment.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def comparison_rate_estimate(self, apr_min: Decimal, apr_max: Decimal) -> Decimal:
        midpoint = (apr_min + apr_max) / Decimal("2")
        return (midpoint + _COMPARISON_RATE_FEE_OFFSET).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    def top_rate_factors(self, request_fields: dict, n: int = 3) -> list[dict]:
        scored = []
        for feature, (mean, std) in _FEATURE_MEANS.items():
            val = request_fields.get(feature)
            if val is None or std == 0:
                continue
            z = (float(val) - mean) / std
            impact = self._impact_for(feature, z)
            scored.append({"name": feature, "z_score": z, "impact": impact})
        scored.sort(key=lambda f: abs(f["z_score"]), reverse=True)
        return [{"name": f["name"], "impact": f["impact"]} for f in scored[:n]]

    @staticmethod
    def _impact_for(feature: str, z: float) -> str:
        if abs(z) < 0.3:
            return "neutral"
        positive_when_high = feature in _POSITIVE_WHEN_HIGH
        high = z > 0
        if positive_when_high == high:
            return "positive"
        return "negative"

    def build_quote(self, probability: float, request_fields: dict) -> dict:
        """Convenience bundle for the view."""
        band_name = self.band_for_probability(probability)
        apr_min, apr_max = self.band_apr_range(band_name)
        midpoint_apr = (apr_min + apr_max) / Decimal("2")
        monthly = self.amortised_monthly_payment(
            principal=Decimal(str(request_fields["loan_amount"])),
            apr_percent=midpoint_apr,
            term_months=int(request_fields["loan_term_months"]),
        )
        return {
            "band": band_name,
            "rate_min": apr_min,
            "rate_max": apr_max,
            "comparison_rate": self.comparison_rate_estimate(apr_min, apr_max),
            "estimated_monthly_repayment": monthly,
            "top_rate_factors": self.top_rate_factors(request_fields),
        }
```

- [ ] **Step 5: Run tests and confirm pass**

Run:
```bash
cd backend && python -m pytest apps/ml_engine/tests/test_rate_quote_service.py -v --no-cov 2>&1 | tail -15
```
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/ml_engine/services/rate_quote_service.py backend/apps/ml_engine/tests/
git commit -m "feat(ml_engine): RateQuoteService — probability-to-rate mapping + amortisation + factors"
```

---

## Task 3: Add `QuoteRequestSerializer`

**Files:**
- Modify: `backend/apps/ml_engine/serializers.py` (create if missing)

- [ ] **Step 1: Check whether `ml_engine/serializers.py` exists**

Run:
```bash
ls backend/apps/ml_engine/serializers.py 2>/dev/null && echo exists || echo missing
```

If missing, the file needs creating; if present, we'll append.

- [ ] **Step 2: Add the serializer**

If creating the file, start with:
```python
"""Serializers for ml_engine API endpoints."""
from rest_framework import serializers
```

Then append (or add to existing file):

```python
_PURPOSE_CHOICES = ("home", "auto", "education", "personal", "business")
_EMPLOYMENT_CHOICES = ("payg_permanent", "payg_casual", "self_employed", "contract")
_HOME_OWNERSHIP_CHOICES = ("own", "rent", "mortgage")
_STATE_CHOICES = ("NSW", "VIC", "QLD", "SA", "WA", "TAS", "ACT", "NT")


class QuoteRequestSerializer(serializers.Serializer):
    """Soft-pull rate quote request. Minimal fields — no PII stored from this body."""

    loan_amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1000, max_value=5_000_000)
    loan_term_months = serializers.IntegerField(min_value=6, max_value=360)
    purpose = serializers.ChoiceField(choices=_PURPOSE_CHOICES)
    annual_income = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    employment_type = serializers.ChoiceField(choices=_EMPLOYMENT_CHOICES)
    employment_length = serializers.IntegerField(min_value=0, max_value=60)
    credit_score = serializers.IntegerField(min_value=300, max_value=900)
    monthly_expenses = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    home_ownership = serializers.ChoiceField(choices=_HOME_OWNERSHIP_CHOICES)
    state = serializers.ChoiceField(choices=_STATE_CHOICES)
    debt_to_income = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=5)
```

- [ ] **Step 3: Verify the file imports cleanly**

Run:
```bash
cd backend && python -c "from apps.ml_engine.serializers import QuoteRequestSerializer; print('ok')"
```
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add backend/apps/ml_engine/serializers.py
git commit -m "feat(ml_engine): add QuoteRequestSerializer"
```

---

## Task 4: Implement `QuoteView` + `QuoteThrottle` + URL

**Files:**
- Modify: `backend/apps/ml_engine/views.py`
- Modify: `backend/apps/ml_engine/urls.py`
- Modify: `docker-compose.yml` (add `DJANGO_THROTTLE_QUOTE_RATE` env)

- [ ] **Step 1: Add the throttle and view to `views.py`**

At the top (with existing imports), add if missing:
```python
from datetime import timedelta
from types import SimpleNamespace

from django.utils import timezone
```

After the existing throttle classes, add:

```python
class QuoteThrottle(UserRateThrottle):
    rate = os.environ.get("DJANGO_THROTTLE_QUOTE_RATE", "30/min")
```

Then add the view (placement: after `PredictView`):

```python
class QuoteView(APIView):
    """Soft-pull rate quote. No LoanApplication created, no bureau call, no Celery."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [QuoteThrottle]

    def post(self, request):
        from apps.agents.services.eligibility_checker import EligibilityChecker
        from apps.ml_engine.models import QuoteLog, compute_inputs_hash
        from apps.ml_engine.serializers import QuoteRequestSerializer
        from apps.ml_engine.services.predictor import ModelPredictor
        from apps.ml_engine.services.rate_quote_service import RateQuoteService

        serializer = QuoteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fields = serializer.validated_data

        now = timezone.now()
        expires_at = now + timedelta(days=7)

        # Build a duck-typed application for EligibilityChecker and ModelPredictor.
        profile = getattr(request.user, "profile", None)
        applicant_ns = SimpleNamespace(profile=profile)
        duck_app = SimpleNamespace(
            applicant=applicant_ns,
            annual_income=fields["annual_income"],
            credit_score=fields["credit_score"],
            loan_amount=fields["loan_amount"],
            loan_term_months=fields["loan_term_months"],
            debt_to_income=fields["debt_to_income"],
            employment_length=fields["employment_length"],
            has_cosigner=False,
            purpose=fields["purpose"],
            home_ownership=fields["home_ownership"],
            number_of_dependants=0,
            monthly_expenses=fields["monthly_expenses"],
            employment_type=fields["employment_type"],
            applicant_type="single",
            has_hecs=False,
            has_bankruptcy=False,
            state=fields["state"],
        )

        payload_for_hash = {k: (str(v) if hasattr(v, "quantize") else v) for k, v in fields.items()}
        inputs_hash = compute_inputs_hash(payload_for_hash)

        eligibility = EligibilityChecker().check(duck_app)

        if not eligibility.passed:
            quote = QuoteLog.objects.create(
                user=request.user,
                inputs_hash=inputs_hash,
                eligible=False,
                ineligible_reason=eligibility.detail or "",
                expires_at=expires_at,
            )
            return Response(
                {
                    "quote_id": str(quote.id),
                    "indicative_rate_range": None,
                    "estimated_monthly_repayment": None,
                    "comparison_rate_estimate": None,
                    "top_rate_factors": [],
                    "indicative": True,
                    "disclosure": (
                        "This is an indicative quote only. It is not a credit offer and does "
                        "not impact your credit file. A full application is required for a firm rate."
                    ),
                    "expires_at": expires_at.isoformat(),
                    "eligible_for_application": False,
                    "ineligible_reason": eligibility.detail,
                },
                status=status.HTTP_200_OK,
            )

        prediction = ModelPredictor().predict(duck_app)
        probability = float(prediction["probability"])

        service = RateQuoteService()
        # Convert Decimal fields to float for the service's z-scoring.
        request_fields_for_factors = {
            "credit_score": int(fields["credit_score"]),
            "employment_length": int(fields["employment_length"]),
            "debt_to_income": float(fields["debt_to_income"]),
            "annual_income": float(fields["annual_income"]),
            "monthly_expenses": float(fields["monthly_expenses"]),
            "loan_amount": float(fields["loan_amount"]),
            "loan_term_months": int(fields["loan_term_months"]),
        }
        quote_data = service.build_quote(probability, request_fields_for_factors)

        quote = QuoteLog.objects.create(
            user=request.user,
            inputs_hash=inputs_hash,
            eligible=True,
            rate_min=quote_data["rate_min"],
            rate_max=quote_data["rate_max"],
            comparison_rate=quote_data["comparison_rate"],
            estimated_monthly_repayment=quote_data["estimated_monthly_repayment"],
            expires_at=expires_at,
        )

        return Response(
            {
                "quote_id": str(quote.id),
                "indicative_rate_range": {
                    "min": float(quote_data["rate_min"]),
                    "max": float(quote_data["rate_max"]),
                },
                "estimated_monthly_repayment": float(quote_data["estimated_monthly_repayment"]),
                "comparison_rate_estimate": float(quote_data["comparison_rate"]),
                "top_rate_factors": quote_data["top_rate_factors"],
                "indicative": True,
                "disclosure": (
                    "This is an indicative quote only. It is not a credit offer and does "
                    "not impact your credit file. A full application is required for a firm rate."
                ),
                "expires_at": expires_at.isoformat(),
                "eligible_for_application": True,
            },
            status=status.HTTP_200_OK,
        )
```

- [ ] **Step 2: Wire the URL**

Modify `backend/apps/ml_engine/urls.py`, add to `urlpatterns`:
```python
    path("quote/", views.QuoteView.as_view(), name="ml-quote"),
```

- [ ] **Step 3: Surface the throttle env in `docker-compose.yml`**

Add to the `backend` service's `environment:` block (alongside the other throttle env vars):
```yaml
      DJANGO_THROTTLE_QUOTE_RATE: ${DJANGO_THROTTLE_QUOTE_RATE:-30/min}
```

- [ ] **Step 4: Verify views import cleanly**

Run:
```bash
cd backend && python -c "from apps.ml_engine.views import QuoteView; print('ok')"
```
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/ml_engine/views.py backend/apps/ml_engine/urls.py docker-compose.yml
git commit -m "feat(ml_engine): add POST /api/v1/ml/quote/ endpoint with env-configurable throttle"
```

---

## Task 5: Integration tests for the endpoint

**Files:**
- Create: `backend/apps/ml_engine/tests/test_quote_view.py`

- [ ] **Step 1: Write the tests**

Create `backend/apps/ml_engine/tests/test_quote_view.py`:

```python
"""Integration tests for POST /api/v1/ml/quote/."""
import datetime
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import CustomerProfile
from apps.ml_engine.models import QuoteLog


QUOTE_URL = "/api/v1/ml/quote/"


def _valid_request():
    return {
        "loan_amount": "25000.00",
        "loan_term_months": 60,
        "purpose": "personal",
        "annual_income": "80000.00",
        "employment_type": "payg_permanent",
        "employment_length": 5,
        "credit_score": 720,
        "monthly_expenses": "3000.00",
        "home_ownership": "rent",
        "state": "NSW",
        "debt_to_income": "0.25",
    }


@pytest.fixture
def authed_client():
    User = get_user_model()
    user = User.objects.create_user(
        username="quoter", password="quote-pass", role="customer"
    )
    # min(day, 28) avoids Feb-29 edge case
    today = datetime.date.today()
    dob = datetime.date(today.year - 30, today.month, min(today.day, 28))
    profile, _ = CustomerProfile.objects.get_or_create(user=user)
    profile.date_of_birth = dob.isoformat()
    profile.save()
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
def test_quote_happy_path(authed_client):
    client, user = authed_client
    fake_prediction = {"probability": 0.05}  # Excellent band
    with patch(
        "apps.ml_engine.services.predictor.ModelPredictor.predict",
        return_value=fake_prediction,
    ):
        resp = client.post(QUOTE_URL, _valid_request(), format="json")

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["eligible_for_application"] is True
    assert body["indicative"] is True
    assert body["indicative_rate_range"]["min"] < body["indicative_rate_range"]["max"]
    assert body["estimated_monthly_repayment"] > 0
    assert len(body["top_rate_factors"]) > 0
    assert body["quote_id"]

    # Exactly one QuoteLog was created for this user.
    logs = QuoteLog.objects.filter(user=user)
    assert logs.count() == 1
    log = logs.first()
    assert log.eligible is True
    assert log.rate_min is not None and log.rate_max is not None


@pytest.mark.django_db
def test_quote_ineligible_when_age_over_67_at_maturity():
    User = get_user_model()
    user = User.objects.create_user(
        username="older-quoter", password="quote-pass", role="customer"
    )
    today = datetime.date.today()
    dob = datetime.date(today.year - 65, today.month, min(today.day, 28))
    profile, _ = CustomerProfile.objects.get_or_create(user=user)
    profile.date_of_birth = dob.isoformat()
    profile.save()

    client = APIClient()
    client.force_authenticate(user=user)

    with patch(
        "apps.ml_engine.services.predictor.ModelPredictor.predict",
        side_effect=AssertionError("ML predictor should not be called when gate fails"),
    ):
        resp = client.post(QUOTE_URL, _valid_request(), format="json")

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["eligible_for_application"] is False
    assert body["indicative_rate_range"] is None
    assert body["ineligible_reason"]

    log = QuoteLog.objects.get(user=user)
    assert log.eligible is False
    assert log.rate_min is None


@pytest.mark.django_db
def test_quote_rejects_unauthenticated():
    client = APIClient()
    resp = client.post(QUOTE_URL, _valid_request(), format="json")
    assert resp.status_code in (401, 403)


@pytest.mark.django_db
def test_quote_rejects_invalid_purpose(authed_client):
    client, _ = authed_client
    body = _valid_request()
    body["purpose"] = "crypto"
    resp = client.post(QUOTE_URL, body, format="json")
    assert resp.status_code == 400
    assert "purpose" in resp.json()
```

- [ ] **Step 2: Run the tests**

Run:
```bash
cd backend && python -m pytest apps/ml_engine/tests/test_quote_view.py -v --no-cov 2>&1 | tail -15
```
Expected: 4 passed.

- [ ] **Step 3: Run the broader suite to catch regressions**

Run:
```bash
cd backend && python -m pytest apps/ml_engine/ apps/agents/ apps/loans/ -q --no-cov 2>&1 | tail -10
```
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add backend/apps/ml_engine/tests/test_quote_view.py
git commit -m "test(ml_engine): integration tests for POST /api/v1/ml/quote/"
```

---

## Task 6: Manual smoke + final verification

**Files:** none.

- [ ] **Step 1: Restart backend with the new throttle env**

Run:
```bash
DJANGO_THROTTLE_QUOTE_RATE=10000/min docker compose up -d --force-recreate --no-deps backend
```

- [ ] **Step 2: Wait for readiness**

Run a single health check loop (up to 8s):
```bash
for i in 1 2 3 4 5 6 7 8; do code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/health/); if [ "$code" = "200" ]; then echo ready; break; fi; sleep 1; done
```

- [ ] **Step 3: Login and POST a quote**

Run:
```bash
curl -s -c /tmp/quote-cookies.txt -H "Content-Type: application/json" \
  -d '{"username":"loadtest","password":"loadtest-change-me"}' \
  http://localhost:8000/api/v1/auth/login/ > /dev/null
curl -s -b /tmp/quote-cookies.txt -H "Content-Type: application/json" \
  -d '{"loan_amount":25000,"loan_term_months":60,"purpose":"personal","annual_income":80000,"employment_type":"payg_permanent","employment_length":5,"credit_score":720,"monthly_expenses":3000,"home_ownership":"rent","state":"NSW","debt_to_income":0.25}' \
  http://localhost:8000/api/v1/ml/quote/ | head -c 800
```
Expected: a JSON response with `indicative_rate_range`, `estimated_monthly_repayment`, `top_rate_factors`, `eligible_for_application: true`. If the loadtest user's profile lacks `date_of_birth`, the gate passes (defensive) and the quote is returned.

- [ ] **Step 4: Confirm nothing broke**

Run:
```bash
cd backend && python -m pytest apps/ -q --no-cov 2>&1 | tail -5
```
Expected: all pass.

---

## Done criteria

- `QuoteLog` model + migration committed and applied
- `RateQuoteService` with 6 passing unit tests
- `QuoteRequestSerializer` validates request bodies
- `QuoteView` at `POST /api/v1/ml/quote/` returns correct shapes for both eligible and ineligible paths
- `QuoteThrottle` defaults to 30/min, env-overridable
- 4 integration tests pass; no existing tests regress
- Manual smoke returns a well-formed quote JSON body
- Single-revert rollback path preserved
