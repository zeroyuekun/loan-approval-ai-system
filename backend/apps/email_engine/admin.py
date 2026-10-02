from django.contrib import admin

from apps.common.admin import ViewOnlyModelAdmin

from .models import GeneratedEmail, GuardrailLog


@admin.register(GeneratedEmail)
class GeneratedEmailAdmin(ViewOnlyModelAdmin):
    """View-only: body, subject, guardrail results and sent_at record what
    was generated, checked and sent; they are not edited by hand."""

    list_display = ("id", "application", "decision", "subject", "passed_guardrails", "attempt_number", "created_at")
    list_filter = ("decision", "passed_guardrails", "model_used")
    search_fields = ("subject", "body")
    readonly_fields = ("id", "created_at")


@admin.register(GuardrailLog)
class GuardrailLogAdmin(ViewOnlyModelAdmin):
    list_display = ("id", "email", "check_name", "passed", "created_at")
    list_filter = ("check_name", "passed")
    readonly_fields = ("id", "created_at")
