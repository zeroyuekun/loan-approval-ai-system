from rest_framework import serializers

from apps.accounts.models import CustomerProfile
from apps.accounts.serializers import UserSerializer
from .models import AuditLog, FraudCheck, LoanApplication, LoanDecision


class LoanDecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanDecision
        fields = (
            'id', 'decision', 'confidence', 'risk_score',
            'feature_importances', 'shap_values', 'decision_waterfall',
            'model_version', 'reasoning', 'created_at',
        )


class FraudCheckSerializer(serializers.ModelSerializer):
    class Meta:
        model = FraudCheck
        fields = (
            'id', 'passed', 'risk_score', 'checks', 'flagged_reasons',
            'created_at',
        )


class LoanApplicationSerializer(serializers.ModelSerializer):
    decision = LoanDecisionSerializer(read_only=True)
    applicant = UserSerializer(read_only=True)
    latest_fraud_check = serializers.SerializerMethodField()

    class Meta:
        model = LoanApplication
        fields = (
            'id', 'applicant', 'annual_income', 'credit_score', 'loan_amount',
            'loan_term_months', 'debt_to_income', 'employment_length',
            'property_value', 'deposit_amount', 'monthly_expenses',
            'existing_credit_card_limit', 'number_of_dependants',
            'employment_type', 'applicant_type', 'purpose', 'home_ownership',
            'has_cosigner', 'has_hecs', 'has_bankruptcy', 'state',
            'status', 'notes',
            'created_at', 'updated_at', 'decision',
            'latest_fraud_check',
        )
        read_only_fields = ('id', 'status', 'created_at', 'updated_at', 'applicant')

    def get_latest_fraud_check(self, obj):
        fraud_check = obj.fraud_checks.first() if hasattr(obj, 'fraud_checks') else None
        if fraud_check is None:
            return None
        return FraudCheckSerializer(fraud_check).data


class LoanApplicationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanApplication
        fields = (
            'id', 'annual_income', 'credit_score', 'loan_amount', 'loan_term_months',
            'debt_to_income', 'employment_length', 'purpose', 'home_ownership',
            'has_cosigner', 'has_hecs', 'has_bankruptcy', 'state', 'notes',
            'property_value', 'deposit_amount', 'monthly_expenses',
            'existing_credit_card_limit', 'number_of_dependants',
            'employment_type', 'applicant_type',
        )
        read_only_fields = ('id',)

    def validate(self, data):
        user = self.context['request'].user
        if user.role == 'customer':
            try:
                profile = user.profile
            except CustomerProfile.DoesNotExist:
                raise serializers.ValidationError(
                    'You must complete your personal profile before submitting a loan application.'
                )
            if not profile.is_profile_complete:
                missing = profile.missing_profile_fields
                raise serializers.ValidationError({
                    'profile_incomplete': (
                        'Please complete your profile before applying. '
                        f'Missing fields: {", ".join(f.replace("_", " ") for f in missing)}'
                    ),
                    'missing_fields': missing,
                })
        return data

    def create(self, validated_data):
        validated_data['applicant'] = self.context['request'].user
        return super().create(validated_data)


class LoanApplicationCustomerUpdateSerializer(serializers.ModelSerializer):
    """Customers can only update the notes field after submission."""
    class Meta:
        model = LoanApplication
        fields = ('id', 'notes')
        read_only_fields = ('id',)


class AuditLogSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = ('id', 'timestamp', 'username', 'action', 'resource_type', 'resource_id', 'details', 'ip_address')
