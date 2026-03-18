from celery import shared_task

from apps.email_engine.models import GeneratedEmail, GuardrailLog
from apps.loans.models import LoanApplication


@shared_task(bind=True, name='apps.email_engine.tasks.generate_email_task', time_limit=120, autoretry_for=(ConnectionError, TimeoutError, OSError), retry_backoff=True, max_retries=3)
def generate_email_task(self, application_id, decision):
    """Generate a decision email for a loan application."""
    from apps.email_engine.services.email_generator import EmailGenerator

    application = LoanApplication.objects.select_related('applicant', 'decision').get(pk=application_id)

    generator = EmailGenerator()
    result = generator.generate(application, decision)

    # Save email record
    email = GeneratedEmail.objects.create(
        application=application,
        decision=decision,
        subject=result['subject'],
        body=result['body'],
        prompt_used=result['prompt_used'],
        model_used='claude-sonnet-4-20250514',
        generation_time_ms=result['generation_time_ms'],
        attempt_number=result['attempt_number'],
        passed_guardrails=result['passed_guardrails'],
    )

    # Save guardrail logs
    GuardrailLog.objects.bulk_create([
        GuardrailLog(
            email=email,
            check_name=check['check_name'],
            passed=check['passed'],
            details=check['details'],
        )
        for check in result['guardrail_results']
    ])

    # Send email to customer if guardrails passed
    email_sent = False
    if result['passed_guardrails'] and application.applicant.email:
        from apps.email_engine.services.sender import send_decision_email
        email_sent = send_decision_email(
            recipient_email=application.applicant.email,
            subject=result['subject'],
            body=result['body'],
        )

    return {
        'email_id': str(email.id),
        'subject': result['subject'],
        'passed_guardrails': result['passed_guardrails'],
        'attempt_number': result['attempt_number'],
        'email_sent': email_sent,
    }
