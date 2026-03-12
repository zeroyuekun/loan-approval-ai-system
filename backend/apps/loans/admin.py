from django.contrib import admin

from .models import LoanApplication, LoanDecision


@admin.register(LoanApplication)
class LoanApplicationAdmin(admin.ModelAdmin):
    list_display = ('id', 'applicant', 'loan_amount', 'purpose', 'status', 'credit_score', 'created_at')
    list_filter = ('status', 'purpose', 'home_ownership', 'has_cosigner')
    search_fields = ('applicant__username', 'applicant__email', 'notes')
    readonly_fields = ('id', 'created_at', 'updated_at')


@admin.register(LoanDecision)
class LoanDecisionAdmin(admin.ModelAdmin):
    list_display = ('id', 'application', 'decision', 'confidence', 'model_version', 'created_at')
    list_filter = ('decision',)
    search_fields = ('application__applicant__username',)
    readonly_fields = ('id', 'created_at')
