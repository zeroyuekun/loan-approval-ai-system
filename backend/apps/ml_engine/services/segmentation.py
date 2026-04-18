"""Product-segment routing for the XGBoost approval model.

Australian lenders train distinct models per product segment rather than a
single unified model, because owner-occupier mortgages, investor mortgages,
and personal loans have very different risk dynamics:

* Owner-occupier mortgages: secured, long-duration, lowest historical default.
* Investor mortgages: secured but cash-flow-sensitive to interest rates and
  rental vacancy; APRA applies a higher risk-weight (APS 112).
* Personal loans: unsecured, shorter duration, highest default; pricing model
  is very different (risk-based APR 7-24% vs. mortgage spreads < 1.5%).

A segmented model respects those dynamics; a unified model averages them away.

The caveat is sample size: segment splits produce smaller training sets.
Below `SEGMENT_MIN_SAMPLES` we fall back to the unified model so decisioning
remains stable during the first months of a new product or when a rare
segment has too few approvals to train on.

This module is pure policy — no Django queries, no model loading. The
predictor is responsible for turning a resolved segment into an active
ModelVersion row (`select_active_model_for_segment`).
"""

from __future__ import annotations

from typing import Optional


SEGMENT_UNIFIED = "unified"
SEGMENT_HOME_OWNER_OCCUPIER = "home_owner_occupier"
SEGMENT_HOME_INVESTOR = "home_investor"
SEGMENT_PERSONAL = "personal"

# Minimum positive-label samples to justify a per-segment model. Below this
# threshold the noise in the per-segment AUC dominates any segmentation
# benefit, so we serve the unified model instead.
SEGMENT_MIN_SAMPLES = 500


# SEGMENT_FILTERS is used by the trainer to slice the training set. Each
# filter accepts a single row (dict-like) and returns True if it belongs to
# the segment. Kept here — rather than scattered across trainer.py — so a
# change to segment definitions lands in one place.
SEGMENT_FILTERS = {
    SEGMENT_HOME_OWNER_OCCUPIER: lambda row: (
        row.get("purpose") == "home"
        and row.get("home_ownership") != "investor"
    ),
    SEGMENT_HOME_INVESTOR: lambda row: (
        row.get("purpose") == "investment"
        or row.get("home_ownership") == "investor"
    ),
    SEGMENT_PERSONAL: lambda row: row.get("purpose") == "personal",
}


def derive_segment(application) -> str:
    """Route a loan application to its product segment.

    Accepts either a dict or a LoanApplication-like object with attribute
    access. Priority order is:

    1. Investment purpose → home_investor (taxonomy: investor loans are
       always treated as such regardless of home_ownership).
    2. Home purpose + owner-occupier home_ownership → home_owner_occupier.
    3. Home purpose + investor home_ownership → home_investor (covers
       "owner-occupier loan for an existing investor applicant" edge case).
    4. Personal purpose → personal.
    5. Anything else → unified (the fallback; this should never fire for a
       valid LoanApplication given the purpose choices, but makes the
       function total).
    """

    def _get(key, default=None):
        if isinstance(application, dict):
            return application.get(key, default)
        return getattr(application, key, default)

    purpose = _get("purpose")
    home_ownership = _get("home_ownership")

    if purpose == "investment":
        return SEGMENT_HOME_INVESTOR
    if purpose == "home":
        if home_ownership == "investor":
            return SEGMENT_HOME_INVESTOR
        return SEGMENT_HOME_OWNER_OCCUPIER
    if purpose == "personal":
        return SEGMENT_PERSONAL
    return SEGMENT_UNIFIED


def select_active_model_for_segment(
    segment: str,
    *,
    ModelVersion=None,
    algorithm: str = "xgb",
) -> Optional["ModelVersion"]:
    """Pick the most recent active ModelVersion for the given segment.

    Falls back to the unified model when no active segment-specific model
    exists, and ultimately returns None if neither is available.

    `ModelVersion` is injected for testability — the predictor passes the
    real model class at call time; unit tests pass a fake.
    """
    if ModelVersion is None:
        from apps.ml_engine.models import ModelVersion as _MV
        ModelVersion = _MV

    base = ModelVersion.objects.filter(is_active=True, algorithm=algorithm)

    if segment != SEGMENT_UNIFIED:
        specific = base.filter(segment=segment).order_by("-created_at").first()
        if specific is not None:
            return specific

    return base.filter(segment=SEGMENT_UNIFIED).order_by("-created_at").first()
