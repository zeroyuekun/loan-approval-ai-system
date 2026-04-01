"""Tests for PII masking utilities and serializer mixin."""

from types import SimpleNamespace

from utils.pii_masking import PIIMaskingMixin, mask_credit_score, mask_currency


class TestMaskCurrency:
    def test_none_returns_none(self):
        assert mask_currency(None) is None

    def test_low_value(self):
        assert mask_currency(30000) == "Under $50,000"

    def test_mid_value(self):
        assert mask_currency(75000) == "$50,000 - $100,000"

    def test_high_value(self):
        assert mask_currency(150000) == "$100,000 - $250,000"

    def test_very_high_value(self):
        assert mask_currency(500000) == "Over $250,000"

    def test_string_input(self):
        assert mask_currency("80000.00") == "$50,000 - $100,000"

    def test_decimal_input(self):
        from decimal import Decimal

        assert mask_currency(Decimal("120000")) == "$100,000 - $250,000"


class TestMaskCreditScore:
    def test_none_returns_none(self):
        assert mask_credit_score(None) is None

    def test_below_average(self):
        assert "Below Average" in mask_credit_score(400)

    def test_average(self):
        assert "Average" in mask_credit_score(600)

    def test_good(self):
        assert "Good" in mask_credit_score(750)

    def test_excellent(self):
        assert "Excellent" in mask_credit_score(900)


class TestPIIMaskingMixin:
    def _make_serializer_class(self):
        """Create a minimal serializer class with the mixin."""
        from rest_framework import serializers

        class FakeSerializer(PIIMaskingMixin, serializers.Serializer):
            income = serializers.IntegerField()
            name = serializers.CharField()

            PII_MASKED_FIELDS = {"income": mask_currency}
            PII_VISIBLE_ROLES = ("admin", "officer")

        return FakeSerializer

    def test_officer_sees_raw_values(self):
        SerializerClass = self._make_serializer_class()
        request = SimpleNamespace(user=SimpleNamespace(role="officer"))
        serializer = SerializerClass(
            instance={"income": 85000, "name": "Jane"},
            context={"request": request},
        )
        assert serializer.data["income"] == 85000

    def test_customer_sees_masked_values(self):
        SerializerClass = self._make_serializer_class()
        request = SimpleNamespace(user=SimpleNamespace(role="customer"))
        serializer = SerializerClass(
            instance={"income": 85000, "name": "Jane"},
            context={"request": request},
        )
        assert serializer.data["income"] == "$50,000 - $100,000"
        # Non-PII fields are not masked
        assert serializer.data["name"] == "Jane"

    def test_admin_sees_raw_values(self):
        SerializerClass = self._make_serializer_class()
        request = SimpleNamespace(user=SimpleNamespace(role="admin"))
        serializer = SerializerClass(
            instance={"income": 85000, "name": "Jane"},
            context={"request": request},
        )
        assert serializer.data["income"] == 85000

    def test_no_request_context_shows_raw(self):
        SerializerClass = self._make_serializer_class()
        serializer = SerializerClass(
            instance={"income": 85000, "name": "Jane"},
            context={},
        )
        assert serializer.data["income"] == 85000
