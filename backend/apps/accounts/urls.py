from django.http import JsonResponse
from django.urls import path
from django.views.decorators.csrf import ensure_csrf_cookie

from . import views
from .views_2fa import TOTPDisableView, TOTPSetupView, TOTPStatusView, TOTPVerifyView


@ensure_csrf_cookie
def csrf_token_view(request):
    """Set the CSRF cookie so the frontend can include it in mutating requests."""
    return JsonResponse({"detail": "CSRF cookie set."})


urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("refresh/", views.CookieTokenRefreshView.as_view(), name="token-refresh"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("csrf/", csrf_token_view, name="csrf-token"),
    path("me/", views.UserProfileView.as_view(), name="user-profile"),
    path("me/profile/", views.CustomerProfileView.as_view(), name="customer-profile"),
    path("me/data-export/", views.CustomerDataExportView.as_view(), name="customer-data-export"),
    path("customers/", views.StaffCustomerListView.as_view(), name="staff-customer-list"),
    path("customers/<int:user_id>/profile/", views.StaffCustomerProfileView.as_view(), name="staff-customer-profile"),
    path(
        "customers/<int:user_id>/activity/", views.StaffCustomerActivityView.as_view(), name="staff-customer-activity"
    ),
    # Two-Factor Authentication (TOTP)
    path("2fa/setup/", TOTPSetupView.as_view(), name="2fa-setup"),
    path("2fa/verify/", TOTPVerifyView.as_view(), name="2fa-verify"),
    path("2fa/status/", TOTPStatusView.as_view(), name="2fa-status"),
    path("2fa/disable/", TOTPDisableView.as_view(), name="2fa-disable"),
]
