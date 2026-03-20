from rest_framework.exceptions import NotFound, PermissionDenied
from apps.loans.models import LoanApplication


def check_loan_access(request, loan_id):
    """Verify user has access to the loan application. Returns the application.

    Shared across agents, email_engine, and ml_engine views.
    """
    try:
        application = LoanApplication.objects.select_related('applicant').get(pk=loan_id)
    except LoanApplication.DoesNotExist:
        raise NotFound('Loan application not found.')

    user = request.user
    if user.role in ('admin', 'officer'):
        return application

    if application.applicant_id != user.id:
        raise PermissionDenied('You do not have access to this application.')

    return application
