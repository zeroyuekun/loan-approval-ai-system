from rest_framework import serializers

from .models import LoanApplication, LoanDecision


class LoanDecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanDecision
        fields = '__all__'
        read_only_fields = fields


class LoanApplicationSerializer(serializers.ModelSerializer):
    decision = LoanDecisionSerializer(read_only=True)
    applicant_username = serializers.CharField(source='applicant.username', read_only=True)

    class Meta:
        model = LoanApplication
        fields = '__all__'
        read_only_fields = ('id', 'status', 'created_at', 'updated_at', 'applicant')


class LoanApplicationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanApplication
        fields = (
            'annual_income', 'credit_score', 'loan_amount', 'loan_term_months',
            'debt_to_income', 'employment_length', 'purpose', 'home_ownership',
            'has_cosigner', 'notes',
        )

    def create(self, validated_data):
        validated_data['applicant'] = self.context['request'].user
        return super().create(validated_data)
