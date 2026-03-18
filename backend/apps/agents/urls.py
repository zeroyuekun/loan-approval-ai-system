from django.urls import path

from . import views

urlpatterns = [
    path('orchestrate/<uuid:loan_id>/', views.OrchestrateView.as_view(), name='orchestrate'),
    path('runs/', views.AgentRunListView.as_view(), name='agent-run-list'),
    path('runs/<uuid:loan_id>/', views.AgentRunView.as_view(), name='agent-run'),
    path('review/<uuid:run_id>/', views.HumanReviewView.as_view(), name='human-review'),
]
