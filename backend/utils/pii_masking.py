"""Field-level PII masking for API responses.

Provides a serializer mixin that redacts sensitive fields based on the
requesting user's role, implementing defense-in-depth alongside the
field-level AES-256 encryption already in the database layer.

Security principle: even if a user gains access to an API endpoint they
shouldn't see, the response won't contain raw PII unless their role permits it.
"""


def mask_currency(value):
    """Mask a currency value, showing only the magnitude bracket."""
    if value is None:
        return None
    try:
        num = float(value) if not isinstance(value, (int, float)) else value
    except (TypeError, ValueError):
        return "***"
    if num < 50_000:
        return "Under $50,000"
    elif num < 100_000:
        return "$50,000 - $100,000"
    elif num < 250_000:
        return "$100,000 - $250,000"
    else:
        return "Over $250,000"


def mask_credit_score(value):
    """Mask a credit score, showing only the band."""
    if value is None:
        return None
    try:
        score = int(value)
    except (TypeError, ValueError):
        return "***"
    if score < 500:
        return "Below Average (0-499)"
    elif score < 700:
        return "Average (500-699)"
    elif score < 850:
        return "Good (700-849)"
    else:
        return "Excellent (850+)"


class PIIMaskingMixin:
    """Serializer mixin that masks PII fields based on the requesting user's role.

    Usage:
        class MySerializer(PIIMaskingMixin, serializers.ModelSerializer):
            class Meta:
                ...

            PII_MASKED_FIELDS = {
                "annual_income": mask_currency,
                "credit_score": mask_credit_score,
            }
            PII_VISIBLE_ROLES = ("admin", "officer")

    When the requesting user's role is NOT in PII_VISIBLE_ROLES, the fields
    listed in PII_MASKED_FIELDS will have their values replaced by the output
    of the corresponding masking function.
    """

    PII_MASKED_FIELDS: dict = {}
    PII_VISIBLE_ROLES: tuple = ("admin", "officer")

    def to_representation(self, instance):
        data = super().to_representation(instance)

        request = self.context.get("request")
        if request is None:
            return data

        user = getattr(request, "user", None)
        if user is None or not hasattr(user, "role"):
            return data

        if user.role in self.PII_VISIBLE_ROLES:
            return data

        # Mask fields for non-privileged users
        for field_name, mask_fn in self.PII_MASKED_FIELDS.items():
            if field_name in data:
                data[field_name] = mask_fn(data[field_name])

        return data
