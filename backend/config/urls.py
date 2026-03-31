"""
URL configuration for loan approval AI system.
"""

import json

from django.contrib import admin
from django.http import HttpResponse, JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
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
            return Response(
                {
                    "task_id": task_id,
                    "status": "PENDING",
                    "result": None,
                    "date_done": None,
                }
            )

        # Staff can see all tasks
        user = request.user
        if user.role not in ("admin", "officer"):
            # For completed tasks, verify ownership via application_id in the result
            if result.result:
                try:
                    result_data = json.loads(result.result) if isinstance(result.result, str) else result.result
                    app_id = None
                    if isinstance(result_data, dict):
                        app_id = result_data.get("application_id")
                    if app_id:
                        if not LoanApplication.objects.filter(pk=app_id, applicant=user).exists():
                            return Response(
                                {"error": "You do not have permission to view this task"},
                                status=http_status.HTTP_403_FORBIDDEN,
                            )
                    else:
                        # No application_id in result — deny non-staff access
                        return Response(
                            {"error": "You do not have permission to view this task"},
                            status=http_status.HTTP_403_FORBIDDEN,
                        )
                except (json.JSONDecodeError, TypeError):
                    return Response(
                        {"error": "You do not have permission to view this task"},
                        status=http_status.HTTP_403_FORBIDDEN,
                    )
            else:
                # PENDING/no result yet — deny non-staff unless they can't trace ownership
                return Response(
                    {"error": "You do not have permission to view this task"},
                    status=http_status.HTTP_403_FORBIDDEN,
                )

        return Response(
            {
                "task_id": task_id,
                "status": result.status,
                "result": result.result,
                "date_done": result.date_done.isoformat() if result.date_done else None,
            }
        )


def security_txt(request):
    """RFC 9116 security.txt — vulnerability disclosure policy."""
    content = (
        "Contact: mailto:security@aussieloanai.com.au\n"
        "Preferred-Languages: en\n"
        "Canonical: https://aussieloanai.com.au/.well-known/security.txt\n"
        "Policy: https://aussieloanai.com.au/security-policy\n"
        "Expires: 2027-03-31T00:00:00.000Z\n"
    )
    return HttpResponse(content, content_type="text/plain")


def health_check(request):
    """Simple health check endpoint."""
    return JsonResponse({"status": "ok"})


def deep_health_check(request):
    """Deep health check verifying DB, Redis, and ML model availability."""
    checks = {}

    # Database
    try:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Redis
    try:
        import redis
        from django.conf import settings as django_settings

        broker_url = django_settings.CELERY_BROKER_URL
        r = redis.from_url(broker_url, socket_connect_timeout=3)
        r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    # Active ML model (non-blocking — ML can be trained after startup)
    try:
        from apps.ml_engine.models import ModelVersion

        active_model = ModelVersion.objects.filter(is_active=True).first()
        if active_model:
            checks["ml_model"] = "ok"
            checks["ml_model_version"] = active_model.version
            checks["ml_algorithm"] = active_model.algorithm
            checks["ml_trained_at"] = active_model.created_at.isoformat() if active_model.created_at else None
        else:
            checks["ml_model"] = "no active model (non-blocking)"
    except Exception as e:
        checks["ml_model"] = f"error: {e}"

    # Celery queue depth (non-blocking)
    try:
        import redis
        from django.conf import settings as django_settings

        r = redis.from_url(django_settings.CELERY_BROKER_URL, socket_connect_timeout=2)
        queue_depths = {}
        for queue_name in ("celery", "ml", "email", "agents"):
            queue_depths[queue_name] = r.llen(queue_name)
        checks["celery_queue_depth"] = queue_depths
        total_queued = sum(queue_depths.values())
        if total_queued > 500:
            checks["celery_queue_status"] = "critical"
        elif total_queued > 100:
            checks["celery_queue_status"] = "warning"
        else:
            checks["celery_queue_status"] = "ok"
    except Exception:
        checks["celery_queue_depth"] = "unavailable"

    # API budget remaining (non-blocking)
    try:
        from datetime import date

        import redis
        from django.conf import settings as django_settings

        r = redis.from_url(django_settings.CELERY_BROKER_URL, socket_connect_timeout=2)
        today = date.today().isoformat()
        cost_cents = int(r.get(f"ai_budget:{today}:cost_cents") or 0)
        call_count = int(r.get(f"ai_budget:{today}:calls") or 0)
        budget_limit = getattr(django_settings, "AI_DAILY_BUDGET_LIMIT_USD", 5.0)
        call_limit = getattr(django_settings, "AI_DAILY_CALL_LIMIT", 500)
        checks["api_budget"] = {
            "spent_usd": round(cost_cents / 100, 2),
            "limit_usd": budget_limit,
            "calls_today": call_count,
            "call_limit": call_limit,
            "circuit_breaker": "open" if r.exists("ai_budget:circuit_breaker") else "closed",
        }
    except Exception:
        checks["api_budget"] = "unavailable"

    # Only database and Redis are required for startup; ML model is optional
    core_checks = {k: v for k, v in checks.items() if k in ("database", "redis")}
    all_ok = all(v == "ok" for v in core_checks.values())
    status_code = 200 if all_ok else 503
    checks["status"] = "healthy" if all_ok else "degraded"

    return JsonResponse(checks, status=status_code)


urlpatterns = [
    path("", include("django_prometheus.urls")),
    path(".well-known/security.txt", security_txt, name="security-txt"),
    path("api/v1/health/", health_check, name="health-check"),
    path("api/v1/health/deep/", deep_health_check, name="deep-health-check"),
    path("api/v1/health/ready/", deep_health_check, name="readiness-probe"),
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/loans/", include("apps.loans.urls")),
    path("api/v1/ml/", include("apps.ml_engine.urls")),
    path("api/v1/emails/", include("apps.email_engine.urls")),
    path("api/v1/agents/", include("apps.agents.urls")),
    path("api/v1/tasks/<str:task_id>/status/", TaskStatusView.as_view(), name="task-status"),
    # API Documentation
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
