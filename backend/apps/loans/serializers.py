from rest_framework import serializers

from apps.accounts.models import CustomerProfile
from apps.accounts.serializers import UserSerializer
from apps.ml_engine.services.reason_codes import (
    generate_adverse_action_reasons,
    generate_reapplication_guidance,
)
from utils.pii_masking import PIIMaskingMixin, mask_credit_score, mask_currency

from .models import AuditLog, Complaint, FraudCheck, LoanApplication, LoanDecision


class LoanDecisionSerializer(serializers.ModelSerializer):
    model_version = serializers.SerializerMethodField()
    model_version_name = serializers.SerializerMethodField()

    class Meta:
        model = LoanDecision
        fields = (
            "id",
            "decision",
            "confidence",
            "risk_score",
            "feature_importances",
            "shap_values",
            "decision_waterfall",
            "model_version",
            "model_version_name",
            "reasoning",
            "created_at",
        )

    def get_model_version(self, obj):
        """Return the model version ID as a string for backward compatibility."""
        return str(obj.model_version_id) if obj.model_version_id else None

    def get_model_version_name(self, obj):
        """Return a human-readable model version string."""
        if obj.model_version:
            return f"{obj.model_version.algorithm} v{obj.model_version.version}"
        return None


class CustomerLoanDecisionSerializer(serializers.ModelSerializer):
    denial_reasons = serializers.SerializerMethodField()
    reapplication_guidance = serializers.SerializerMethodField()

    class Meta:
        model = LoanDecision
        fields = (
            "id",
            "decision",
            "created_at",
            "denial_reasons",
            "reapplication_guidance",
        )

    def get_denial_reasons(self, obj):
        return generate_adverse_action_reasons(obj.shap_values or {}, obj.decision)

    def get_reapplication_guidance(self, obj):
        if obj.decision != "denied":
            return None
        reasons = self.get_denial_reasons(obj)
        return generate_reapplication_guidance([], reasons)


class FraudCheckSerializer(serializers.ModelSerializer):
    class Meta:
        model = FraudCheck
        fields = (
            "id",
            "passed",
            "risk_score",
            "checks",
            "flagged_reasons",
            "created_at",
        )


class LoanApplicationSerializer(serializers.ModelSerializer):
    decision = LoanDecisionSerializer(read_only=True)
    applicant = UserSerializer(read_only=True)
    latest_fraud_check = serializers.SerializerMethodField()

    class Meta:
        model = LoanApplication
        fields = (
            "id",
            "applicant",
            "annual_income",
            "credit_score",
            "loan_amount",
            "loan_term_months",
            "debt_to_income",
            "employment_length",
            "property_value",
            "deposit_amount",
            "monthly_expenses",
            "existing_credit_card_limit",
            "number_of_dependants",
            "employment_type",
            "applicant_type",
            "purpose",
            "home_ownership",
            "has_cosigner",
            "has_hecs",
            "has_bankruptcy",
            "state",
            "status",
            "notes",
            "conditions",
            "conditions_met",
            "consumer_objectives",
            "consumer_requirements",
            "financial_situation_notes",
            "created_at",
            "updated_at",
            "decision",
            "latest_fraud_check",
        )
        read_only_fields = (
            "id",
            "status",
            "created_at",
            "updated_at",
            "applicant",
            "consumer_objectives",
            "consumer_requirements",
            "financial_situation_notes",
        )

    def get_latest_fraud_check(self, obj):
        # Use .all() to hit the prefetch cache — .first() bypasses it and causes N+1
        fraud_checks = list(obj.fraud_checks.all()[:1]) if hasattr(obj, "fraud_checks") else []
        if not fraud_checks:
            return None
        return FraudCheckSerializer(fraud_checks[0]).data


class CustomerLoanApplicationSerializer(PIIMaskingMixin, serializers.ModelSerializer):
    decision = CustomerLoanDecisionSerializer(read_only=True)

    PII_MASKED_FIELDS = {
        "annual_income": mask_currency,
        "credit_score": mask_credit_score,
        "loan_amount": mask_currency,
        "monthly_expenses": mask_currency,
    }

    class Meta:
        model = LoanApplication
        fields = (
            "id",
            "annual_income",
            "credit_score",
            "loan_amount",
            "loan_term_months",
            "debt_to_income",
            "employment_length",
            "property_value",
            "deposit_amount",
            "monthly_expenses",
            "number_of_dependants",
            "employment_type",
            "purpose",
            "home_ownership",
            "has_cosigner",
            "has_hecs",
            "status",
            "notes",
            "conditions",
            "conditions_met",
            "consumer_objectives",
            "consumer_requirements",
            "financial_situation_notes",
            "created_at",
            "updated_at",
            "decision",
        )
        read_only_fields = ("id", "status", "created_at", "updated_at")


class LoanApplicationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanApplication
        fields = (
            "id",
            "annual_income",
            "credit_score",
            "loan_amount",
            "loan_term_months",
            "debt_to_income",
            "employment_length",
            "purpose",
            "home_ownership",
            "has_cosigner",
            "has_hecs",
            "has_bankruptcy",
            "state",
            "notes",
            "property_value",
            "deposit_amount",
            "monthly_expenses",
            "existing_credit_card_limit",
            "number_of_dependants",
            "employment_type",
            "applicant_type",
            "consumer_objectives",
            "consumer_requirements",
            "financial_situation_notes",
        )
        read_only_fields = ("id",)

    def validate(self, data):
        user = self.context["request"].user
        if user.role == "customer":
            try:
                profile = user.profile
            except CustomerProfile.DoesNotExist as err:
                raise serializers.ValidationError(
                    "You must complete your personal profile before submitting a loan application."
                ) from err
            if not profile.is_profile_complete:
                missing = profile.missing_profile_fields
                raise serializers.ValidationError(
                    {
                        "profile_incomplete": (
                            "Please complete your profile before applying. "
                            f"Missing fields: {', '.join(f.replace('_', ' ') for f in missing)}"
                        ),
                        "missing_fields": missing,
                    }
                )
        return data

    def create(self, validated_data):
        validated_data["applicant"] = self.context["request"].user
        return super().create(validated_data)


class LoanApplicationCustomerUpdateSerializer(serializers.ModelSerializer):
    """Customers can only update the notes field after submission."""

    class Meta:
        model = LoanApplication
        fields = ("id", "notes")
        read_only_fields = ("id",)


class AuditLogSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = ("id", "timestamp", "username", "action", "resource_type", "resource_id", "details", "ip_address")


class ComplaintSerializer(serializers.ModelSerializer):
    complainant_name = serializers.CharField(source="complainant.get_full_name", read_only=True)
    description = serializers.CharField(max_length=10000)

    class Meta:
        model = Complaint
        fields = (
            "id",
            "complainant",
            "complainant_name",
            "loan_application",
            "category",
            "status",
            "subject",
            "description",
            "resolution",
            "acknowledged_at",
            "resolved_at",
            "sla_deadline",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "complainant",
            "acknowledged_at",
            "sla_deadline",
            "created_at",
            "updated_at",
        )

    def create(self, validated_data):
        from datetime import timedelta

        from django.utils import timezone

        now = timezone.now()
        validated_data["complainant"] = self.context["request"].user
        validated_data["acknowledged_at"] = now

        # ASIC RG 271: 21 days for credit-related, 30 days for standard
        category = validated_data.get("category", "other")
        sla_days = 21 if category == "decision" else 30
        validated_data["sla_deadline"] = now + timedelta(days=sla_days)

        return super().create(validated_data)
