from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.models import AgentRun
from apps.agents.tasks import orchestrate_pipeline_task


class OrchestrateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, loan_id):
        """Trigger the full pipeline orchestration for a loan application."""
        task = orchestrate_pipeline_task.delay(str(loan_id))
        return Response(
            {'task_id': task.id, 'status': 'pipeline_queued'},
            status=status.HTTP_202_ACCEPTED,
        )


class AgentRunView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, loan_id):
        """Return the latest AgentRun with all related data for a loan application."""
        agent_run = AgentRun.objects.filter(
            application_id=loan_id
        ).prefetch_related(
            'bias_reports', 'next_best_offers'
        ).first()

        if not agent_run:
            return Response(
                {'error': 'No agent run found for this application'},
                status=status.HTTP_404_NOT_FOUND,
            )

        bias_reports = [
            {
                'id': str(br.id),
                'bias_score': br.bias_score,
                'categories': br.categories,
                'analysis': br.analysis,
                'flagged': br.flagged,
                'requires_human_review': br.requires_human_review,
                'created_at': br.created_at.isoformat(),
            }
            for br in agent_run.bias_reports.all()
        ]

        next_best_offers = [
            {
                'id': str(nbo.id),
                'offers': nbo.offers,
                'analysis': nbo.analysis,
                'created_at': nbo.created_at.isoformat(),
            }
            for nbo in agent_run.next_best_offers.all()
        ]

        return Response({
            'id': str(agent_run.id),
            'application_id': str(agent_run.application_id),
            'status': agent_run.status,
            'steps': agent_run.steps,
            'total_time_ms': agent_run.total_time_ms,
            'error': agent_run.error,
            'bias_reports': bias_reports,
            'next_best_offers': next_best_offers,
            'created_at': agent_run.created_at.isoformat(),
            'updated_at': agent_run.updated_at.isoformat(),
        })
