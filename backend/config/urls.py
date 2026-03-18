"""
URL configuration for loan approval AI system.
"""

import json

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from rest_framework import status as http_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.loans.models import LoanApplication


class TaskStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):
        """Check the status of an async Celery task with ownership verification."""
        from django_celery_results.models import TaskResult

        try:
            result = TaskResult.objects.get(task_id=task_id)
        except TaskResult.DoesNotExist:
            return Response({
                'task_id': task_id,
                'status': 'PENDING',
                'result': None,
                'date_done': None,
            })

        # Staff can see all tasks
        user = request.user
        if user.role not in ('admin', 'officer'):
            # For completed tasks, verify ownership via application_id in the result
            if result.result:
                try:
                    result_data = json.loads(result.result) if isinstance(result.result, str) else result.result
                    app_id = None
                    if isinstance(result_data, dict):
                        app_id = result_data.get('application_id')
                    if app_id:
                        if not LoanApplication.objects.filter(
                            pk=app_id, applicant=user
                        ).exists():
                            return Response(
                                {'error': 'You do not have permission to view this task'},
                                status=http_status.HTTP_403_FORBIDDEN,
                            )
                    else:
                        # No application_id in result — deny non-staff access
                        return Response(
                            {'error': 'You do not have permission to view this task'},
                            status=http_status.HTTP_403_FORBIDDEN,
                        )
                except (json.JSONDecodeError, TypeError):
                    return Response(
                        {'error': 'You do not have permission to view this task'},
                        status=http_status.HTTP_403_FORBIDDEN,
                    )
            else:
                # PENDING/no result yet — deny non-staff unless they can't trace ownership
                return Response(
                    {'error': 'You do not have permission to view this task'},
                    status=http_status.HTTP_403_FORBIDDEN,
                )

        return Response({
            'task_id': task_id,
            'status': result.status,
            'result': result.result,
            'date_done': result.date_done.isoformat() if result.date_done else None,
        })


def health_check(request):
    """Simple health check endpoint."""
    return JsonResponse({'status': 'ok'})


urlpatterns = [
    path('api/v1/health/', health_check, name='health-check'),
    path('admin/', admin.site.urls),
    path('api/v1/auth/', include('apps.accounts.urls')),
    path('api/v1/loans/', include('apps.loans.urls')),
    path('api/v1/ml/', include('apps.ml_engine.urls')),
    path('api/v1/emails/', include('apps.email_engine.urls')),
    path('api/v1/agents/', include('apps.agents.urls')),
    path('api/v1/tasks/<str:task_id>/status/', TaskStatusView.as_view(), name='task-status'),
]
