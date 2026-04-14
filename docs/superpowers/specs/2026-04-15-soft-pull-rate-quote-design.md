# Soft-Pull Rate Quote Endpoint — Design

**Date:** 2026-04-15
**Source:** Sub-project A research (`docs/research/2026-04-14-au-lending-research.md`) — MoneyMe 90-second quote, Plenti RateEstimate, Alex Bank personalised rate, all flagged `[→ C]`.
**Out of scope:** Anonymous access, bureau calls, rate lock, multi-product quote comparison, frontend UI, email containing the quote.

## Goal

Let authenticated users obtain an indicative interest-rate quote in one API call — no credit impact, no `LoanApplication` row created, no orchestrator/Celery involvement. Response includes a rate range, an estimated monthly repayment, the top factors that drove the rate, and a clear "indicative only" disclosure.

## Why

Every significant Australian lender in our research offers a soft-pull quote (MoneyMe 90s, Plenti RateEstimate, Alex Bank, NAB). It is the largest UX gap we identified. The endpoint also gives us analytics on quote-to-application conversion without inflating the real `LoanApplication` table.

## Endpoint

- `POST /api/v1/ml/quote/`
- `permission_classes = [IsAuthenticated]`
- `throttle_classes = [QuoteThrottle]`, where `QuoteThrottle.rate = os.environ.get("DJANGO_THROTTLE_QUOTE_RATE", "30/min")`

## Request body

```json
{
  "loan_amount": 25000,
  "loan_term_months": 60,
  "purpose": "personal",
  "annual_income": 80000,
  "employment_type": "payg_permanent",
  "employment_length": 5,
  "credit_score": 720,
  "monthly_expenses": 3000,
  "home_ownership": "rent",
  "state": "NSW",
  "debt_to_income": 0.25
}
```

All fields required. Validation mirrors the validators used by `LoanApplicationCreateSerializer` — same choice sets, same numeric bounds. The serializer is new because it has no FK to the applicant and no nullable fields.

## Response body

```json
{
  "quote_id": "uuid",
  "indicative_rate_range": {"min": 7.50, "max": 9.25},
  "estimated_monthly_repayment": 506.12,
  "comparison_rate_estimate": 10.05,
  "top_rate_factors": [
    {"name": "credit_score", "impact": "positive"},
    {"name": "debt_to_income", "impact": "neutral"},
    {"name": "employment_length", "impact": "positive"}
  ],
  "indicative": true,
  "disclosure": "This is an indicative quote only. It is not a credit offer and does not impact your credit file. A full application is required for a firm rate.",
  "expires_at": "2026-04-22T07:12:30Z",
  "eligible_for_application": true
}
```

When the age-at-maturity gate fails, the response is still HTTP 200 with:

```json
{
  "quote_id": "uuid",
  "indicative_rate_range": null,
  "estimated_monthly_repayment": null,
  "comparison_rate_estimate": null,
  "top_rate_factors": [],
  "indicative": true,
  "disclosure": "...",
  "expires_at": "...",
  "eligible_for_application": false,
  "ineligible_reason": "Applicant age at loan maturity would exceed the 67-year policy limit."
}
```

200 with `eligible_for_application: false` (not 4xx) because a soft-pull is informational — we inform, we don't block.

## Server-side flow

