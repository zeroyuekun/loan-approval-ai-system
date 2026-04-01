from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"audit-logs", views.AuditLogViewSet, basename="auditlog")
router.register(r"complaints", views.ComplaintViewSet, basename="complaint")
router.register(r"", views.LoanApplicationViewSet, basename="loan-application")

urlpatterns = [
    path("dashboard-stats/", views.DashboardStatsView.as_view(), name="dashboard-stats"),
    path("", include(router.urls)),
]
