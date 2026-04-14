# Australian Lending Platform Research — Design

**Date:** 2026-04-14
**Sub-project:** A (of A→B→C sequence)
**Feeds:** Sub-project B (ML / synthetic data realism + XGBoost) and Sub-project C (code efficiency + stress testing + UX/email improvements)
**Out of scope:** Code changes, ML tuning, stress testing, synthetic data regeneration. Research only.

## Goal

Produce a consolidated research artifact describing how Australian consumer lenders collect applications, assess risk, and present decisions. The artifact must be directly usable as input to:

1. Synthetic data schema upgrades (what fields real lenders collect)
2. XGBoost feature engineering (what risk signals real lenders use)
3. Frontend and email copy improvements (how neobanks communicate approvals/denials)

## Sources

Nine Australian lenders, chosen for mix of size, segment, and transparency:

| Tier | Lender | Why |
|---|---|---|
| Big Four | Commonwealth Bank (CBA) | Largest incumbent, most disclosure |
| Big Four | NAB | Strong personal loan product, public criteria |
| Neobank | Up | Best-in-class UX, instant decisioning patterns |
| Neobank | Judo Bank | SME/business lending angle for comparison |
| Neobank | Alex Bank | Newer personal loan challenger |
| Specialist | Plenti | Marketplace lender, risk-based pricing published |
| Specialist | Wisr | Comprehensive credit reporting focus |
| Specialist | MoneyMe | Fast-decisioning fintech |
| Comparison | Canstar | Cross-lender criteria and rate benchmarking |

## Method

- **Discovery:** `WebSearch` for each lender across queries like `<lender> personal loan eligibility`, `<lender> application requirements`, `<lender> rates fees`, `<lender> credit assessment`.
- **Extraction:** `WebFetch` against discovered URLs (product page, eligibility page, FAQ, rate table, PDS where linked as HTML).
- **Fallback behaviour:** If a page is JS-gated or login-gated, record the gap in the lender section and move on. Do not invoke Playwright for this phase.
- **Rate limiting:** Sequential fetches per lender; no concurrent scraping across lenders to stay polite.

## Extraction Schema (per lender)

- **Application fields collected:** income, employment, expenses, liabilities, assets, loan purpose, ID types, residency.
- **Eligibility criteria:** minimum income, age, residency, credit history statements.
- **Risk signals mentioned:** comprehensive credit reporting (CCR), bank statement analysis, serviceability calculations, DTI, explicit use of alternative data.
- **Rates and fees:** advertised range, establishment fee, monthly fee, comparison rate, personalised-rate language.
- **UX patterns:** advertised decision time, conditional approval behaviour, rate personalisation, disclosure style, denial communication style (where publicly described).
- **Gaps:** anything the source hides behind login/PDF/JS.

## Deliverables

Two files committed under `docs/research/`:

### 1. `docs/research/2026-04-14-au-lending-research.md`

- Executive summary (1 page)
- One section per lender following the extraction schema
- **Consolidated findings** section:
  - Common application fields (present in ≥5 lenders)
  - Common risk signals (present in ≥5 lenders)
  - Gaps vs. our current model: fields real lenders collect that our synthetic data lacks
  - UX/copy patterns worth adopting
- **Recommendations** section with every item tagged `[→ B]` (feeds ML sub-project) or `[→ C]` (feeds code/UX sub-project)

### 2. `docs/research/findings.json`

Normalised structured data for programmatic consumption by sub-project B:

```json
{
  "generated_at": "2026-04-14",
  "lenders": [
    {
      "name": "string",
      "type": "big_four | neobank | specialist | comparison",
      "urls_fetched": ["string"],
      "application_fields": ["string"],
      "eligibility": {
        "min_income_aud": "number | null",
        "min_age": "number | null",
        "residency": "string | null",
        "credit_notes": "string | null"
      },
      "risk_signals": ["string"],
      "rates": {
        "advertised_min_apr": "number | null",
        "advertised_max_apr": "number | null",
        "comparison_rate_max": "number | null",
        "fees": ["string"]
      },
      "ux_patterns": ["string"],
      "gaps": ["string"]
    }
  ],
  "consolidated": {
    "common_application_fields": ["string"],
    "common_risk_signals": ["string"],
    "gaps_in_our_model": ["string"],
    "ux_recommendations": ["string"]
  }
}
```

## Success Criteria

- All 9 lenders covered; gaps explicitly noted where extraction failed.
- Consolidated findings identify at least 5 concrete application fields or risk signals not present in our current synthetic data generator.
- Every recommendation is tagged `[→ B]` or `[→ C]` so downstream sub-projects can pick them up without re-reading the whole report.
- `findings.json` validates as JSON and matches the schema above.

## Non-Goals

- No scraping of gated/authenticated flows.
- No PDF extraction (note PDS links as gaps).
- No implementation work — this phase produces research only.
- No inference of private decisioning criteria lenders don't publicly describe; stick to what sources say.