1. Validate via `QuoteRequestSerializer`.
2. Run `EligibilityChecker().check(...)` with a duck-typed application carrying `loan_term_months` and a derived DOB from the authenticated user's `CustomerProfile`. If the applicant has no DOB on their profile, the gate passes (same behaviour as the loan pipeline).
3. If gate fails → persist a `QuoteLog` with `ineligible=True` and return the 200-ineligible response above.
4. If gate passes → build the ML feature vector in memory (no DB row). Reuse the existing feature-engineering helpers in `ml_engine/services/` where possible; do not touch the orchestrator.
5. Call `ModelPredictor.predict()` exactly like `PredictView` does.
6. Pass the probability + request fields to `RateQuoteService.build_quote()`:
   - Maps probability to a rate band (3 tiers, see below).
   - Computes estimated monthly repayment with standard amortisation: `P = L * r / (1 - (1 + r)^-n)` where `r = apr_midpoint / 12 / 100`, `n = loan_term_months`.
   - Computes a comparison rate estimate: rate-band midpoint plus a fixed fee-impact adjustment (0.5% — conservative AU-market proxy, documented in the service).
   - Returns top rate factors by selecting the three numeric inputs with the largest absolute z-score against plausible AU-market means (means defined in the service; not from the ML model's SHAP because SHAP here would be overkill and slow).
7. Persist a `QuoteLog` row:
   - `id` (UUID)
   - `user` (FK)
   - `inputs_hash` (sha256 of the canonical-JSON request)
   - `rate_min`, `rate_max`, `comparison_rate`, `estimated_monthly_repayment`
   - `eligible` (bool)
   - `ineligible_reason` (nullable)
   - `created_at`, `expires_at` (= created_at + 7 days)
8. Return the response.

## Rate band mapping (in `RateQuoteService`)

Documented and hand-tuned — NOT ML-derived — so behaviour is explainable and reviewable. Three bands:

| Band | Probability range (of default) | Rate range | Comparison-rate estimate |
|---|---|---|---|
| Excellent | `< 0.08` | 6.5% – 8.5% | midpoint + 0.5% |
| Standard | `0.08 – 0.20` | 8.5% – 13.5% | midpoint + 0.5% |
| Sub-prime | `> 0.20` | 13.5% – 22.0% | midpoint + 0.5% |

Band thresholds are module-level constants in `rate_quote_service.py`; they are NOT env-configurable (changing them is a product decision that warrants code review).

## Data model — `QuoteLog`

New model in `backend/apps/ml_engine/models.py`:

```python
class QuoteLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="quote_logs")
    inputs_hash = models.CharField(max_length=64, db_index=True)
    rate_min = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    rate_max = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    comparison_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    estimated_monthly_repayment = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    eligible = models.BooleanField(default=True)
    ineligible_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["user", "-created_at"])]
```

Migration is generated with `makemigrations`. No data migration.

## PII stance

The `QuoteLog` stores only derived, quote-level data plus the `inputs_hash`. The raw request body is NOT stored. This keeps the table out of the PII encryption path and dramatically shrinks the compliance surface. The `inputs_hash` lets analytics detect repeat quotes without storing PII.

## Testing

All tests under `backend/apps/ml_engine/tests/`. Create that directory (and `__init__.py`) if it doesn't exist.

1. **Unit — rate band mapping** (`test_rate_quote_service.py`): four cases — probability below 0.08, probability in 0.08–0.20, probability above 0.20, exact boundary at 0.20 (mapped to the upper band).
2. **Unit — amortisation** (`test_rate_quote_service.py`): assert the standard amortisation formula returns ~$506.12 for a $25,000 loan at 8.375% APR (the midpoint of 6.5%–10.25%) over 60 months. Tolerance ±$0.50.
3. **Unit — top factors** (`test_rate_quote_service.py`): given a request with `credit_score=820`, `employment_length=15`, `debt_to_income=0.5`, assert the top-3 factors include credit_score as positive and debt_to_income as negative.
4. **Integration — endpoint happy path** (`test_quote_view.py`): `POST /api/v1/ml/quote/` with valid body for an under-67-at-maturity user, assert 200, assert `eligible_for_application=true`, assert `rate_min < rate_max`, assert a `QuoteLog` row was created for that user.
5. **Integration — eligibility gate** (`test_quote_view.py`): user whose age-at-maturity would exceed 67, assert 200, `eligible_for_application=false`, `ineligible_reason` non-empty, `QuoteLog.eligible=False`.
6. **Regression**: `python -m pytest apps/ml_engine/ apps/agents/ apps/loans/ -q` passes cleanly.

## Success criteria

- `POST /api/v1/ml/quote/` returns a valid quote in ≤300 ms p95 under normal load (single ML call, no bureau, no orchestrator, single DB insert)
- No `LoanApplication` row is created
- No Celery task is dispatched
- Age-at-maturity policy gate integrates and returns `eligible_for_application=false` rather than a 4xx
- 5 new tests pass; no existing tests regress
- Single-revert rollback path preserved

## Deliverables

- Create: `backend/apps/ml_engine/services/rate_quote_service.py`
- Create: `backend/apps/ml_engine/tests/__init__.py` (if missing)
- Create: `backend/apps/ml_engine/tests/test_rate_quote_service.py`
- Create: `backend/apps/ml_engine/tests/test_quote_view.py`
- Create: migration for `QuoteLog`
- Modify: `backend/apps/ml_engine/models.py` (add `QuoteLog`)
- Modify: `backend/apps/ml_engine/serializers.py` (add `QuoteRequestSerializer`, `QuoteResponseSerializer`)
- Modify: `backend/apps/ml_engine/views.py` (add `QuoteThrottle`, `QuoteView`)
- Modify: `backend/apps/ml_engine/urls.py` (add `quote/` path)
- Modify: `docker-compose.yml` (surface `DJANGO_THROTTLE_QUOTE_RATE`)
