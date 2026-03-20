from django.urls import path
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import JsonResponse

from . import views


@ensure_csrf_cookie
def csrf_token_view(request):
    """Set the CSRF cookie so the frontend can include it in mutating requests."""
    return JsonResponse({'detail': 'CSRF cookie set.'})


urlpatterns = [
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('refresh/', views.CookieTokenRefreshView.as_view(), name='token-refresh'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('csrf/', csrf_token_view, name='csrf-token'),
    path('me/', views.UserProfileView.as_view(), name='user-profile'),
    path('me/profile/', views.CustomerProfileView.as_view(), name='customer-profile'),
    path('me/data-export/', views.CustomerDataExportView.as_view(), name='customer-data-export'),
    path('customers/', views.StaffCustomerListView.as_view(), name='staff-customer-list'),
    path('customers/<int:user_id>/profile/', views.StaffCustomerProfileView.as_view(), name='staff-customer-profile'),
    path('customers/<int:user_id>/activity/', views.StaffCustomerActivityView.as_view(), name='staff-customer-activity'),
]
