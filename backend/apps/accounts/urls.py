from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

urlpatterns = [
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('me/', views.UserProfileView.as_view(), name='user-profile'),
    path('me/profile/', views.CustomerProfileView.as_view(), name='customer-profile'),
    path('customers/', views.StaffCustomerListView.as_view(), name='staff-customer-list'),
    path('customers/<int:user_id>/profile/', views.StaffCustomerProfileView.as_view(), name='staff-customer-profile'),
    path('customers/<int:user_id>/activity/', views.StaffCustomerActivityView.as_view(), name='staff-customer-activity'),
]
