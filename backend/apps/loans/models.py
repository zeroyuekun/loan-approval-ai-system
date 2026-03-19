from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
import uuid


class AuditLog(models.Model):
    """Immutable audit trail for all significant actions in the system."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
    )
    action = models.CharField(max_length=50, db_index=True)
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=255)
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-timestamp']
        # Append-only: remove delete permissions
        default_permissions = ('add', 'view')

    def __str__(self):
        return f"[{self.timestamp}] {self.action} on {self.resource_type}({self.resource_id})"


class LoanApplication(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'
        APPROVED = 'approved', 'Approved'
        DENIED = 'denied', 'Denied'
        REVIEW = 'review', 'Under Review'

    class Purpose(models.TextChoices):
        HOME = 'home', 'Home Purchase'
        AUTO = 'auto', 'Auto Loan'
        EDUCATION = 'education', 'Education'
        PERSONAL = 'personal', 'Personal'
        BUSINESS = 'business', 'Business'

    class EmploymentType(models.TextChoices):
        PAYG_PERMANENT = 'payg_permanent', 'PAYG Permanent'
        PAYG_CASUAL = 'payg_casual', 'PAYG Casual'
        SELF_EMPLOYED = 'self_employed', 'Self-Employed'
        CONTRACT = 'contract', 'Contract'

    class ApplicantType(models.TextChoices):
        SINGLE = 'single', 'Single'
        COUPLE = 'couple', 'Couple'

    class AustralianState(models.TextChoices):
        NSW = 'NSW', 'New South Wales'
        VIC = 'VIC', 'Victoria'
        QLD = 'QLD', 'Queensland'
        WA = 'WA', 'Western Australia'
        SA = 'SA', 'South Australia'
        TAS = 'TAS', 'Tasmania'
        ACT = 'ACT', 'Australian Capital Territory'
        NT = 'NT', 'Northern Territory'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='loan_applications'
    )

    # Financial info
    annual_income = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(10_000_000)])
    credit_score = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(1200)], db_index=True)
    loan_amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(5_000_000)], db_index=True)
    loan_term_months = models.IntegerField(default=36, validators=[MinValueValidator(1), MaxValueValidator(600)])
    debt_to_income = models.DecimalField(max_digits=6, decimal_places=2, help_text="DTI ratio (e.g. 4.5 = 4.5x income)")
    employment_length = models.IntegerField(help_text="Years of employment", validators=[MinValueValidator(0)])

    # Australian lending fields
    property_value = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Property value for LVR calculation"
    )
    deposit_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Deposit/genuine savings amount"
    )
    monthly_expenses = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Self-declared monthly living expenses"
    )
    existing_credit_card_limit = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Total credit card limit (banks assess 3% of limit)"
    )
    number_of_dependants = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(10)])
    employment_type = models.CharField(
        max_length=20, choices=EmploymentType.choices,
        default=EmploymentType.PAYG_PERMANENT,
    )
    applicant_type = models.CharField(
        max_length=10, choices=ApplicantType.choices,
        default=ApplicantType.SINGLE,
    )

    # Categorical
    purpose = models.CharField(max_length=20, choices=Purpose.choices, db_index=True)
    home_ownership = models.CharField(
        max_length=20,
        choices=[('own', 'Own'), ('rent', 'Rent'), ('mortgage', 'Mortgage')],
    )
    has_cosigner = models.BooleanField(default=False)

    # Location
    state = models.CharField(
        max_length=3, choices=AustralianState.choices,
        default=AustralianState.NSW,
        help_text="Australian state/territory of the applicant",
    )

    # Compliance
    has_hecs = models.BooleanField(default=False, help_text="Has HECS/HELP debt (ATO compulsory repayment)")
    has_bankruptcy = models.BooleanField(default=False, help_text="Undischarged bankrupt or within 7 years")

    # Status
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['applicant', '-created_at'], name='loan_applicant_created'),
        ]

    def __str__(self):
        return f"Loan {self.id} - {self.applicant.username} - ${self.loan_amount}"


class LoanDecision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.OneToOneField(
        LoanApplication, on_delete=models.CASCADE, related_name='decision'
    )
    decision = models.CharField(
        max_length=20, choices=[('approved', 'Approved'), ('denied', 'Denied')]
    )
    confidence = models.FloatField()
    risk_score = models.FloatField(null=True, blank=True)
    feature_importances = models.JSONField(default=dict)
    model_version = models.CharField(max_length=100)
    reasoning = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Decision for {self.application_id}: {self.decision} ({self.confidence:.1%})"
