"""External integration adapters (CDR sandbox, credit bureau, property,
macro, geocoding, benchmarks).

This subpackage was extracted from the flat ml_engine/services/ directory
on 2026-05-26 as PR-1 of the decomposition cycle (see
docs/superpowers/specs/2026-05-25-ml-engine-decomposition-design.md).

Re-exports preserve the public API. Direct imports from this subpackage
are preferred for new code:

    from apps.ml_engine.services.external.credit_bureau import CreditBureauService
"""
from apps.ml_engine.services.external.benchmark_resolver import BenchmarkResolver
from apps.ml_engine.services.external.credit_bureau import (
    CREDIT_REPORT_BOUNDS,
    CreditBureauService,
    CreditReport,
)
from apps.ml_engine.services.external.geocoding import (
    GeocodingService,
    GeoRiskProfile,
)
from apps.ml_engine.services.external.macro_data import MacroDataService
from apps.ml_engine.services.external.open_banking import (
    OpenBankingProfile,
    OpenBankingService,
)
from apps.ml_engine.services.external.plaid_patterns import (
    PLAID_TO_AU_FEATURE_MAP,
    PlaidBehavioralPatterns,
    PlaidPatternsService,
)
from apps.ml_engine.services.external.property_data import PropertyDataService

__all__ = [
    "BenchmarkResolver",
    "CREDIT_REPORT_BOUNDS",
    "CreditBureauService",
    "CreditReport",
    "GeocodingService",
    "GeoRiskProfile",
    "MacroDataService",
    "OpenBankingProfile",
    "OpenBankingService",
    "PLAID_TO_AU_FEATURE_MAP",
    "PlaidBehavioralPatterns",
    "PlaidPatternsService",
    "PropertyDataService",
]
