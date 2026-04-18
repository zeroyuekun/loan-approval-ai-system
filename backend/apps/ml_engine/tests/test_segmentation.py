"""Unit tests for segmentation.derive_segment and select_active_model_for_segment.

The filter dict SEGMENT_FILTERS is exercised indirectly via derive_segment
behaviour tests, and directly via a small coverage test to catch accidental
definition drift (e.g. all three segments ever becoming mutually exclusive
on the same row).
"""

from unittest.mock import MagicMock

import pytest

from apps.ml_engine.services.segmentation import (
    SEGMENT_FILTERS,
    SEGMENT_HOME_INVESTOR,
    SEGMENT_HOME_OWNER_OCCUPIER,
    SEGMENT_MIN_SAMPLES,
    SEGMENT_PERSONAL,
    SEGMENT_UNIFIED,
    derive_segment,
    select_active_model_for_segment,
)


class TestDeriveSegment:
    def test_home_owner_occupier(self):
        assert (
            derive_segment({"purpose": "home", "home_ownership": "own"})
            == SEGMENT_HOME_OWNER_OCCUPIER
        )
        assert (
            derive_segment({"purpose": "home", "home_ownership": "rent"})
            == SEGMENT_HOME_OWNER_OCCUPIER
        )

    def test_home_investor_via_purpose(self):
        assert (
            derive_segment({"purpose": "investment", "home_ownership": "own"})
            == SEGMENT_HOME_INVESTOR
        )

    def test_home_investor_via_home_ownership(self):
        assert (
            derive_segment({"purpose": "home", "home_ownership": "investor"})
            == SEGMENT_HOME_INVESTOR
        )

    def test_personal(self):
        assert (
            derive_segment({"purpose": "personal", "home_ownership": "own"})
            == SEGMENT_PERSONAL
        )

    def test_unknown_purpose_falls_back_to_unified(self):
        assert derive_segment({"purpose": "unknown"}) == SEGMENT_UNIFIED

    def test_accepts_object_with_attrs(self):
        app = MagicMock(spec=["purpose", "home_ownership"])
        app.purpose = "personal"
        app.home_ownership = "own"
        assert derive_segment(app) == SEGMENT_PERSONAL

    def test_missing_fields_return_unified(self):
        assert derive_segment({}) == SEGMENT_UNIFIED

    @pytest.mark.parametrize("purpose", ["home", "investment", "personal"])
    def test_segment_min_samples_is_conservative(self, purpose):
        # Dumb guard: the 500 threshold should never be 0 (would disable the
        # fallback) and should be at least a meaningful statistical sample.
        assert SEGMENT_MIN_SAMPLES >= 100


class TestSegmentFilters:
    def test_home_owner_occupier_filter(self):
        f = SEGMENT_FILTERS[SEGMENT_HOME_OWNER_OCCUPIER]
        assert f({"purpose": "home", "home_ownership": "own"})
        assert f({"purpose": "home", "home_ownership": "rent"})
        assert not f({"purpose": "home", "home_ownership": "investor"})
        assert not f({"purpose": "investment"})
        assert not f({"purpose": "personal"})

    def test_home_investor_filter(self):
        f = SEGMENT_FILTERS[SEGMENT_HOME_INVESTOR]
        assert f({"purpose": "investment"})
        assert f({"purpose": "home", "home_ownership": "investor"})
        assert not f({"purpose": "personal"})

    def test_personal_filter(self):
        f = SEGMENT_FILTERS[SEGMENT_PERSONAL]
        assert f({"purpose": "personal"})
        assert not f({"purpose": "home"})
        assert not f({"purpose": "investment"})


class TestSelectActiveModelForSegment:
    def _stub_modelversion(self, rows_by_filter):
        """Build a MagicMock ModelVersion class with chainable .objects.filter
        returning the row list matched by the current filter kwargs."""
        class Mgr:
            def __init__(self, rows_by_filter):
                self._rows_by_filter = rows_by_filter
                self._current_filter = {}

            def filter(self, **kwargs):
                new = Mgr(self._rows_by_filter)
                new._current_filter = {**self._current_filter, **kwargs}
                return new

            def order_by(self, *_args):
                return self

            def first(self):
                for predicate, rows in self._rows_by_filter:
                    if all(self._current_filter.get(k) == v for k, v in predicate.items()):
                        return rows[0] if rows else None
                return None

        MV = MagicMock()
        MV.objects = Mgr(rows_by_filter)
        return MV

    def test_returns_specific_when_available(self):
        specific_model = MagicMock(name="home_owner_occupier_model")
        MV = self._stub_modelversion([
            ({"segment": SEGMENT_HOME_OWNER_OCCUPIER, "is_active": True, "algorithm": "xgb"}, [specific_model]),
            ({"segment": SEGMENT_UNIFIED, "is_active": True, "algorithm": "xgb"}, [MagicMock(name="unified")]),
        ])
        got = select_active_model_for_segment(
            SEGMENT_HOME_OWNER_OCCUPIER, ModelVersion=MV
        )
        assert got is specific_model

    def test_falls_back_to_unified_when_segment_missing(self):
        unified_model = MagicMock(name="unified_model")
        MV = self._stub_modelversion([
            ({"segment": SEGMENT_HOME_OWNER_OCCUPIER, "is_active": True, "algorithm": "xgb"}, []),
            ({"segment": SEGMENT_UNIFIED, "is_active": True, "algorithm": "xgb"}, [unified_model]),
        ])
        got = select_active_model_for_segment(
            SEGMENT_HOME_OWNER_OCCUPIER, ModelVersion=MV
        )
        assert got is unified_model

    def test_returns_none_when_no_active_models(self):
        MV = self._stub_modelversion([
            ({"segment": SEGMENT_HOME_OWNER_OCCUPIER, "is_active": True, "algorithm": "xgb"}, []),
            ({"segment": SEGMENT_UNIFIED, "is_active": True, "algorithm": "xgb"}, []),
        ])
        got = select_active_model_for_segment(
            SEGMENT_HOME_OWNER_OCCUPIER, ModelVersion=MV
        )
        assert got is None

    def test_unified_request_goes_direct_to_unified(self):
        unified_model = MagicMock(name="unified_model")
        MV = self._stub_modelversion([
            ({"segment": SEGMENT_UNIFIED, "is_active": True, "algorithm": "xgb"}, [unified_model]),
        ])
        got = select_active_model_for_segment(
            SEGMENT_UNIFIED, ModelVersion=MV
        )
        assert got is unified_model
