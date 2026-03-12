from django.urls import path

from . import views

urlpatterns = [
    path('generate/<uuid:loan_id>/', views.GenerateEmailView.as_view(), name='generate-email'),
    path('<uuid:loan_id>/', views.EmailDetailView.as_view(), name='email-detail'),
]
