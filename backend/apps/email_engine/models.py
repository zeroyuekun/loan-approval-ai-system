from django.db import models
import uuid


class GeneratedEmail(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(
        'loans.LoanApplication', on_delete=models.CASCADE, related_name='emails'
    )
    decision = models.CharField(max_length=20)
    subject = models.CharField(max_length=200)
    body = models.TextField()
    prompt_used = models.TextField()
    model_used = models.CharField(max_length=50, default='claude-sonnet-4-20250514')
    generation_time_ms = models.IntegerField(null=True)
    attempt_number = models.IntegerField(default=1)
    passed_guardrails = models.BooleanField(default=False)
    template_fallback = models.BooleanField(default=False, help_text='True if generated from static template (Claude API unavailable)')

    # Token & cost tracking
    input_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)
    estimated_cost_usd = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Email for {self.application_id}: {self.subject}"


class GuardrailLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.ForeignKey(
        GeneratedEmail, on_delete=models.CASCADE, related_name='guardrail_checks'
    )
    check_name = models.CharField(max_length=100)
    passed = models.BooleanField()
    details = models.TextField(blank=True)
    category = models.CharField(
        max_length=20, default='decision',
        choices=[('shared', 'Shared'), ('decision', 'Decision'), ('marketing', 'Marketing')],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['email', '-created_at'], name='guardrail_email_created'),
        ]

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"{self.check_name}: {status}"


class GuardrailAnalytics(models.Model):
    """Weekly guardrail effectiveness snapshot."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    week_start = models.DateField(db_index=True)
    check_name = models.CharField(max_length=100)
    total_runs = models.IntegerField(default=0)
    pass_count = models.IntegerField(default=0)
    fail_count = models.IntegerField(default=0)
    pass_rate = models.FloatField(default=0.0)
    retry_rate = models.FloatField(default=0.0, help_text='% of emails that needed at least 1 retry')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('week_start', 'check_name')]
        ordering = ['-week_start', 'check_name']

    def __str__(self):
        return f"Guardrail {self.check_name} week {self.week_start}: {self.pass_rate:.1%} pass"


class PromptVersion(models.Model):
    """Track which prompt template produced which email for A/B testing and rollback."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, help_text='e.g. approval_v2, denial_empathetic')
    prompt_type = models.CharField(
        max_length=20,
        choices=[('approval', 'Approval'), ('denial', 'Denial'), ('marketing', 'Marketing')],
    )
    template_text = models.TextField()
    is_active = models.BooleanField(default=False)
    version = models.IntegerField(default=1)

    # Performance tracking
    total_uses = models.IntegerField(default=0)
    guardrail_pass_rate = models.FloatField(null=True, blank=True)
    avg_generation_time_ms = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('name', 'version')]

    def __str__(self):
        status = 'ACTIVE' if self.is_active else 'inactive'
        return f"Prompt {self.name} v{self.version} ({status})"
