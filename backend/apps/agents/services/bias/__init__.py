"""Bias detection agents for loan decision and marketing emails.

Public API (preserved for back-compat via the bias_detector shim):
- BiasDetector: junior compliance analyst for decision emails
- AIEmailReviewer: senior compliance review for decision emails
- MarketingBiasDetector: junior compliance analyst for marketing emails
- MarketingEmailReviewer: senior compliance review for marketing emails
"""

from .core import BiasDetector
from .marketing import MarketingBiasDetector, MarketingEmailReviewer
from .reviewer import AIEmailReviewer

__all__ = [
    "AIEmailReviewer",
    "BiasDetector",
    "MarketingBiasDetector",
    "MarketingEmailReviewer",
]
