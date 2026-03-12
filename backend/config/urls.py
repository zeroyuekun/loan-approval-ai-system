"""
URL configuration for loan approval AI system.
"""

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def task_status_view(request, task_id):
    """Check the status of an async Celery task."""
    from django_celery_results.models import TaskResult

    try:
        result = TaskResult.objects.get(task_id=task_id)
        return JsonResponse({
            'task_id': task_id,
            'status': result.status,
            'result': result.result,
            'date_done': result.date_done.isoformat() if result.date_done else None,
        })
    except TaskResult.DoesNotExist:
        return JsonResponse({
            'task_id': task_id,
            'status': 'PENDING',
            'result': None,
            'date_done': None,
        })


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/auth/', include('apps.accounts.urls')),
    path('api/v1/loans/', include('apps.loans.urls')),
    path('api/v1/ml/', include('apps.ml_engine.urls')),
    path('api/v1/emails/', include('apps.email_engine.urls')),
    path('api/v1/agents/', include('apps.agents.urls')),
    path('api/v1/tasks/<str:task_id>/status/', task_status_view, name='task-status'),
]
