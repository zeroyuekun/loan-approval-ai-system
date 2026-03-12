from django.contrib import admin

from .models import GeneratedEmail, GuardrailLog


@admin.register(GeneratedEmail)
class GeneratedEmailAdmin(admin.ModelAdmin):
    list_display = ('id', 'application', 'decision', 'subject', 'passed_guardrails', 'attempt_number', 'created_at')
    list_filter = ('decision', 'passed_guardrails', 'model_used')
    search_fields = ('subject', 'body')
    readonly_fields = ('id', 'created_at')


@admin.register(GuardrailLog)
class GuardrailLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'email', 'check_name', 'passed', 'created_at')
    list_filter = ('check_name', 'passed')
    readonly_fields = ('id', 'created_at')
