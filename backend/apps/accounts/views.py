import logging

from django.contrib.auth.hashers import check_password, make_password
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

from apps.loans.models import AuditLog

from apps.agents.models import AgentRun
from apps.email_engine.models import GeneratedEmail

from .models import CustomerProfile, CustomUser
from .permissions import IsAdminOrOfficer
from .serializers import AdminCustomerProfileUpdateSerializer, CustomerProfileSerializer, LoginSerializer, RegisterSerializer, StaffCustomerDetailSerializer, UserSerializer

logger = logging.getLogger(__name__)


class LoginRateThrottle(AnonRateThrottle):
    rate = '5/min'


class RegisterRateThrottle(AnonRateThrottle):
    rate = '3/min'


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
            action='register',
            resource_type='CustomUser',
            resource_id=str(user.id),
            details={'username': user.username},
            ip_address=request.META.get('REMOTE_ADDR'),
        )

        return Response({
            'user': UserSerializer(user).data,
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }
        }, status=status.HTTP_201_CREATED)


class LoginView(generics.GenericAPIView):
    serializer_class = LoginSerializer
    permission_classes = (AllowAny,)
    throttle_classes = (LoginRateThrottle,)

    # Dummy password used to burn CPU time when the username doesn't exist,
    # so that the response timing is indistinguishable from a real lookup.
    _DUMMY_HASH = make_password('dummy-timing-equalizer')

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        generic_error = {'detail': 'Invalid username or password.'}

        # Check if account is locked before attempting authentication
        username = request.data.get('username', '')
        user_obj = None
        if username:
            try:
                user_obj = CustomUser.objects.get(username=username)
            except CustomUser.DoesNotExist:
                # Perform a dummy password check to equalise timing
                check_password(request.data.get('password', ''), self._DUMMY_HASH)

        if user_obj and user_obj.is_locked:
            AuditLog.objects.create(
                user=user_obj,
                action='login_blocked_locked',
                resource_type='CustomUser',
                resource_id=str(user_obj.id),
                details={'reason': 'account_locked'},
                ip_address=request.META.get('REMOTE_ADDR'),
            )
            return Response(generic_error, status=status.HTTP_400_BAD_REQUEST)

        if not serializer.is_valid():
            # Record failed login attempt
            if user_obj:
                user_obj.record_failed_login()
                AuditLog.objects.create(
                    user=user_obj,
                    action='login_failed',
                    resource_type='CustomUser',
                    resource_id=str(user_obj.id),
                    details={'failed_attempts': user_obj.failed_login_attempts},
                    ip_address=request.META.get('REMOTE_ADDR'),
                )
            return Response(generic_error, status=status.HTTP_400_BAD_REQUEST)

        user = serializer.validated_data['user']
        user.reset_failed_logins()

        refresh = RefreshToken.for_user(user)

        AuditLog.objects.create(
            user=user,
            action='login_success',
            resource_type='CustomUser',
            resource_id=str(user.id),
            details={},
            ip_address=request.META.get('REMOTE_ADDR'),
        )

        return Response({
            'user': UserSerializer(user).data,
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }
        })


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
        qs = CustomUser.objects.all().order_by('-created_at')
        search = self.request.query_params.get('search', '').strip()
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(email__icontains=search) |
                Q(username__icontains=search)
            )
        return qs


class StaffCustomerProfileView(generics.RetrieveUpdateAPIView):
    """Endpoint for admin/officer to view any customer's profile. Admins can also update."""
    permission_classes = (IsAdminOrOfficer,)
    lookup_field = 'user_id'
    lookup_url_kwarg = 'user_id'

    def get_serializer_class(self):
        if self.request.method in ('PUT', 'PATCH'):
            return AdminCustomerProfileUpdateSerializer
        return StaffCustomerDetailSerializer

    def get_object(self):
        user_id = self.kwargs['user_id']
        get_object_or_404(CustomUser, pk=user_id)
        profile, _ = CustomerProfile.objects.select_related('user').get_or_create(user_id=user_id)
        return profile

    def check_permissions(self, request):
        super().check_permissions(request)
        if request.method in ('PUT', 'PATCH') and request.user.role != 'admin' and not request.user.is_superuser:
            self.permission_denied(request, message='Only admins can update customer profiles.')

    def perform_update(self, serializer):
        profile = serializer.save()
        AuditLog.objects.create(
            user=self.request.user,
            action='admin_update_customer_profile',
            resource_type='CustomerProfile',
            resource_id=str(profile.id),
            details={
                'customer_user_id': profile.user_id,
                'customer_username': profile.user.username,
                'updated_fields': list(serializer.validated_data.keys()),
            },
            ip_address=self.request.META.get('REMOTE_ADDR'),
        )


