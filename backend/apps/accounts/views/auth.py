"""Authentication views: login, register, logout, token refresh."""

import logging

from django.conf import settings as django_settings
from django.contrib.auth.hashers import check_password, make_password
from django.middleware.csrf import get_token as get_csrf_token
from django.middleware.csrf import rotate_token
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.loans.models import AuditLog

from ..models import CustomUser
from ..serializers import LoginSerializer, RegisterSerializer, UserSerializer
from ._shared import (
    LoginRateThrottle,
    RefreshRateThrottle,
    RegisterRateThrottle,
    clear_jwt_cookies,
    set_jwt_cookies,
)

logger = logging.getLogger(__name__)


class CookieTokenRefreshView(generics.GenericAPIView):
    """Refresh JWT tokens using the HttpOnly refresh cookie."""

    permission_classes = (AllowAny,)
    throttle_classes = (RefreshRateThrottle,)

    def post(self, request, *args, **kwargs):
        refresh_name = getattr(django_settings, "JWT_REFRESH_COOKIE_NAME", "refresh_token")
        raw_refresh = request.COOKIES.get(refresh_name) or request.data.get("refresh")
        if not raw_refresh:
            return Response(
                {"detail": "No refresh token provided."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        try:
            refresh = RefreshToken(raw_refresh)
            new_access = refresh.access_token

            # Rotate refresh token if configured
            if django_settings.SIMPLE_JWT.get("ROTATE_REFRESH_TOKENS", False):
                if django_settings.SIMPLE_JWT.get("BLACKLIST_AFTER_ROTATION", False):
                    try:
                        refresh.blacklist()
                    except AttributeError:
                        logging.getLogger("accounts").debug("Token blacklist not available — skipping")
                refresh = RefreshToken.for_user(self._get_user_from_token(refresh))
                new_access = refresh.access_token

            response = Response({"detail": "Token refreshed."})
            set_jwt_cookies(response, new_access, refresh)
            return response
        except TokenError:
            response = Response(
                {"detail": "Token is invalid or expired."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            clear_jwt_cookies(response)
            return response
        except Exception:
            logger.exception("Unexpected error during token refresh")
            response = Response(
                {"detail": "Token refresh failed."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
            clear_jwt_cookies(response)
            return response

    def _get_user_from_token(self, token):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        try:
            return User.objects.get(pk=token["user_id"])
        except User.DoesNotExist as exc:
            # Deleted-user race: token is cryptographically valid but its
            # subject no longer exists. Treat as invalid token (401) rather
            # than letting the outer handler return 500.
            raise TokenError("user no longer exists") from exc


class RegisterView(generics.CreateAPIView):
    queryset = CustomUser.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = (AllowAny,)
    throttle_classes = (RegisterRateThrottle,)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)

        AuditLog.objects.create(
            user=user,
            action="register",
            resource_type="CustomUser",
            resource_id=str(user.id),
            details={"username": user.username},
            ip_address=request.META.get("REMOTE_ADDR"),
        )

        response = Response(
            {
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )
        set_jwt_cookies(response, refresh.access_token, refresh)
        # Ensure CSRF cookie is set for subsequent mutating requests
        get_csrf_token(request)
        return response


class LoginView(generics.GenericAPIView):
    serializer_class = LoginSerializer
    permission_classes = (AllowAny,)
    throttle_classes = (LoginRateThrottle,)

    # Dummy password used to burn CPU time when the username doesn't exist,
    # so that the response timing is indistinguishable from a real lookup.
    _DUMMY_HASH = make_password("dummy-timing-equalizer")

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        generic_error = {"detail": "Invalid username or password."}

        # Check if account is locked before attempting authentication
        username = request.data.get("username", "")
        user_obj = None
        if username:
            try:
                user_obj = CustomUser.objects.get(username=username)
            except CustomUser.DoesNotExist:
                # Perform a dummy password check to equalise timing
                check_password(request.data.get("password", ""), self._DUMMY_HASH)

        if user_obj and user_obj.is_locked:
            AuditLog.objects.create(
                user=user_obj,
                action="login_blocked_locked",
                resource_type="CustomUser",
                resource_id=str(user_obj.id),
                details={"reason": "account_locked"},
                ip_address=request.META.get("REMOTE_ADDR"),
            )
            return Response(generic_error, status=status.HTTP_400_BAD_REQUEST)

        if not serializer.is_valid():
            # Record failed login attempt
            if user_obj:
                user_obj.record_failed_login()
                AuditLog.objects.create(
                    user=user_obj,
                    action="login_failed",
                    resource_type="CustomUser",
                    resource_id=str(user_obj.id),
                    details={"failed_attempts": user_obj.failed_login_attempts},
                    ip_address=request.META.get("REMOTE_ADDR"),
                )
            return Response(generic_error, status=status.HTTP_400_BAD_REQUEST)

        user = serializer.validated_data["user"]
        user.reset_failed_logins()

        refresh = RefreshToken.for_user(user)

        AuditLog.objects.create(
            user=user,
            action="login_success",
            resource_type="CustomUser",
            resource_id=str(user.id),
            details={},
            ip_address=request.META.get("REMOTE_ADDR"),
        )

        response = Response(
            {
                "user": UserSerializer(user).data,
            }
        )
        set_jwt_cookies(response, refresh.access_token, refresh)
        rotate_token(request)
        get_csrf_token(request)
        return response


class LogoutView(generics.GenericAPIView):
    """Blacklist the refresh token and clear auth cookies."""

    permission_classes = (IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        # Try cookie first, then request body (backwards compat)
        refresh_name = getattr(django_settings, "JWT_REFRESH_COOKIE_NAME", "refresh_token")
        refresh = request.COOKIES.get(refresh_name) or request.data.get("refresh")
        if not refresh:
            response = Response(
                {"detail": "refresh token is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
            clear_jwt_cookies(response)
            return response
        try:
            token = RefreshToken(refresh)
            token.blacklist()
        except TokenError as exc:
            logger.debug(
                "logout_token_already_invalid",
                extra={"user_id": str(request.user.id), "error": type(exc).__name__},
            )

        AuditLog.objects.create(
            user=request.user,
            action="logout",
            resource_type="CustomUser",
            resource_id=str(request.user.id),
            details={},
            ip_address=request.META.get("REMOTE_ADDR"),
        )

        response = Response({"detail": "Successfully logged out."}, status=status.HTTP_200_OK)
        clear_jwt_cookies(response)
        return response
