from rest_framework import viewsets, permissions
from rest_framework.exceptions import PermissionDenied

from apps.accounts.models import CustomerProfile
from apps.accounts.permissions import IsAdmin
from .filters import LoanApplicationFilter
from .models import AuditLog, LoanApplication
from .serializers import LoanApplicationCreateSerializer, LoanApplicationCustomerUpdateSerializer, LoanApplicationSerializer


class IsOwnerOrStaff(permissions.BasePermission):
    """Object-level permission: only the applicant, admins, or officers can modify."""

    def has_object_permission(self, request, view, obj):
        if request.user.role in ('admin', 'officer'):
            return True
        return obj.applicant_id == request.user.id


class LoanApplicationViewSet(viewsets.ModelViewSet):
    filterset_class = LoanApplicationFilter
    ordering_fields = ['created_at', 'loan_amount', 'credit_score', 'status']

    def get_serializer_class(self):
        if self.action == 'create':
            return LoanApplicationCreateSerializer
        if self.action in ('update', 'partial_update') and self.request.user.role == 'customer':
            return LoanApplicationCustomerUpdateSerializer
        return LoanApplicationSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role in ('admin', 'officer'):
            return LoanApplication.objects.all().select_related('applicant', 'decision')
        return LoanApplication.objects.filter(applicant=user).select_related('applicant', 'decision')

    def get_permissions(self):
        if self.action == 'destroy':
            return [permissions.IsAuthenticated(), IsAdmin()]
        if self.action in ('update', 'partial_update'):
            return [permissions.IsAuthenticated(), IsOwnerOrStaff()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        user = self.request.user
        instance = serializer.save(applicant=user)
        # Ensure customer has a profile and seed it from the application
        if user.role == 'customer':
            profile, created = CustomerProfile.objects.get_or_create(user=user)
            if created or profile.num_products <= 1:
                # Seed profile banking fields from the loan application data
                profile.has_mortgage = instance.home_ownership == 'mortgage'
                profile.has_credit_card = (instance.existing_credit_card_limit or 0) > 0
                profile.num_products = max(
                    profile.num_products,
                    1 + int(profile.has_credit_card) + int(profile.has_mortgage),
                )
                profile.save(update_fields=[
                    'has_mortgage', 'has_credit_card', 'num_products',
                ])
        AuditLog.objects.create(
            user=user,
            action='loan_created',
            resource_type='LoanApplication',
            resource_id=str(instance.id),
            details={'loan_amount': str(instance.loan_amount), 'purpose': instance.purpose},
            ip_address=self.request.META.get('REMOTE_ADDR'),
        )

    def perform_update(self, serializer):
        instance = serializer.save()
        AuditLog.objects.create(
            user=self.request.user,
            action='loan_updated',
            resource_type='LoanApplication',
            resource_id=str(instance.id),
            details={'status': instance.status},
            ip_address=self.request.META.get('REMOTE_ADDR'),
        )

    def perform_destroy(self, instance):
        resource_id = str(instance.id)
        AuditLog.objects.create(
            user=self.request.user,
            action='loan_deleted',
            resource_type='LoanApplication',
            resource_id=resource_id,
            details={},
            ip_address=self.request.META.get('REMOTE_ADDR'),
        )
        super().perform_destroy(instance)
