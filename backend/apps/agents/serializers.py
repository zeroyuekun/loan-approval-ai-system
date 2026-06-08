"""DRF serializers for AgentRun and its nested artifacts (L13/L14).

These replace the hand-built response dicts in ``agents/views.py`` that were
duplicated across the list and detail endpoints. The serialized shapes are
byte-equal to the legacy dicts: UUIDs render via ``str(...)`` and timestamps
via ``.isoformat()`` (hence SerializerMethodField rather than raw
UUIDField/DateTimeField, which would change the representation).

The list endpoint nests ``MarketingEmailListSerializer`` (no ``html_body``) so
the 1k-LOC regex HTML renderer is not invoked per marketing email per row in
the paginated hot path (L14). The detail endpoint nests
``MarketingEmailDetailSerializer`` (with ``html_body``).
"""

from rest_framework import serializers

from apps.email_engine.services.html_renderer import render_html


class BiasReportSerializer(serializers.Serializer):
    id = serializers.SerializerMethodField()
    report_type = serializers.CharField()
    bias_score = serializers.IntegerField()
    deterministic_score = serializers.IntegerField()
    score_source = serializers.CharField()
    categories = serializers.JSONField()
    analysis = serializers.CharField()
    flagged = serializers.BooleanField()
    requires_human_review = serializers.BooleanField()
    ai_review_approved = serializers.BooleanField(allow_null=True)
    ai_review_reasoning = serializers.CharField(allow_null=True)
    created_at = serializers.SerializerMethodField()

    def get_id(self, obj):
        return str(obj.id)

    def get_created_at(self, obj):
        return obj.created_at.isoformat()


class NextBestOfferSerializer(serializers.Serializer):
    id = serializers.SerializerMethodField()
    offers = serializers.JSONField()
    analysis = serializers.CharField()
    customer_retention_score = serializers.FloatField()
    loyalty_factors = serializers.JSONField()
    personalized_message = serializers.CharField()
    marketing_message = serializers.CharField()
    created_at = serializers.SerializerMethodField()

    def get_id(self, obj):
        return str(obj.id)

    def get_created_at(self, obj):
        return obj.created_at.isoformat()


class MarketingEmailListSerializer(serializers.Serializer):
    """List variant — omits html_body to avoid per-row HTML rendering (L14)."""

    id = serializers.SerializerMethodField()
    subject = serializers.CharField()
    body = serializers.CharField()
    passed_guardrails = serializers.BooleanField()
    guardrail_results = serializers.JSONField()
    generation_time_ms = serializers.IntegerField(allow_null=True)
    attempt_number = serializers.IntegerField()
    created_at = serializers.SerializerMethodField()

    def get_id(self, obj):
        return str(obj.id)

    def get_created_at(self, obj):
        return obj.created_at.isoformat()


class MarketingEmailDetailSerializer(MarketingEmailListSerializer):
    """Detail variant — includes the rendered html_body."""

    html_body = serializers.SerializerMethodField()

    def get_html_body(self, obj):
        return render_html(obj.body, email_type="marketing")


class AgentRunSerializer(serializers.Serializer):
    """Serializes an AgentRun with its nested bias/NBO/marketing artifacts.

    Pass ``context={"include_html": True}`` (detail) to nest the marketing
    serializer that renders ``html_body``; the default (list) omits it.
    """

    id = serializers.SerializerMethodField()
    application_id = serializers.SerializerMethodField()
    applicant_id = serializers.SerializerMethodField()
    applicant_name = serializers.SerializerMethodField()
    status = serializers.CharField()
    steps = serializers.JSONField()
    total_time_ms = serializers.IntegerField(allow_null=True)
    error = serializers.CharField(allow_null=True)
    bias_reports = serializers.SerializerMethodField()
    next_best_offers = serializers.SerializerMethodField()
    marketing_emails = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    updated_at = serializers.SerializerMethodField()

    def get_id(self, obj):
        return str(obj.id)

    def get_application_id(self, obj):
        return str(obj.application_id)

    def get_applicant_id(self, obj):
        return obj.application.applicant.id

    def get_applicant_name(self, obj):
        applicant = obj.application.applicant
        return f"{applicant.first_name} {applicant.last_name}".strip() or applicant.username

    def get_created_at(self, obj):
        return obj.created_at.isoformat()

    def get_updated_at(self, obj):
        return obj.updated_at.isoformat()

    def get_bias_reports(self, obj):
        return BiasReportSerializer(obj.bias_reports.all(), many=True).data

    def get_next_best_offers(self, obj):
        return NextBestOfferSerializer(obj.next_best_offers.all(), many=True).data

    def get_marketing_emails(self, obj):
        include_html = self.context.get("include_html", False)
        ser = MarketingEmailDetailSerializer if include_html else MarketingEmailListSerializer
        return ser(obj.marketing_emails.all(), many=True).data
