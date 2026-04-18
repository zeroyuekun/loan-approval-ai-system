import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.common.models import SoftDeleteModel


class AuditLog(models.Model):
    """Immutable audit trail for all significant actions in the system."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=50, db_index=True)
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=255)
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        # Append-only: remove delete permissions
        default_permissions = ("add", "view")
        indexes = [
            models.Index(fields=["user", "-timestamp"], name="auditlog_user_timestamp"),
        ]

    def __str__(self):
        return f"[{self.timestamp}] {self.action} on {self.resource_type}({self.resource_id})"


class LoanApplication(SoftDeleteModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        APPROVED = "approved", "Approved"
        DENIED = "denied", "Denied"
        REVIEW = "review", "Under Review"
        QUEUE_FAILED = "queue_failed", "Queue Dispatch Failed"

    class Purpose(models.TextChoices):
        HOME = "home", "Home Purchase"
        AUTO = "auto", "Auto Loan"
        EDUCATION = "education", "Education"
        PERSONAL = "personal", "Personal"
        BUSINESS = "business", "Business"

    class EmploymentType(models.TextChoices):
        PAYG_PERMANENT = "payg_permanent", "PAYG Permanent"
        PAYG_CASUAL = "payg_casual", "PAYG Casual"
        SELF_EMPLOYED = "self_employed", "Self-Employed"
        CONTRACT = "contract", "Contract"

    class ApplicantType(models.TextChoices):
        SINGLE = "single", "Single"
        COUPLE = "couple", "Couple"

    class HomeOwnership(models.TextChoices):
        OWN = "own", "Own"
        RENT = "rent", "Rent"
        MORTGAGE = "mortgage", "Mortgage"

    class AustralianState(models.TextChoices):
        NSW = "NSW", "New South Wales"
        VIC = "VIC", "Victoria"
        QLD = "QLD", "Queensland"
        WA = "WA", "Western Australia"
        SA = "SA", "South Australia"
        TAS = "TAS", "Tasmania"
        ACT = "ACT", "Australian Capital Territory"
        NT = "NT", "Northern Territory"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    applicant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="loan_applications")

    # Financial info
    annual_income = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(10_000_000)]
    )
    credit_score = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(1200)], db_index=True)
    loan_amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(5_000_000)], db_index=True
    )
    loan_term_months = models.IntegerField(default=36, validators=[MinValueValidator(1), MaxValueValidator(600)])
    debt_to_income = models.DecimalField(max_digits=6, decimal_places=2, help_text="DTI ratio (e.g. 4.5 = 4.5x income)")
    employment_length = models.IntegerField(help_text="Years of employment", validators=[MinValueValidator(0)])

    # Australian lending fields
    property_value = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, help_text="Property value for LVR calculation"
    )
    deposit_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, help_text="Deposit/genuine savings amount"
    )
    monthly_expenses = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Self-declared monthly living expenses"
    )
    existing_credit_card_limit = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, help_text="Total credit card limit (banks assess 3% of limit)"
    )
    number_of_dependants = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(10)])
    employment_type = models.CharField(
        max_length=20,
        choices=EmploymentType.choices,
        default=EmploymentType.PAYG_PERMANENT,
    )
    applicant_type = models.CharField(
        max_length=10,
        choices=ApplicantType.choices,
        default=ApplicantType.SINGLE,
    )

    # NCCP consumer requirements/objectives
    consumer_objectives = models.TextField(
        blank=True,
        help_text="Consumer's stated objectives for this loan (NCCP Act s.12A)",
    )
    consumer_requirements = models.TextField(
        blank=True,
        help_text="Consumer's stated requirements and how this loan meets them",
    )
    financial_situation_notes = models.TextField(
        blank=True,
        help_text="Summary of inquiries into consumer's financial situation",
    )

    # Categorical
    purpose = models.CharField(max_length=20, choices=Purpose.choices, db_index=True)
    home_ownership = models.CharField(
        max_length=20,
        choices=HomeOwnership.choices,
    )
    has_cosigner = models.BooleanField(default=False)

    # Location
    state = models.CharField(
        max_length=3,
        choices=AustralianState.choices,
        default=AustralianState.NSW,
        help_text="Australian state/territory of the applicant",
    )

    # Bureau features (Equifax/Illion credit report data)
    num_credit_enquiries_6m = models.IntegerField(null=True, blank=True, help_text="Credit enquiries in last 6 months")
    worst_arrears_months = models.IntegerField(
        null=True, blank=True, help_text="Worst arrears in last 24 months (0-3+)"
    )
    num_defaults_5yr = models.IntegerField(null=True, blank=True, help_text="Defaults on credit file in last 5 years")
    credit_history_months = models.IntegerField(null=True, blank=True, help_text="Length of credit history in months")
    total_open_accounts = models.IntegerField(null=True, blank=True, help_text="Total open credit accounts")
    num_bnpl_accounts = models.IntegerField(null=True, blank=True, help_text="Buy-now-pay-later accounts")

    # Behavioural features (existing customer internal data)
    is_existing_customer = models.BooleanField(default=False, help_text="Existing bank customer")
    savings_balance = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, help_text="Average savings balance"
    )
    salary_credit_regularity = models.FloatField(null=True, blank=True, help_text="Salary credit regularity score 0-1")
    num_dishonours_12m = models.IntegerField(null=True, blank=True, help_text="Bounced payments in last 12 months")
    avg_monthly_savings_rate = models.FloatField(null=True, blank=True, help_text="Average monthly savings rate")
    days_in_overdraft_12m = models.IntegerField(null=True, blank=True, help_text="Days in overdraft in last 12 months")

    # Macroeconomic context at time of application
    rba_cash_rate = models.FloatField(null=True, blank=True, help_text="RBA cash rate at application date")
    unemployment_rate = models.FloatField(
        null=True, blank=True, help_text="State unemployment rate at application date"
    )
    property_growth_12m = models.FloatField(null=True, blank=True, help_text="12-month property growth for state")
    consumer_confidence = models.FloatField(null=True, blank=True, help_text="Westpac-MI Consumer Confidence Index")

    # Open Banking / Transaction Features (Plaid/Basiq-inspired)
    savings_trend_3m = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        choices=[("positive", "Positive"), ("negative", "Negative"), ("flat", "Flat")],
        help_text="3-month savings trend",
    )
    discretionary_spend_ratio = models.FloatField(
        null=True, blank=True, help_text="Ratio of discretionary to essential spending"
    )
    gambling_transaction_flag = models.BooleanField(default=False, help_text="Gambling transactions detected")
    bnpl_active_count = models.IntegerField(default=0, help_text="Number of active BNPL accounts")
    overdraft_frequency_90d = models.IntegerField(default=0, help_text="Overdraft events in last 90 days")
    income_verification_score = models.FloatField(
        null=True, blank=True, help_text="0.0-1.0: declared vs observed income consistency"
    )

    # CCR (Comprehensive Credit Reporting) — mandatory since 2018
    num_late_payments_24m = models.IntegerField(
        null=True, blank=True, default=0, help_text="Late (14+ days) payments in 24-month CCR window"
    )
    worst_late_payment_days = models.IntegerField(
        null=True, blank=True, default=0, help_text="Worst arrears: 0, 14, 30, 60, 90+ days"
    )
    total_credit_limit = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, help_text="Sum of all credit limits from CCR"
    )
    credit_utilization_pct = models.FloatField(null=True, blank=True, help_text="Total balance / total credit limit")
    num_hardship_flags = models.IntegerField(
        null=True, blank=True, default=0, help_text="Financial Hardship Information flags (CCR since 2022)"
    )
    months_since_last_default = models.IntegerField(null=True, blank=True, help_text="Months since most recent default")
    num_credit_providers = models.IntegerField(
        null=True, blank=True, default=1, help_text="Count of distinct credit providers"
    )
    # BNPL-specific (NCCP Act since June 2025)
    bnpl_total_limit = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, default=0, help_text="Total BNPL credit limit"
    )
    bnpl_utilization_pct = models.FloatField(null=True, blank=True, default=0, help_text="BNPL balance / BNPL limit")
    bnpl_late_payments_12m = models.IntegerField(
        null=True, blank=True, default=0, help_text="Late BNPL payments in 12 months"
    )
    bnpl_monthly_commitment = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True, default=0, help_text="Average monthly BNPL repayment"
    )
    # CDR/Open Banking transaction features (Consumer Data Right)
    income_source_count = models.IntegerField(
        null=True, blank=True, default=1, help_text="Count of distinct income sources"
    )
    rent_payment_regularity = models.FloatField(
        null=True, blank=True, help_text="0-1: on-time rent payment consistency"
    )
    utility_payment_regularity = models.FloatField(
        null=True, blank=True, help_text="0-1: on-time utility payment consistency"
    )
    essential_to_total_spend = models.FloatField(null=True, blank=True, help_text="Essential spending / total spending")
    subscription_burden = models.FloatField(
        null=True, blank=True, help_text="Total recurring subscriptions / monthly income"
    )
    balance_before_payday = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Average balance 3 days before salary"
    )
    min_balance_30d = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Lowest account balance in last 30 days"
    )
    days_negative_balance_90d = models.IntegerField(
        null=True, blank=True, default=0, help_text="Days with negative balance in 90 days"
    )
    # Geographic risk
    postcode_default_rate = models.FloatField(
        null=True, blank=True, help_text="Historical default rate for postcode area"
    )
    industry_risk_tier = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        choices=[("low", "Low"), ("medium", "Medium"), ("high", "High"), ("very_high", "Very High")],
    )

    # Application integrity signals
    income_verification_gap = models.FloatField(null=True, blank=True, help_text="Declared vs verified income ratio")
    document_consistency_score = models.FloatField(null=True, blank=True, help_text="Document consistency 0-1")

    # Compliance
    has_hecs = models.BooleanField(default=False, help_text="Has HECS/HELP debt (ATO compulsory repayment)")
    has_bankruptcy = models.BooleanField(default=False, help_text="Undischarged bankrupt or within 7 years")

    # Outcome tracking (backtesting validation)
    actual_outcome = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        choices=[
            ("performing", "Performing"),
            ("arrears_30", "30-Day Arrears"),
            ("arrears_60", "60-Day Arrears"),
            ("arrears_90", "90+ Day Arrears"),
            ("default", "Default"),
            ("prepaid", "Prepaid Early"),
        ],
    )
    outcome_date = models.DateField(null=True, blank=True)
    months_to_outcome = models.IntegerField(null=True, blank=True)

    # Status
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    notes = models.TextField(blank=True)

    # Referral audit trail (D6) — populated when credit-policy overlay's
    # refer rules (P08–P12) fire. Intentionally orthogonal to the
    # customer-facing bias review queue (which stays bias-only per the
    # established product preference); admins read these via the
    # `/api/loans/referrals/` endpoint.
    class ReferralStatus(models.TextChoices):
        NONE = "none", "Not referred"
        REFERRED = "referred", "Referred to underwriter"
        CLEARED = "cleared", "Cleared by underwriter"
        ESCALATED = "escalated", "Escalated (further review)"

    referral_status = models.CharField(
        max_length=20,
        choices=ReferralStatus.choices,
        default=ReferralStatus.NONE,
        db_index=True,
        help_text="Referral state from credit-policy overlay (P08–P12); admin-only workflow.",
    )
    referral_codes = models.JSONField(
        default=list,
        blank=True,
        help_text="Policy codes (e.g. ['P09', 'P11']) that triggered referral.",
    )
    referral_rationale = models.JSONField(
        default=dict,
        blank=True,
        help_text="Code → human-readable reason map, captured at decision time for audit.",
    )

    # Legacy fields — kept for migration compatibility
    conditions = models.JSONField(
        default=list,
        blank=True,
    )
    conditions_met = models.BooleanField(
        default=False,
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["applicant", "-created_at"], name="loan_applicant_created"),
        ]

    # Valid state transitions — any transition not listed here is illegal
    ALLOWED_TRANSITIONS: dict[str, list[str]] = {
        "pending": ["processing", "denied"],
        "processing": ["approved", "denied", "review", "pending"],  # pending = prediction failure rollback
        "review": ["approved", "denied", "processing", "pending"],  # pending = regenerate, processing = retry
        "approved": ["processing"],  # allow pipeline re-run
        "denied": ["processing"],  # allow pipeline re-run
    }

    class InvalidStateTransition(Exception):
        """Raised when an illegal status transition is attempted."""

    def transition_to(self, new_status: str, *, user=None, details: dict | None = None) -> None:
        """Transition to a new status with validation and audit logging.

        Raises InvalidStateTransition if the transition is not allowed.
        Creates an AuditLog entry for every successful transition.
        """
        old_status = self.status
        allowed = self.ALLOWED_TRANSITIONS.get(old_status, [])
        if new_status not in allowed:
            raise self.InvalidStateTransition(
                f"Cannot transition from '{old_status}' to '{new_status}'. Allowed transitions: {allowed}"
            )
        self.status = new_status
        self.save(update_fields=["status", "updated_at"])

        AuditLog.objects.create(
            user=user,
            action="status_transition",
            resource_type="LoanApplication",
            resource_id=str(self.id),
            details={
                "from_status": old_status,
                "to_status": new_status,
                **(details or {}),
            },
        )

    def __str__(self):
        return f"Loan {self.id} - {self.applicant.username} - ${self.loan_amount}"


class LoanDecision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.OneToOneField(LoanApplication, on_delete=models.CASCADE, related_name="decision")
    decision = models.CharField(max_length=20, choices=[("approved", "Approved"), ("denied", "Denied")])
    confidence = models.FloatField()
    risk_score = models.FloatField(null=True, blank=True)
    risk_grade = models.CharField(
        max_length=5,
        blank=True,
        default="",
        choices=[
            ("AAA", "AAA"),
            ("AA", "AA"),
            ("A", "A"),
            ("BBB", "BBB"),
            ("BB", "BB"),
            ("B", "B"),
            ("CCC", "CCC"),
        ],
        help_text="APS 220 internal risk grade",
    )
    feature_importances = models.JSONField(default=dict)
    shap_values = models.JSONField(default=dict, blank=True)
    counterfactual_results = models.JSONField(
        default=list,
        blank=True,
        help_text="DiCE counterfactual explanations for denied applications",
    )
    decision_waterfall = models.JSONField(
        default=list,
        blank=True,
        help_text="Ordered list of decision gate results for ASIC RG 209 audit trail",
    )
    model_version = models.ForeignKey(
        "ml_engine.ModelVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decisions",
        help_text="ML model version that produced this decision",
    )
    reasoning = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Decision for {self.application_id}: {self.decision} ({self.confidence:.1%})"


class FraudCheck(models.Model):
    """Stores the results of fraud detection / velocity checks for an application."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(LoanApplication, on_delete=models.CASCADE, related_name="fraud_checks")
    passed = models.BooleanField(help_text="True if no high-risk check failed")
    risk_score = models.FloatField(help_text="Composite risk score 0-1")
    checks = models.JSONField(default=list, help_text="List of individual check results")
    flagged_reasons = models.JSONField(default=list, help_text="Human-readable reasons for failed checks")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"FraudCheck for {self.application_id}: passed={self.passed} risk={self.risk_score:.2f}"


