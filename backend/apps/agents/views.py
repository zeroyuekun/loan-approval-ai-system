from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminOrOfficer
from apps.agents.models import AgentRun
from apps.agents.tasks import orchestrate_pipeline_task, resume_pipeline_task
from apps.loans.models import AuditLog, LoanApplication


class OrchestrationThrottle(UserRateThrottle):
    rate = '60/hour'


def _check_loan_access(user, loan_id):
    """Return (application, error_response) tuple. error_response is None if access is allowed."""
    try:
        application = LoanApplication.objects.get(pk=loan_id)
    except LoanApplication.DoesNotExist:
        return None, Response(
            {'error': 'Loan application not found'},
            status=status.HTTP_404_NOT_FOUND,
        )
    if user.role not in ('admin', 'officer') and application.applicant_id != user.id:
        return None, Response(
            {'error': 'You do not have permission to access this loan application'},
            status=status.HTTP_403_FORBIDDEN,
        )
    return application, None


class AgentRunListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return a paginated list of all agent runs the user can access."""
        user = request.user
        queryset = AgentRun.objects.select_related(
            'application__applicant'
        ).prefetch_related(
            'bias_reports', 'next_best_offers', 'marketing_emails'
        ).order_by('-created_at')

        # Non-staff users can only see runs for their own applications
        if user.role not in ('admin', 'officer'):
            queryset = queryset.filter(application__applicant=user)

        # Simple pagination (clamped to max 100)
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
        runs = queryset[offset:offset + page_size]

        results = []
        for agent_run in runs:
            bias_reports = [
                {
                    'id': str(br.id),
                    'report_type': br.report_type,
                    'bias_score': br.bias_score,
                    'deterministic_score': br.deterministic_score,
                    'score_source': br.score_source,
                    'categories': br.categories,
                    'analysis': br.analysis,
                    'flagged': br.flagged,
                    'requires_human_review': br.requires_human_review,
                    'ai_review_approved': br.ai_review_approved,
                    'ai_review_reasoning': br.ai_review_reasoning,
                    'created_at': br.created_at.isoformat(),
                }
                for br in agent_run.bias_reports.all()
            ]

            next_best_offers = [
                {
                    'id': str(nbo.id),
                    'offers': nbo.offers,
                    'analysis': nbo.analysis,
                    'customer_retention_score': nbo.customer_retention_score,
                    'loyalty_factors': nbo.loyalty_factors,
                    'personalized_message': nbo.personalized_message,
                    'marketing_message': nbo.marketing_message,
                    'created_at': nbo.created_at.isoformat(),
                }
                for nbo in agent_run.next_best_offers.all()
            ]

            marketing_emails = [
                {
                    'id': str(me.id),
                    'subject': me.subject,
                    'body': me.body,
                    'passed_guardrails': me.passed_guardrails,
                    'guardrail_results': me.guardrail_results,
                    'generation_time_ms': me.generation_time_ms,
                    'attempt_number': me.attempt_number,
                    'created_at': me.created_at.isoformat(),
                }
                for me in agent_run.marketing_emails.all()
            ]

            applicant = agent_run.application.applicant
            results.append({
                'id': str(agent_run.id),
                'application_id': str(agent_run.application_id),
                'applicant_id': applicant.id,
                'applicant_name': f'{applicant.first_name} {applicant.last_name}'.strip() or applicant.username,
                'status': agent_run.status,
                'steps': agent_run.steps,
                'total_time_ms': agent_run.total_time_ms,
                'error': agent_run.error,
                'bias_reports': bias_reports,
                'next_best_offers': next_best_offers,
                'marketing_emails': marketing_emails,
                'created_at': agent_run.created_at.isoformat(),
                'updated_at': agent_run.updated_at.isoformat(),
            })

        # Build next/previous URLs
        base_url = request.build_absolute_uri(request.path)
        next_url = f'{base_url}?page={page + 1}&page_size={page_size}' if offset + page_size < total else None
        prev_url = f'{base_url}?page={page - 1}&page_size={page_size}' if page > 1 else None

        return Response({
            'count': total,
            'next': next_url,
            'previous': prev_url,
            'results': results,
        })


class OrchestrateView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [OrchestrationThrottle]

    def post(self, request, loan_id):
        """Trigger the full pipeline orchestration for a loan application."""
        application, error = _check_loan_access(request.user, loan_id)
        if error:
            return error

        task = orchestrate_pipeline_task.delay(str(loan_id))

        AuditLog.objects.create(
            user=request.user,
            action='pipeline_triggered',
            resource_type='LoanApplication',
            resource_id=str(loan_id),
            details={'task_id': task.id},
            ip_address=request.META.get('REMOTE_ADDR'),
        )

        return Response(
            {'task_id': task.id, 'status': 'pipeline_queued'},
            status=status.HTTP_202_ACCEPTED,
        )


class AgentRunView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, loan_id):
        """Return the latest AgentRun with all related data for a loan application."""
        _, error = _check_loan_access(request.user, loan_id)
        if error:
            return error

        agent_run = AgentRun.objects.filter(
            application_id=loan_id
        ).select_related(
            'application__applicant'
        ).prefetch_related(
            'bias_reports', 'next_best_offers', 'marketing_emails'
        ).first()

        if not agent_run:
            return Response(
                {'error': 'No agent run found for this application'},
                status=status.HTTP_404_NOT_FOUND,
            )

        bias_reports = [
            {
                'id': str(br.id),
                'report_type': br.report_type,
                'bias_score': br.bias_score,
                'deterministic_score': br.deterministic_score,
                'score_source': br.score_source,
                'categories': br.categories,
                'analysis': br.analysis,
                'flagged': br.flagged,
                'requires_human_review': br.requires_human_review,
                'ai_review_approved': br.ai_review_approved,
                'ai_review_reasoning': br.ai_review_reasoning,
                'created_at': br.created_at.isoformat(),
            }
            for br in agent_run.bias_reports.all()
        ]

        next_best_offers = [
            {
                'id': str(nbo.id),
                'offers': nbo.offers,
                'analysis': nbo.analysis,
                'customer_retention_score': nbo.customer_retention_score,
                'loyalty_factors': nbo.loyalty_factors,
                'personalized_message': nbo.personalized_message,
                'created_at': nbo.created_at.isoformat(),
            }
            for nbo in agent_run.next_best_offers.all()
        ]

        marketing_emails = [
            {
                'id': str(me.id),
                'subject': me.subject,
                'body': me.body,
                'passed_guardrails': me.passed_guardrails,
                'guardrail_results': me.guardrail_results,
                'generation_time_ms': me.generation_time_ms,
                'attempt_number': me.attempt_number,
                'created_at': me.created_at.isoformat(),
            }
            for me in agent_run.marketing_emails.all()
        ]

        applicant = agent_run.application.applicant
        return Response({
            'id': str(agent_run.id),
            'application_id': str(agent_run.application_id),
            'applicant_id': applicant.id,
            'applicant_name': f'{applicant.first_name} {applicant.last_name}'.strip() or applicant.username,
            'status': agent_run.status,
            'steps': agent_run.steps,
            'total_time_ms': agent_run.total_time_ms,
            'error': agent_run.error,
            'bias_reports': bias_reports,
            'next_best_offers': next_best_offers,
            'marketing_emails': marketing_emails,
            'created_at': agent_run.created_at.isoformat(),
            'updated_at': agent_run.updated_at.isoformat(),
        })


class HumanReviewView(APIView):
    """Lets loan officers approve, deny, or regenerate escalated pipeline runs."""
    permission_classes = [IsAdminOrOfficer]

    def post(self, request, run_id):
        action = request.data.get('action')
        if action not in ('approve', 'deny', 'regenerate'):
            return Response(
                {'error': 'action must be one of: approve, deny, regenerate'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            agent_run = AgentRun.objects.get(pk=run_id)
        except AgentRun.DoesNotExist:
            return Response(
                {'error': 'Agent run not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if agent_run.status != 'escalated':
            return Response(
                {'error': f'Agent run is not escalated (current status: {agent_run.status})'},
                status=status.HTTP_409_CONFLICT,
            )

        reviewer_note = request.data.get('note', '')

        if action == 'approve':
            # Resume the pipeline from where it stopped (NBO + finalization)
            task = resume_pipeline_task.delay(str(run_id), reviewer=request.user.username, note=reviewer_note)

            AuditLog.objects.create(
                user=request.user,
                action='human_review_approve',
                resource_type='AgentRun',
                resource_id=str(run_id),
                details={'note': reviewer_note, 'task_id': task.id},
                ip_address=request.META.get('REMOTE_ADDR'),
            )

            return Response({
                'task_id': task.id,
                'status': 'review_approved_pipeline_resuming',
                'action': 'approve',
            })

        elif action == 'deny':
            # Human override: deny the application immediately
            with transaction.atomic():
                application = agent_run.application
                application.status = 'denied'
                application.save(update_fields=['status'])

                agent_run.steps.append({
                    'step_name': 'human_review_decision',
                    'status': 'completed',
                    'result_summary': {
                        'action': 'deny',
                        'reviewer': request.user.username,
                        'note': reviewer_note,
                    },
                })
                agent_run.status = 'completed'
                agent_run.save()

            AuditLog.objects.create(
                user=request.user,
                action='human_review_deny',
                resource_type='AgentRun',
                resource_id=str(run_id),
                details={'note': reviewer_note, 'application_id': str(application.id)},
                ip_address=request.META.get('REMOTE_ADDR'),
            )

            return Response({
                'status': 'application_denied_by_reviewer',
                'action': 'deny',
            })

        else:  # regenerate
            # Send back through the pipeline for a fresh email + bias check
            task = orchestrate_pipeline_task.delay(str(agent_run.application_id))

            with transaction.atomic():
                agent_run.steps.append({
                    'step_name': 'human_review_decision',
                    'status': 'completed',
                    'result_summary': {
                        'action': 'regenerate',
                        'reviewer': request.user.username,
                        'note': reviewer_note,
                    },
                })
                agent_run.status = 'completed'
                agent_run.save()

            AuditLog.objects.create(
                user=request.user,
                action='human_review_regenerate',
                resource_type='AgentRun',
                resource_id=str(run_id),
                details={'note': reviewer_note, 'application_id': str(agent_run.application_id), 'task_id': task.id},
                ip_address=request.META.get('REMOTE_ADDR'),
            )

            return Response({
                'task_id': task.id,
                'status': 'regeneration_queued',
                'action': 'regenerate',
            })