class StaffCustomerActivityView(generics.GenericAPIView):
    """Return emails and agent runs for a specific customer's applications."""
    permission_classes = (IsAdminOrOfficer,)

    def get(self, request, user_id):
        try:
            customer = CustomUser.objects.get(pk=user_id)
        except CustomUser.DoesNotExist:
            return Response(
                {'error': 'Customer not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        app_ids = list(
            customer.loan_applications.values_list('id', flat=True)
        )

        # Emails (bounded to 50 most recent)
        emails_qs = GeneratedEmail.objects.filter(
            application_id__in=app_ids
        ).prefetch_related('guardrail_checks').order_by('-created_at')[:50]

        emails = []
        for email in emails_qs:
            guardrail_checks = [
                {'check_name': log.check_name, 'passed': log.passed, 'details': log.details}
                for log in email.guardrail_checks.all()
            ]
            emails.append({
                'id': str(email.id),
                'application_id': str(email.application_id),
                'decision': email.decision,
                'subject': email.subject,
                'body': email.body,
                'model_used': email.model_used,
                'generation_time_ms': email.generation_time_ms,
                'attempt_number': email.attempt_number,
                'passed_guardrails': email.passed_guardrails,
                'guardrail_checks': guardrail_checks,
                'created_at': email.created_at.isoformat(),
            })

        # Agent runs (bounded to 50 most recent)
        runs_qs = AgentRun.objects.filter(
            application_id__in=app_ids
        ).prefetch_related(
            'bias_reports', 'next_best_offers', 'marketing_emails'
        ).order_by('-created_at')[:50]

        agent_runs = []
        for run in runs_qs:
            bias_reports = [
                {
                    'id': str(br.id),
                    'bias_score': br.bias_score,
                    'categories': br.categories,
                    'analysis': br.analysis,
                    'flagged': br.flagged,
                    'requires_human_review': br.requires_human_review,
                    'ai_review_approved': br.ai_review_approved,
                    'ai_review_reasoning': br.ai_review_reasoning,
                    'created_at': br.created_at.isoformat(),
                }
                for br in run.bias_reports.all()
            ]
            next_best_offers = [
                {
                    'id': str(nbo.id),
                    'offers': nbo.offers,
                    'analysis': nbo.analysis,
                    'customer_retention_score': nbo.customer_retention_score,
                    'loyalty_factors': nbo.loyalty_factors,
                    'personalized_message': nbo.personalized_message,
                    'marketing_message': nbo.marketing_message,
                    'created_at': nbo.created_at.isoformat(),
                }
                for nbo in run.next_best_offers.all()
            ]
            marketing_emails = [
                {
                    'id': str(me.id),
                    'subject': me.subject,
                    'body': me.body,
                    'passed_guardrails': me.passed_guardrails,
                    'guardrail_results': me.guardrail_results,
                    'generation_time_ms': me.generation_time_ms,
                    'attempt_number': me.attempt_number,
                    'created_at': me.created_at.isoformat(),
                }
                for me in run.marketing_emails.all()
            ]
            agent_runs.append({
                'id': str(run.id),
                'application_id': str(run.application_id),
                'status': run.status,
                'steps': run.steps,
                'total_time_ms': run.total_time_ms,
                'error': run.error,
                'bias_reports': bias_reports,
                'next_best_offers': next_best_offers,
                'marketing_emails': marketing_emails,
                'created_at': run.created_at.isoformat(),
                'updated_at': run.updated_at.isoformat(),
            })

        return Response({
            'customer_id': customer.id,
            'customer_name': f'{customer.first_name} {customer.last_name}'.strip() or customer.username,
            'emails': emails,
            'agent_runs': agent_runs,
        })


class LogoutView(generics.GenericAPIView):
    """Blacklist the provided refresh token so it cannot be reused."""
    permission_classes = (IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        refresh = request.data.get('refresh')
        if not refresh:
            return Response(
                {'detail': 'refresh token is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(refresh)
            token.blacklist()
        except Exception:
            return Response(
                {'detail': 'Token is invalid or already blacklisted.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        AuditLog.objects.create(
            user=request.user,
            action='logout',
            resource_type='CustomUser',
            resource_id=str(request.user.id),
            details={},
            ip_address=request.META.get('REMOTE_ADDR'),
        )

        return Response({'detail': 'Successfully logged out.'}, status=status.HTTP_200_OK)
