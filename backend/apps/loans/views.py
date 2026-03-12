from rest_framework import viewsets, permissions

from .filters import LoanApplicationFilter
from .models import LoanApplication
from .serializers import LoanApplicationCreateSerializer, LoanApplicationSerializer


class LoanApplicationViewSet(viewsets.ModelViewSet):
    filterset_class = LoanApplicationFilter
    ordering_fields = ['created_at', 'loan_amount', 'credit_score', 'status']

    def get_serializer_class(self):
        if self.action == 'create':
            return LoanApplicationCreateSerializer
        return LoanApplicationSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role in ('admin', 'officer'):
            return LoanApplication.objects.all().select_related('applicant', 'decision')
        return LoanApplication.objects.filter(applicant=user).select_related('applicant', 'decision')

    def get_permissions(self):
        if self.action in ('update', 'partial_update', 'destroy'):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        serializer.save(applicant=self.request.user)
