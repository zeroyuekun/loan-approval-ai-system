import logging
from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib.auth.hashers import check_password, make_password
from django.db.models import Prefetch, Q
from django.middleware.csrf import get_token as get_csrf_token
from django.middleware.csrf import rotate_token
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.agents.models import AgentRun, MarketingEmail
from apps.common.http import client_ip
from apps.email_engine.models import GeneratedEmail
from apps.loans.models import AuditLog, LoanApplication, LoanDecision

from .authentication import CookieJWTAuthentication
from .models import CustomerProfile, CustomUser
from .permissions import IsAdminOrOfficer
from .serializers import (
    AdminCustomerProfileUpdateSerializer,
    CustomerProfileSerializer,
    LoginSerializer,
    RegisterSerializer,
    StaffCustomerDetailSerializer,
    UserSerializer,
)
from .services.customer_activity import customer_activity

logger = logging.getLogger(__name__)


def _set_jwt_cookies(response, access_token, refresh_token):
    """Set JWT tokens as HttpOnly cookies on the response."""
    secure = getattr(django_settings, "JWT_COOKIE_SECURE", True)
    samesite = getattr(django_settings, "JWT_COOKIE_SAMESITE", "Lax")
    access_name = getattr(django_settings, "JWT_ACCESS_COOKIE_NAME", "access_token")
    refresh_name = getattr(django_settings, "JWT_REFRESH_COOKIE_NAME", "refresh_token")

    access_max_age = int(django_settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds())
    refresh_max_age = int(django_settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds())

    response.set_cookie(
        access_name,
        str(access_token),
        max_age=access_max_age,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
    )
    response.set_cookie(
        refresh_name,
        str(refresh_token),
        max_age=refresh_max_age,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
    )
    return response


def _clear_jwt_cookies(response):
    """Remove JWT cookies from the response."""
    access_name = getattr(django_settings, "JWT_ACCESS_COOKIE_NAME", "access_token")
    refresh_name = getattr(django_settings, "JWT_REFRESH_COOKIE_NAME", "refresh_token")
    response.delete_cookie(access_name, path="/")
    response.delete_cookie(refresh_name, path="/")
    return response


def _audit_user_event(request, user, action, details=None):
    """Write an AuditLog row for an auth event on ``user``'s own account."""
    AuditLog.objects.create(
        user=user,
        action=action,
        resource_type="CustomUser",
        resource_id=str(user.id),
        details=details or {},
        ip_address=client_ip(request),
    )


class RefreshRateThrottle(AnonRateThrottle):
    # Distinct scope so this limit doesn't share AnonRateThrottle's "anon" cache
    # key with the login/register throttles — without it all three count against
    # the same per-IP bucket and interfere with each other's limits.
    scope = "token_refresh"
    rate = "30/min"


def _record_activity(user_id):
    """Stamp last_login at most once a day per user.

    The API never goes through django.contrib.auth.login(), so nothing else
    sets last_login, and the 7-year de-identification job reads it to tell a
    customer who still signs in from a closed account.
    """
    now = timezone.now()
    CustomUser.objects.filter(pk=user_id).filter(
        Q(last_login__isnull=True) | Q(last_login__lt=now - timedelta(days=1))
    ).update(last_login=now)


