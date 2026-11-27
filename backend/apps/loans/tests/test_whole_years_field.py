"""Time in current role: applicants answer in decimal years; the API stores whole years."""

import pytest
from rest_framework import serializers

from apps.loans.serializers import WholeYearsField


@pytest.mark.parametrize(("given", "stored"), [("3.5", 3), (3.9, 3), ("4", 4), (0, 0), ("0.4", 0)])
def test_rounds_fractional_years_down(given, stored):
    assert WholeYearsField(min_value=0).run_validation(given) == stored


@pytest.mark.parametrize("given", ["abc", "", None, "-1"])
def test_rejects_non_numbers_and_negatives(given):
    with pytest.raises(serializers.ValidationError):
        WholeYearsField(min_value=0).run_validation(given)
