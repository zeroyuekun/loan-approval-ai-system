import django_filters

from .models import LoanApplication


class LoanApplicationFilter(django_filters.FilterSet):
    applicant = django_filters.NumberFilter(field_name='applicant_id')
    status = django_filters.ChoiceFilter(choices=LoanApplication.Status.choices)
    purpose = django_filters.ChoiceFilter(choices=LoanApplication.Purpose.choices)
    credit_score_min = django_filters.NumberFilter(field_name='credit_score', lookup_expr='gte')
    credit_score_max = django_filters.NumberFilter(field_name='credit_score', lookup_expr='lte')
    loan_amount_min = django_filters.NumberFilter(field_name='loan_amount', lookup_expr='gte')
    loan_amount_max = django_filters.NumberFilter(field_name='loan_amount', lookup_expr='lte')
    created_after = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')

    class Meta:
        model = LoanApplication
        fields = ['status', 'purpose']
