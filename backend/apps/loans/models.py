from django.conf import settings
from django.db import models
import uuid


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

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='loan_applications'
    )

    # Financial info
    annual_income = models.DecimalField(max_digits=12, decimal_places=2)
    credit_score = models.IntegerField()
    loan_amount = models.DecimalField(max_digits=12, decimal_places=2)
    loan_term_months = models.IntegerField(default=36)
    debt_to_income = models.DecimalField(max_digits=5, decimal_places=4)
    employment_length = models.IntegerField(help_text="Years of employment")

    # Categorical
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    home_ownership = models.CharField(
        max_length=20,
        choices=[('own', 'Own'), ('rent', 'Rent'), ('mortgage', 'Mortgage')],
    )
    has_cosigner = models.BooleanField(default=False)

    # Status
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

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
