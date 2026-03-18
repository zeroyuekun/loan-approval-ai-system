from django.db import models
import uuid


class AgentRun(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RUNNING = 'running', 'Running'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        ESCALATED = 'escalated', 'Escalated to Human'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(
        'loans.LoanApplication', on_delete=models.CASCADE, related_name='agent_runs'
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    steps = models.JSONField(default=list)  # [{step, status, started_at, completed_at, result}]
    total_time_ms = models.IntegerField(null=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
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
        'email_engine.GeneratedEmail', on_delete=models.CASCADE, related_name='bias_reports',
        null=True, blank=True,
    )
    marketing_email = models.ForeignKey(
        'agents.MarketingEmail', on_delete=models.CASCADE, related_name='bias_reports',
        null=True, blank=True,
    )
    report_type = models.CharField(
        max_length=20, default='decision',
        choices=[('decision', 'Decision'), ('marketing', 'Marketing')],
    )
    bias_score = models.FloatField()  # 0-100
    deterministic_score = models.FloatField(null=True, default=None)
    llm_raw_score = models.FloatField(null=True, default=None)
    score_source = models.CharField(max_length=20, default='composite')  # 'deterministic', 'llm', 'composite'
    categories = models.JSONField(default=list)  # ['gender', 'age', etc.]
    analysis = models.TextField()
    flagged = models.BooleanField(default=False)
    requires_human_review = models.BooleanField(default=False)
    ai_review_approved = models.BooleanField(null=True, default=None)
    ai_review_reasoning = models.TextField(blank=True, default='')
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
    offers = models.JSONField(default=list)  # [{type, name, amount, term, rate, benefit, reasoning}]
    analysis = models.TextField()
    customer_retention_score = models.FloatField(default=0)  # 0-100
    loyalty_factors = models.JSONField(default=list)
    personalized_message = models.TextField(blank=True)
    marketing_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"NBO for {self.application_id}: {len(self.offers)} offers (retention: {self.customer_retention_score})"


class MarketingEmail(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent_run = models.ForeignKey(
        AgentRun, on_delete=models.CASCADE, related_name='marketing_emails'
    )
    application = models.ForeignKey(
        'loans.LoanApplication', on_delete=models.CASCADE, related_name='marketing_emails'
    )
    subject = models.CharField(max_length=200)
    body = models.TextField()
    prompt_used = models.TextField()
    model_used = models.CharField(max_length=50, default='claude-sonnet-4-20250514')
    generation_time_ms = models.IntegerField(null=True)
    attempt_number = models.IntegerField(default=1)
    passed_guardrails = models.BooleanField(default=False)
    guardrail_results = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"MarketingEmail for {self.application_id}: {self.subject}"
