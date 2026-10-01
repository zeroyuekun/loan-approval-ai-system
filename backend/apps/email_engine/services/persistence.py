import logging

from apps.email_engine.models import GeneratedEmail, GuardrailLog

logger = logging.getLogger(__name__)


class EmailPersistenceService:
    """Single source of truth for email and guardrail persistence.

    Used by email_engine.tasks, the agents email pipeline and human-review
    handler, and the loans decision-review overturn path.
    """

    @staticmethod
    def save_generated_email(application, decision, email_result, model_used=None):
        """Persist a generated email with all metadata.

        ``model_used`` defaults to what the generator reports
        (``"<provider>:<model>"`` for LLM emails, ``"template"`` for the
        deterministic fallback) so Groq/Ollama/template emails are not
        mislabelled as Claude.
        """
        if model_used is None:
            model_used = email_result.get("model_used") or "unknown"
        max_len = GeneratedEmail._meta.get_field("model_used").max_length
        return GeneratedEmail.objects.create(
            application=application,
            decision=decision,
            subject=email_result.get("subject", ""),
            body=email_result.get("body", ""),
            prompt_used=email_result.get("prompt_used", ""),
            model_used=model_used[:max_len],
            generation_time_ms=email_result.get("generation_time_ms", 0),
            attempt_number=email_result.get("attempt_number", 1),
            passed_guardrails=email_result.get("passed_guardrails", False),
            template_fallback=email_result.get("template_fallback", False),
            input_tokens=email_result.get("input_tokens", 0),
            output_tokens=email_result.get("output_tokens", 0),
            estimated_cost_usd=email_result.get("estimated_cost_usd", 0),
        )

    @staticmethod
    def save_guardrail_logs(generated_email, guardrail_results, category="decision"):
        """Bulk-create guardrail log entries."""
        if not guardrail_results:
            return []
        logs = [
            GuardrailLog(
                email=generated_email,
                check_name=check.get("check_name", "unknown"),
                passed=check.get("passed", True),
                details=check.get("details", ""),
                category=check.get("category", category),
            )
            for check in guardrail_results
        ]
        return GuardrailLog.objects.bulk_create(logs)
