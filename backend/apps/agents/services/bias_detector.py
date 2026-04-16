"""Back-compat shim. Real code lives in the bias/ package."""

import anthropic  # noqa: F401 — re-exported for tests that patch bias_detector.anthropic

from apps.agents.services.bias import (  # noqa: F401
    AIEmailReviewer,
    BiasDetector,
    MarketingBiasDetector,
    MarketingEmailReviewer,
)
