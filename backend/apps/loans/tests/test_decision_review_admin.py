import pytest
from django.contrib.admin.sites import site

from apps.loans.models import DecisionReview

pytestmark = pytest.mark.django_db


def test_decision_review_registered_with_resolve_actions():
    model_admin = site._registry[DecisionReview]
    action_names = {a.__name__ if callable(a) else a for a in model_admin.actions}
    assert "mark_overturned" in action_names
    assert "mark_upheld" in action_names
