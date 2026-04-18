"""accounts views package — re-exports all view classes for urls.py and tests."""

from ._shared import (
    DataExportThrottle,
    LoginRateThrottle,
    RefreshRateThrottle,
    RegisterRateThrottle,
)
from .auth import CookieTokenRefreshView, LoginView, LogoutView, RegisterView
from .export import CustomerDataExportView
from .profile import CustomerProfileView, UserProfileView
from .staff import StaffCustomerActivityView, StaffCustomerListView, StaffCustomerProfileView

__all__ = [
    # auth
    "CookieTokenRefreshView",
    "LoginView",
    "LogoutView",
    "RegisterView",
    # profile
    "CustomerProfileView",
    "UserProfileView",
    # staff
    "StaffCustomerActivityView",
    "StaffCustomerListView",
    "StaffCustomerProfileView",
    # export
    "CustomerDataExportView",
    # throttles (importable for tests/overrides)
    "DataExportThrottle",
    "LoginRateThrottle",
    "RefreshRateThrottle",
    "RegisterRateThrottle",
]
