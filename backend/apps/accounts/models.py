import datetime
import uuid
from decimal import Decimal, InvalidOperation

from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone

from apps.accounts.fields import EncryptedCharField  # noqa: F401 — used by this module and migrations
from apps.accounts.utils.encryption import get_fernet
from apps.common.models import SoftDeleteModel

# Backward-compatible alias — existing tests and commands import _get_fernet from here.
_get_fernet = get_fernet


class CustomUser(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        LOAN_OFFICER = 'officer', 'Loan Officer'
        CUSTOMER = 'customer', 'Customer'

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER)
    phone = models.CharField(max_length=20, blank=True)
    failed_login_attempts = models.IntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    @property
    def is_locked(self):
        if self.locked_until and self.locked_until > timezone.now():
            return True
        return False

    def record_failed_login(self):
        from django.db.models import F
        CustomUser.objects.filter(pk=self.pk).update(
            failed_login_attempts=F('failed_login_attempts') + 1
        )
        self.refresh_from_db()

        if self.failed_login_attempts >= 15:
            lock_minutes = 1440  # 24 hours
        elif self.failed_login_attempts >= 10:
            lock_minutes = 30
        elif self.failed_login_attempts >= 8:
            lock_minutes = 5
        elif self.failed_login_attempts >= 5:
            lock_minutes = 1
        else:
            lock_minutes = 0

        if lock_minutes > 0:
            self.locked_until = timezone.now() + timezone.timedelta(minutes=lock_minutes)
            CustomUser.objects.filter(pk=self.pk).update(locked_until=self.locked_until)

    def reset_failed_logins(self):
        if self.failed_login_attempts > 0 or self.locked_until:
            self.failed_login_attempts = 0
            self.locked_until = None
            self.save(update_fields=['failed_login_attempts', 'locked_until'])


class EmploymentStatus(models.TextChoices):
    PAYG_PERMANENT = 'payg_permanent', 'PAYG – Permanent'
    PAYG_CASUAL = 'payg_casual', 'PAYG – Casual'
    SELF_EMPLOYED = 'self_employed', 'Self-Employed'
    CONTRACT = 'contract', 'Contract'
    RETIRED = 'retired', 'Retired'
    UNEMPLOYED = 'unemployed', 'Unemployed'
    HOME_DUTIES = 'home_duties', 'Home Duties'


class HousingSituation(models.TextChoices):
    OWN_OUTRIGHT = 'own_outright', 'Own Outright'
    MORTGAGE = 'mortgage', 'Mortgage'
    RENTING = 'renting', 'Renting'
    BOARDING = 'boarding', 'Boarding'
    LIVING_WITH_PARENTS = 'living_with_parents', 'Living with Parents'


class ContactMethod(models.TextChoices):
    EMAIL = 'email', 'Email'
    PHONE = 'phone', 'Phone'
    SMS = 'sms', 'SMS'


class Industry(models.TextChoices):
    AGRICULTURE = 'agriculture', 'Agriculture, Forestry and Fishing'
    MINING = 'mining', 'Mining'
    MANUFACTURING = 'manufacturing', 'Manufacturing'
    UTILITIES = 'utilities', 'Electricity, Gas, Water and Waste Services'
    CONSTRUCTION = 'construction', 'Construction'
    WHOLESALE_TRADE = 'wholesale_trade', 'Wholesale Trade'
    RETAIL_TRADE = 'retail_trade', 'Retail Trade'
    ACCOMMODATION_FOOD = 'accommodation_food', 'Accommodation and Food Services'
    TRANSPORT_POSTAL = 'transport_postal', 'Transport, Postal and Warehousing'
    INFORMATION_MEDIA = 'information_media', 'Information Media and Telecommunications'
    FINANCIAL_INSURANCE = 'financial_insurance', 'Financial and Insurance Services'
    PROPERTY_SERVICES = 'property_services', 'Rental, Hiring and Real Estate Services'
    PROFESSIONAL_SCIENTIFIC = 'professional_scientific', 'Professional, Scientific and Technical Services'
    ADMINISTRATIVE = 'administrative', 'Administrative and Support Services'
    PUBLIC_ADMIN = 'public_admin', 'Public Administration and Safety'
    EDUCATION_TRAINING = 'education_training', 'Education and Training'
    HEALTHCARE_SOCIAL = 'healthcare_social', 'Health Care and Social Assistance'
    ARTS_RECREATION = 'arts_recreation', 'Arts and Recreation Services'
    OTHER_SERVICES = 'other_services', 'Other Services'


