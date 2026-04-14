"""Serializers for ml_engine API endpoints."""

from rest_framework import serializers

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
