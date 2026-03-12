from django.db import models
import uuid


class AgentRun(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RUNNING = 'running', 'Running'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(
        'loans.LoanApplication', on_delete=models.CASCADE, related_name='agent_runs'
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    steps = models.JSONField(default=list)  # [{step, status, started_at, completed_at, result}]
    total_time_ms = models.IntegerField(null=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"AgentRun {self.id} - {self.status}"


class BiasReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent_run = models.ForeignKey(
        AgentRun, on_delete=models.CASCADE, related_name='bias_reports'
    )
    email = models.ForeignKey(
        'email_engine.GeneratedEmail', on_delete=models.CASCADE, related_name='bias_reports'
    )
    bias_score = models.FloatField()  # 0-100
    categories = models.JSONField(default=list)  # ['gender', 'age', etc.]
    analysis = models.TextField()
    flagged = models.BooleanField(default=False)
    requires_human_review = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"BiasReport {self.id}: score={self.bias_score}"


class NextBestOffer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent_run = models.ForeignKey(
        AgentRun, on_delete=models.CASCADE, related_name='next_best_offers'
    )
    application = models.ForeignKey(
        'loans.LoanApplication', on_delete=models.CASCADE, related_name='next_best_offers'
    )
    offers = models.JSONField(default=list)  # [{type, amount, term, rate, reasoning}]
    analysis = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"NBO for {self.application_id}: {len(self.offers)} offers"
