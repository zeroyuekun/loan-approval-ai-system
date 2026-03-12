from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r'', views.LoanApplicationViewSet, basename='loan-application')

urlpatterns = [
    path('', include(router.urls)),
]