class CookieTokenRefreshView(generics.GenericAPIView):
    """Refresh JWT tokens using the HttpOnly refresh cookie."""

    permission_classes = (AllowAny,)
    # No authentication: a stale access cookie must not 401 the endpoint the
    # client uses to recover from it (the refresh cookie is checked below).
    authentication_classes = ()
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
                        logger.debug("Token blacklist not available — skipping")
                refresh = RefreshToken.for_user(self._get_user_from_token(refresh))
                new_access = refresh.access_token

            _record_activity(refresh["user_id"])
            response = Response({"detail": "Token refreshed."})
            _set_jwt_cookies(response, new_access, refresh)
            return response
        except TokenError:
            response = Response(
                {"detail": "Token is invalid or expired."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            _clear_jwt_cookies(response)
            return response
        except Exception:
            logger.exception("Unexpected error during token refresh")
            response = Response(
                {"detail": "Token refresh failed."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
            _clear_jwt_cookies(response)
            return response

    def _get_user_from_token(self, token):
        try:
            return CustomUser.objects.get(pk=token["user_id"])
        except CustomUser.DoesNotExist as exc:
            # Deleted-user race: token is cryptographically valid but its
            # subject no longer exists. Treat as invalid token (401) rather
            # than letting the outer handler return 500.
            raise TokenError("user no longer exists") from exc


class LoginRateThrottle(AnonRateThrottle):
    # Distinct scope (see RefreshRateThrottle) — login, register and refresh must
    # each own their per-IP bucket rather than sharing AnonRateThrottle's "anon".
    scope = "login"
    rate = "5/min"


class RegisterRateThrottle(AnonRateThrottle):
    scope = "register"
    rate = "3/min"


class RegisterView(generics.CreateAPIView):
    queryset = CustomUser.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = (AllowAny,)
    authentication_classes = ()  # a stale access cookie must not 401 registration
    throttle_classes = (RegisterRateThrottle,)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)

        _audit_user_event(request, user, "register", {"username": user.username})

        response = Response(
            {
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )
        _set_jwt_cookies(response, refresh.access_token, refresh)
        # Ensure CSRF cookie is set for subsequent mutating requests
        get_csrf_token(request)
        return response


class LoginView(generics.GenericAPIView):
    serializer_class = LoginSerializer
    permission_classes = (AllowAny,)
    authentication_classes = ()  # a stale access cookie must not 401 login
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
            # Resolve the acting user the SAME way LoginSerializer does (it
            # accepts an email in this field). Resolving only by username here
            # would let an attacker bypass the lockout + failed-attempt audit
            # entirely by submitting the email instead of the username.
            if "@" in username:
                user_obj = CustomUser.objects.filter(email=username).first()
            else:
                user_obj = CustomUser.objects.filter(username=username).first()
            if user_obj is None:
                # Perform a dummy password check to equalise timing
                check_password(request.data.get("password", ""), self._DUMMY_HASH)

        if user_obj and user_obj.is_locked:
            _audit_user_event(request, user_obj, "login_blocked_locked", {"reason": "account_locked"})
            return Response(generic_error, status=status.HTTP_400_BAD_REQUEST)

        if not serializer.is_valid():
            # Record failed login attempt
            if user_obj:
                user_obj.record_failed_login()
                _audit_user_event(
                    request, user_obj, "login_failed", {"failed_attempts": user_obj.failed_login_attempts}
                )
            return Response(generic_error, status=status.HTTP_400_BAD_REQUEST)

        user = serializer.validated_data["user"]
        user.reset_failed_logins()

        _record_activity(user.pk)
        refresh = RefreshToken.for_user(user)
        _audit_user_event(request, user, "login_success")

        response = Response({"user": UserSerializer(user).data})
        _set_jwt_cookies(response, refresh.access_token, refresh)
        rotate_token(request)
        get_csrf_token(request)
        return response


class UserProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = (IsAuthenticated,)

    def get_object(self):
        return self.request.user


class CustomerProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = CustomerProfileSerializer
    permission_classes = (IsAuthenticated,)

    def get_object(self):
        profile, _ = CustomerProfile.objects.get_or_create(user=self.request.user)
        return profile


class StaffCustomerListView(generics.ListAPIView):
    """List all customers for admin/officer staff."""

    serializer_class = UserSerializer
    permission_classes = (IsAdminOrOfficer,)

    def get_queryset(self):
        qs = CustomUser.objects.filter(role=CustomUser.Role.CUSTOMER).select_related("profile").order_by("-created_at")
        search = self.request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(email__icontains=search)
                | Q(username__icontains=search)
            )
        return qs


class StaffCustomerProfileView(generics.RetrieveUpdateAPIView):
    """Endpoint for admin/officer to view any customer's profile. Admins can also update."""

    permission_classes = (IsAdminOrOfficer,)
    lookup_field = "user_id"
    lookup_url_kwarg = "user_id"

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return AdminCustomerProfileUpdateSerializer
        return StaffCustomerDetailSerializer

    def get_object(self):
        user_id = self.kwargs["user_id"]
        # Gate the profile fetch on role=customer BEFORE the get_or_create so we
        # never auto-attach a CustomerProfile row to a staff account (a PII
        # trust-boundary leak).
        user = get_object_or_404(CustomUser, pk=user_id, role=CustomUser.Role.CUSTOMER)
        profile, _ = CustomerProfile.objects.select_related("user").get_or_create(user=user)
        return profile

    def check_permissions(self, request):
        super().check_permissions(request)
        if request.method in ("PUT", "PATCH") and request.user.role != "admin" and not request.user.is_superuser:
            self.permission_denied(request, message="Only admins can update customer profiles.")

    def perform_update(self, serializer):
        profile = serializer.save()
        AuditLog.objects.create(
            user=self.request.user,
            action="admin_update_customer_profile",
            resource_type="CustomerProfile",
            resource_id=str(profile.id),
            details={
                "customer_user_id": profile.user_id,
                "customer_username": profile.user.username,
                "updated_fields": list(serializer.validated_data.keys()),
            },
            ip_address=client_ip(self.request),
        )


class StaffCustomerActivityView(generics.GenericAPIView):
    """Return emails and agent runs for a specific customer's applications."""

    permission_classes = (IsAdminOrOfficer,)

    def get(self, request, user_id):
        try:
            customer = CustomUser.objects.get(pk=user_id, role=CustomUser.Role.CUSTOMER)
        except CustomUser.DoesNotExist:
            return Response(
                {"error": "Customer not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(customer_activity(customer))


class DataExportThrottle(UserRateThrottle):
    """Low cap on data exports — heavy endpoint + Privacy Act APP-12 is low-frequency."""

    scope = "data_export"
    rate = "10/hour"


class CustomerDataExportView(generics.GenericAPIView):
    """Export all customer data (APP 12 — Australian Privacy Act 1988)."""

    permission_classes = (IsAuthenticated,)
    throttle_classes = (DataExportThrottle,)

    # Prevent unbounded memory load for high-volume applicants. Real users will
    # never exceed these caps; attackers who synthesise many records would OOM
    # the worker without them.
    MAX_APPLICATIONS = 500
    MAX_EMAILS_PER_APP = 50
    MAX_AGENT_RUNS_PER_APP = 20

    def get(self, request):
        user = request.user
        data = {
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "role": user.role,
                "created_at": user.created_at.isoformat(),
            },
        }

        # Profile data
        try:
            profile = user.profile
            data["profile"] = {
                f.name: str(getattr(profile, f.name, ""))
                for f in profile._meta.get_fields()
                if hasattr(f, "column") and f.name not in ("id", "user")
            }
        except CustomerProfile.DoesNotExist:
            data["profile"] = None

        # Loan applications with related decisions, emails, agent runs, bias reports
        applications = (
            LoanApplication.objects.filter(applicant=user)
            .select_related("decision", "decision__model_version")
            .prefetch_related(
                # Use Prefetch with bounded sub-querysets so Django's prefetch
                # cache is hit inside the loop (list(qs)[:n] bypasses the cache
                # and causes N+1 queries per application).
                Prefetch(
                    "emails",
                    queryset=GeneratedEmail.objects.order_by("-created_at")[: self.MAX_EMAILS_PER_APP],
                    to_attr="_emails_cached",
                ),
                Prefetch(
                    "agent_runs",
                    queryset=AgentRun.objects.prefetch_related("bias_reports").order_by("-created_at")[
                        : self.MAX_AGENT_RUNS_PER_APP
                    ],
                    to_attr="_agent_runs_cached",
                ),
                Prefetch(
                    "marketing_emails",
                    queryset=MarketingEmail.objects.order_by("-created_at")[: self.MAX_EMAILS_PER_APP],
                    to_attr="_marketing_emails_cached",
                ),
            )
            .order_by("-created_at")[: self.MAX_APPLICATIONS]
        )

        apps_data = []
        for app in applications:
            app_dict = {
                "id": str(app.id),
                "loan_amount": str(app.loan_amount),
                "purpose": app.purpose,
                "status": app.status,
                "created_at": app.created_at.isoformat(),
            }

            # Loan decision with ML explanation
            try:
                d = app.decision
                app_dict["decision"] = {
                    "decision": d.decision,
                    "confidence": d.confidence,
                    "risk_grade": d.risk_grade,
                    "feature_importances": d.feature_importances,
                    "shap_values": d.shap_values,
                    "reasoning": d.reasoning,
                    "model_version": str(d.model_version) if d.model_version else None,
                    "created_at": d.created_at.isoformat(),
                }
            except LoanDecision.DoesNotExist:
                app_dict["decision"] = None

            app_dict["emails"] = [
                {
                    "subject": e.subject,
                    "body": e.body,
                    "decision": e.decision,
                    "created_at": e.created_at.isoformat(),
                }
                for e in getattr(app, "_emails_cached", [])
            ]

            app_dict["marketing_emails"] = [
                {
                    "subject": me.subject,
                    "body": me.body,
                    "sent": me.sent,
                    "sent_at": me.sent_at.isoformat() if me.sent_at else None,
                    "created_at": me.created_at.isoformat(),
                }
                for me in getattr(app, "_marketing_emails_cached", [])
            ]

            app_dict["agent_runs"] = [
                {
                    "status": run.status,
                    "steps": run.steps,
                    "created_at": run.created_at.isoformat(),
                    "bias_reports": [
                        {
                            "bias_score": br.bias_score,
                            "categories": br.categories,
                            "analysis": br.analysis,
                            "flagged": br.flagged,
                            "created_at": br.created_at.isoformat(),
                        }
                        for br in run.bias_reports.all()
                    ],
                }
                for run in getattr(app, "_agent_runs_cached", [])
            ]

            apps_data.append(app_dict)

        data["loan_applications"] = apps_data

        # Audit log entries
        audit_logs = (
            AuditLog.objects.filter(user=user)
            .order_by("-timestamp")[:100]
            .values(
                "action",
                "resource_type",
                "timestamp",
            )
        )
        data["audit_logs"] = [{k: str(v) for k, v in log.items()} for log in audit_logs]

        _audit_user_event(request, user, "data_export")

        return Response(data)


class LogoutView(generics.GenericAPIView):
    """Blacklist the refresh token and clear auth cookies.

    Authenticated by the refresh token, not the access cookie: a stale or
    invalid access cookie (JS cannot clear the HttpOnly cookie) must not
    stop a user logging out. A browser request carrying the refresh cookie
    still has to pass the CSRF check.
    """

    permission_classes = (AllowAny,)
    authentication_classes = ()

    def post(self, request, *args, **kwargs):
        # Try cookie first, then request body (backwards compat)
        refresh_name = getattr(django_settings, "JWT_REFRESH_COOKIE_NAME", "refresh_token")
        from_cookie = request.COOKIES.get(refresh_name)
        refresh = from_cookie or request.data.get("refresh")
        if not refresh:
            response = Response(
                {"detail": "refresh token is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
            _clear_jwt_cookies(response)
            return response
        if from_cookie:
            CookieJWTAuthentication()._enforce_csrf(request)

        user = None
        try:
            token = RefreshToken(refresh)
            user = CustomUser.objects.filter(pk=token.payload.get("user_id")).first()
            token.blacklist()
        except TokenError as exc:
            logger.debug("logout_token_already_invalid", extra={"error": type(exc).__name__})

        if user is not None:
            _audit_user_event(request, user, "logout")

        response = Response({"detail": "Successfully logged out."}, status=status.HTTP_200_OK)
        _clear_jwt_cookies(response)
        return response