class Complaint(models.Model):
    """Customer complaint tracking per ASIC RG 271 and NCCP Act s.12CM."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        INVESTIGATING = "investigating", "Investigating"
        RESOLVED = "resolved", "Resolved"
        ESCALATED_AFCA = "escalated_afca", "Escalated to AFCA"

    class Category(models.TextChoices):
        DECISION = "decision", "Loan Decision"
        SERVICE = "service", "Service Quality"
        PRIVACY = "privacy", "Privacy Concern"
        DISCRIMINATION = "discrimination", "Discrimination"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complainant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="complaints",
    )
    loan_application = models.ForeignKey(
        "LoanApplication",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="complaints",
    )
    category = models.CharField(max_length=20, choices=Category.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    subject = models.CharField(max_length=200)
    description = models.TextField()
    resolution = models.TextField(blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    sla_deadline = models.DateTimeField(
        null=True,
        blank=True,
        help_text="ASIC RG 271: 21 days for credit complaints, 30 days for standard",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["complainant", "status"], name="complaint_user_status"),
        ]

    def __str__(self):
        return f"Complaint {self.id} - {self.get_status_display()}"


class PipelineDispatchOutbox(models.Model):
    """Outbox row for loan applications whose Celery dispatch failed.

    A beat task drains this table on a 60s cadence. Rows that reach
    MAX_DISPATCH_ATTEMPTS remain for operator visibility — they are NOT
    retried further by the automated loop.
    """

    MAX_DISPATCH_ATTEMPTS = 5

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.OneToOneField(
        LoanApplication,
        on_delete=models.CASCADE,
        related_name="dispatch_outbox",
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Pipeline Dispatch Outbox Entry"
        verbose_name_plural = "Pipeline Dispatch Outbox"
        ordering = ["created_at"]

    def __str__(self):
        return f"outbox<{self.application_id}> attempts={self.attempts}"
