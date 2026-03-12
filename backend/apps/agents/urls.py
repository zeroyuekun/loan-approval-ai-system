from django.urls import path

from . import views

urlpatterns = [
    path('orchestrate/<uuid:loan_id>/', views.OrchestrateView.as_view(), name='orchestrate'),
    path('runs/<uuid:loan_id>/', views.AgentRunView.as_view(), name='agent-run'),
]
