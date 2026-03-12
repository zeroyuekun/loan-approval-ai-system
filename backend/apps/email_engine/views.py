from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.email_engine.models import GeneratedEmail, GuardrailLog
from apps.email_engine.tasks import generate_email_task


class GenerateEmailView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, loan_id):
        """Trigger email generation for a loan application."""
        decision = request.data.get('decision', 'approved')
        task = generate_email_task.delay(str(loan_id), decision)
        return Response(
            {'task_id': task.id, 'status': 'email_generation_queued'},
            status=status.HTTP_202_ACCEPTED,
        )


class EmailDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, loan_id):
        """Return the latest generated email for an application."""
        email = GeneratedEmail.objects.filter(
            application_id=loan_id
        ).select_related('application').prefetch_related('guardrail_checks').first()

        if not email:
            return Response(
                {'error': 'No email found for this application'},
                status=status.HTTP_404_NOT_FOUND,
            )

        guardrail_checks = [
            {
                'check_name': log.check_name,
                'passed': log.passed,
                'details': log.details,
            }
            for log in email.guardrail_checks.all()
        ]

        return Response({
            'id': str(email.id),
            'application_id': str(email.application_id),
            'decision': email.decision,
            'subject': email.subject,
            'body': email.body,
            'model_used': email.model_used,
            'generation_time_ms': email.generation_time_ms,
            'attempt_number': email.attempt_number,
            'passed_guardrails': email.passed_guardrails,
            'guardrail_checks': guardrail_checks,
            'created_at': email.created_at.isoformat(),
        })
