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
    created_at = models.DateTimeField(auto_now_add=True)

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
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"{self.check_name}: {status}"
