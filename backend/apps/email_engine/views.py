from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.email_engine.models import GeneratedEmail, GuardrailLog
from apps.email_engine.tasks import generate_email_task
from apps.loans.permissions import check_loan_access


class EmailGenerationThrottle(UserRateThrottle):
    rate = '10/hour'


class EmailListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return a paginated list of all generated emails the user can access."""
        user = request.user
        queryset = GeneratedEmail.objects.select_related(
            'application', 'application__applicant'
        ).prefetch_related('guardrail_checks').order_by('-created_at')

        if user.role not in ('admin', 'officer'):
            queryset = queryset.filter(application__applicant=user)

        try:
            page = int(request.query_params.get('page', 1))
        except (ValueError, TypeError):
            page = 1
        try:
            page_size = min(int(request.query_params.get('page_size', 20)), 100)
        except (ValueError, TypeError):
            page_size = 20
        total = queryset.count()
        offset = (page - 1) * page_size
        emails = queryset[offset:offset + page_size]

        results = []
        for email in emails:
            guardrail_checks = [
                {
                    'check_name': log.check_name,
                    'passed': log.passed,
                    'details': log.details,
                }
                for log in email.guardrail_checks.all()
            ]
            applicant = email.application.applicant
            results.append({
                'id': str(email.id),
                'application_id': str(email.application_id),
                'applicant_id': applicant.id,
                'applicant_name': f'{applicant.first_name} {applicant.last_name}'.strip() or applicant.username,
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

        base_url = request.build_absolute_uri(request.path)
        next_url = f'{base_url}?page={page + 1}&page_size={page_size}' if offset + page_size < total else None
        prev_url = f'{base_url}?page={page - 1}&page_size={page_size}' if page > 1 else None

        return Response({
            'count': total,
            'next': next_url,
            'previous': prev_url,
            'results': results,
        })


class GenerateEmailView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [EmailGenerationThrottle]

    def post(self, request, loan_id):
        """Trigger email generation for a loan application."""
        check_loan_access(request, loan_id)

        decision = request.data.get('decision', 'approved')
        if decision not in ('approved', 'denied'):
            return Response(
                {'error': "decision must be 'approved' or 'denied'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        task = generate_email_task.delay(str(loan_id), decision)
        return Response(
            {'task_id': task.id, 'status': 'email_generation_queued'},
            status=status.HTTP_202_ACCEPTED,
        )


class EmailDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, loan_id):
        """Return the latest generated email for an application."""
        check_loan_access(request, loan_id)

        email = GeneratedEmail.objects.filter(
            application_id=loan_id
        ).select_related('application__applicant').prefetch_related('guardrail_checks').first()

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

        applicant = email.application.applicant
        return Response({
            'id': str(email.id),
            'application_id': str(email.application_id),
            'applicant_id': applicant.id,
            'applicant_name': f'{applicant.first_name} {applicant.last_name}'.strip() or applicant.username,
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
