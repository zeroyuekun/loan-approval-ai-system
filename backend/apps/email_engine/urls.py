from django.urls import path

from . import views

urlpatterns = [
    path('', views.EmailListView.as_view(), name='email-list'),
    path('generate/<uuid:loan_id>/', views.GenerateEmailView.as_view(), name='generate-email'),
    path('send/<uuid:loan_id>/', views.SendLatestEmailView.as_view(), name='send-latest-email'),
    path('<uuid:loan_id>/', views.EmailDetailView.as_view(), name='email-detail'),
]