class CustomerProfile(SoftDeleteModel):
    """Tracks a customer's personal details, compliance documents, and banking history."""

    # PII ENCRYPTION NOTE: Sensitive PII fields use EncryptedCharField (Fernet
    # AES-128-CBC) for at-rest protection. Encrypted fields include: ID numbers,
    # address, phone, DOB, income figures, and employer name. These fields cannot
    # be used in ORM filter()/order_by() queries — all filtering must happen in
    # Python after retrieval. See properties below for native-type accessors.

    class Tier(models.TextChoices):
        STANDARD = 'standard', 'Standard'
        SILVER = 'silver', 'Silver'
        GOLD = 'gold', 'Gold'
        PLATINUM = 'platinum', 'Platinum'

    class IdType(models.TextChoices):
        DRIVERS_LICENCE = 'drivers_licence', "Driver's Licence"
        PASSPORT = 'passport', 'Australian Passport'
        MEDICARE = 'medicare', 'Medicare Card'
        IMMICARD = 'immicard', 'ImmiCard'

    class ResidencyStatus(models.TextChoices):
        CITIZEN = 'citizen', 'Australian Citizen'
        PERMANENT_RESIDENT = 'permanent_resident', 'Permanent Resident'
        TEMPORARY_VISA = 'temporary_visa', 'Temporary Visa Holder'
        NZ_CITIZEN = 'nz_citizen', 'New Zealand Citizen'

    class MaritalStatus(models.TextChoices):
        SINGLE = 'single', 'Single'
        MARRIED = 'married', 'Married'
        DE_FACTO = 'de_facto', 'De Facto'
        DIVORCED = 'divorced', 'Divorced'
        WIDOWED = 'widowed', 'Widowed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='profile')

    # ── Personal details (NCCP Act 2009 responsible lending) ──
    date_of_birth = EncryptedCharField(max_length=500, blank=True, default='', help_text="ISO-8601 date string, encrypted at rest")
    phone = EncryptedCharField(max_length=500, blank=True, help_text="Australian mobile or landline")
    address_line_1 = EncryptedCharField(max_length=500, blank=True)
    address_line_2 = EncryptedCharField(max_length=500, blank=True)
    suburb = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=3, blank=True, help_text="e.g. NSW, VIC, QLD")
    postcode = models.CharField(max_length=10, blank=True)
    marital_status = models.CharField(max_length=20, choices=MaritalStatus.choices, blank=True)

    # ── Identity verification (AML/CTF Act 2006, 100-point ID check) ──
    residency_status = models.CharField(max_length=20, choices=ResidencyStatus.choices, blank=True)
    primary_id_type = models.CharField(max_length=20, choices=IdType.choices, blank=True)
    primary_id_number = EncryptedCharField(max_length=500, blank=True, help_text="Encrypted at rest via Fernet")
    secondary_id_type = models.CharField(max_length=20, choices=IdType.choices, blank=True)
    secondary_id_number = EncryptedCharField(max_length=500, blank=True, help_text="Encrypted at rest via Fernet")
    tax_file_number_provided = models.BooleanField(default=False, help_text="TFN declaration lodged (not stored)")
    is_politically_exposed = models.BooleanField(default=False, help_text="PEP status under AML/CTF rules")

    # ── Employment ──
    employer_name = EncryptedCharField(max_length=500, blank=True, default='')
    occupation = models.CharField(max_length=100, blank=True, default='')
    industry = models.CharField(max_length=30, choices=Industry.choices, blank=True, default='')
    employment_status = models.CharField(max_length=20, choices=EmploymentStatus.choices, blank=True, default='')
    years_in_current_role = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    previous_employer = models.CharField(max_length=255, blank=True, default='', help_text='Required if less than 2 years in current role')

    # ── Income (encrypted at rest — stored as string representations) ──
    gross_annual_income = EncryptedCharField(max_length=500, blank=True, default='', help_text="Decimal string, encrypted at rest")
    other_income = EncryptedCharField(max_length=500, blank=True, default='0', help_text="Decimal string, encrypted at rest")
    other_income_source = models.CharField(max_length=100, blank=True, default='')
    partner_annual_income = EncryptedCharField(max_length=500, blank=True, default='', help_text="Decimal string, encrypted at rest")

    # ── Assets ──
    estimated_property_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    vehicle_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    savings_other_institutions = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    investment_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    superannuation_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    # ── Liabilities ──
    other_loan_repayments_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    other_credit_card_limits = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rent_or_board_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # ── Living situation ──
    housing_situation = models.CharField(max_length=25, choices=HousingSituation.choices, blank=True, default='')
    time_at_current_address_years = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    number_of_dependants = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(15)])
    previous_suburb = models.CharField(max_length=100, blank=True, default='')
    previous_state = models.CharField(max_length=3, blank=True, default='')
    previous_postcode = models.CharField(max_length=10, blank=True, default='')

    # ── Contact preference ──
    preferred_contact_method = models.CharField(max_length=10, choices=ContactMethod.choices, default='email')

    # ── Banking relationship ──
    savings_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    checking_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    account_tenure_years = models.IntegerField(default=0, help_text="Years as a customer")
    has_credit_card = models.BooleanField(default=False)
    has_mortgage = models.BooleanField(default=False)
    has_auto_loan = models.BooleanField(default=False)
    num_products = models.IntegerField(default=1, help_text="Total banking products held")
    loyalty_tier = models.CharField(max_length=20, choices=Tier.choices, default=Tier.STANDARD)

    # ── Payment history ──
    on_time_payment_pct = models.FloatField(default=100.0, help_text="Percentage of on-time payments")

    # ── Privacy Act / consent tracking ──
    privacy_consent_given = models.BooleanField(default=False, help_text='Customer consented to Privacy Collection Notice')
    privacy_consent_date = models.DateTimeField(null=True, blank=True)
    marketing_consent = models.BooleanField(default=False, help_text='Consent to receive marketing communications')
    data_sharing_consent = models.BooleanField(default=False, help_text='Consent to share data with third parties')

    previous_loans_repaid = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile: {self.user.username} ({self.loyalty_tier})"

    # ── Native-type accessors for encrypted string fields ──
    # These properties convert the encrypted string representations back to
    # their original Python types so that existing service code (KYC, ML,
    # orchestrator, serializers) continues to work without modification.

    @property
    def date_of_birth_date(self) -> datetime.date | None:
        """Return date_of_birth as a datetime.date, or None."""
        val = self.date_of_birth
        if not val:
            return None
        if isinstance(val, datetime.date):
            return val
        try:
            return datetime.date.fromisoformat(val)
        except (ValueError, TypeError):
            return None

    @property
    def gross_annual_income_decimal(self) -> Decimal | None:
        """Return gross_annual_income as Decimal, or None."""
        val = self.gross_annual_income
        if not val or val == '':
            return None
        try:
            return Decimal(val)
        except (InvalidOperation, TypeError):
            return None

    @property
    def other_income_decimal(self) -> Decimal:
        """Return other_income as Decimal (defaults to 0)."""
        val = self.other_income
        if not val or val == '':
            return Decimal('0')
        try:
            return Decimal(val)
        except (InvalidOperation, TypeError):
            return Decimal('0')

    @property
    def partner_annual_income_decimal(self) -> Decimal | None:
        """Return partner_annual_income as Decimal, or None."""
        val = self.partner_annual_income
        if not val or val == '':
            return None
        try:
            return Decimal(val)
        except (InvalidOperation, TypeError):
            return None

    @property
    def total_deposits(self):
        return self.savings_balance + self.checking_balance

    @property
    def total_assets(self):
        return (
            self.estimated_property_value
            + self.vehicle_value
            + self.savings_other_institutions
            + self.investment_value
            + self.superannuation_balance
            + self.savings_balance
            + self.checking_balance
        )

    @property
    def total_monthly_liabilities(self):
        return (
            self.other_loan_repayments_monthly
            + (Decimal('0.03') * self.other_credit_card_limits)
            + self.rent_or_board_monthly
        )

    # Fields the customer must complete before submitting a loan application.
    # Based on NCCP Act 2009 (responsible lending) and AML/CTF Act 2006 (100-point ID check).
    REQUIRED_PROFILE_FIELDS = (
        'date_of_birth', 'phone', 'address_line_1', 'suburb', 'state',
        'postcode', 'residency_status', 'primary_id_type', 'primary_id_number',
        'employment_status', 'gross_annual_income', 'housing_situation',
        'number_of_dependants',
    )

    @property
    def is_profile_complete(self):
        """True when all fields required for a loan application have been filled in."""
        return not self.missing_profile_fields

    @property
    def missing_profile_fields(self):
        """Return a list of required field names that are still empty."""
        missing = []
        for f in self.REQUIRED_PROFILE_FIELDS:
            val = getattr(self, f, None)
            if val is None or val == '':
                missing.append(f)
        return missing

    @property
    def is_loyal_customer(self):
        """True if the customer has enough history/deposits to be worth keeping."""
        return (
            self.account_tenure_years >= 3
            or self.total_deposits >= 10000
            or self.num_products >= 3
            or self.loyalty_tier in ('gold', 'platinum')
            or self.previous_loans_repaid >= 1
        )


class KYCVerification(models.Model):
    """Tracks AML/CTF 100-point ID verification status."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        VERIFIED = 'verified', 'Verified'
        FAILED = 'failed', 'Failed'
        EXPIRED = 'expired', 'Expired'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='kyc_verifications')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    # 100-point check
    total_points = models.IntegerField(default=0, help_text='Total ID verification points (need 100)')
    primary_id_points = models.IntegerField(default=0, help_text='Points from primary ID (e.g. passport=70)')
    secondary_id_points = models.IntegerField(default=0, help_text='Points from secondary ID')
    supplementary_points = models.IntegerField(default=0, help_text='Points from supplementary docs')

    # Sanctions screening
    sanctions_checked = models.BooleanField(default=False)
    sanctions_clear = models.BooleanField(null=True, default=None)
    sanctions_check_date = models.DateTimeField(null=True, blank=True)

    # OCDD (Ongoing Customer Due Diligence)
    next_review_date = models.DateField(null=True, blank=True)

    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='kyc_verifications_performed',
    )
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def is_verified(self):
        return self.status == 'verified' and self.total_points >= 100

    def __str__(self):
        return f"KYC {self.customer.username}: {self.status} ({self.total_points} pts)"
