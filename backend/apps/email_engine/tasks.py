from celery import shared_task

from apps.email_engine.models import GeneratedEmail, GuardrailLog
from apps.loans.models import LoanApplication


@shared_task(bind=True, name='apps.email_engine.tasks.generate_email_task')
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
    for check in result['guardrail_results']:
        GuardrailLog.objects.create(
            email=email,
            check_name=check['check_name'],
            passed=check['passed'],
            details=check['details'],
        )

    return {
        'email_id': str(email.id),
        'subject': result['subject'],
        'passed_guardrails': result['passed_guardrails'],
        'attempt_number': result['attempt_number'],
    }
