from django.urls import path

from . import views

urlpatterns = [
    path("predict/<uuid:loan_id>/", views.PredictView.as_view(), name="ml-predict"),
    path("quote/", views.QuoteView.as_view(), name="ml-quote"),
    path("models/active/metrics/", views.ModelMetricsView.as_view(), name="model-metrics"),
    path("models/active/drift/", views.ModelDriftView.as_view(), name="model-drift"),
    path("models/train/", views.TrainModelView.as_view(), name="model-train"),
    path("models/active/model-card/", views.ModelCardView.as_view(), name="model-card"),
    path("models/", views.ModelVersionListView.as_view(), name="model-list"),
    path("models/<uuid:pk>/activate/", views.ModelActivateView.as_view(), name="model-activate"),
    path("models/<uuid:pk>/traffic/", views.ModelTrafficView.as_view(), name="model-traffic"),
    path("models/compare/", views.ModelCompareView.as_view(), name="model-compare"),
    path("models/active/drift-reports/", views.DriftReportListView.as_view(), name="drift-report-list"),
]
