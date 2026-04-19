"""Registration smoke tests for the SLO histograms introduced in v1.10.4.

These tests pin the metric name + label shape so a future rename doesn't
silently break the Grafana dashboard and alert rules in
`monitoring/prometheus/alert_rules.yml`.
"""

from apps.agents.metrics import (
    bias_review_total,
    bias_review_ttr_seconds,
    pipeline_e2e_seconds,
)
from apps.email_engine.metrics import email_generation_total


class TestAgentsSLOMetrics:
    def test_pipeline_e2e_seconds_shape(self):
        assert "pipeline_e2e_seconds" in pipeline_e2e_seconds._name
        assert set(pipeline_e2e_seconds._labelnames) == {"status", "decision"}
        # Buckets must span the documented SLO range (1 s – 120 s) so
        # histogram_quantile(0.95) and (0.99) can be computed.
        bounds = pipeline_e2e_seconds._upper_bounds
        assert min(bounds) <= 1.0
        assert max(b for b in bounds if b != float("inf")) >= 60.0

    def test_pipeline_e2e_can_observe(self):
        pipeline_e2e_seconds.labels(status="completed", decision="approved").observe(5.0)

    def test_bias_review_ttr_shape(self):
        assert "bias_review_ttr_seconds" in bias_review_ttr_seconds._name
        assert set(bias_review_ttr_seconds._labelnames) == {"decision"}

    def test_bias_review_ttr_can_observe(self):
        bias_review_ttr_seconds.labels(decision="approved").observe(900.0)

    def test_bias_review_total_shape(self):
        # Counter's internal name strips the `_total` suffix.
        assert "bias_review" in bias_review_total._name
        assert set(bias_review_total._labelnames) == {"outcome"}

    def test_bias_review_total_can_increment(self):
        bias_review_total.labels(outcome="human_resolved").inc()


class TestEmailEngineSLOMetrics:
    def test_email_generation_total_shape(self):
        assert "email_generation" in email_generation_total._name
        assert set(email_generation_total._labelnames) == {"decision", "source", "status"}

    def test_email_generation_total_can_increment(self):
        email_generation_total.labels(
            decision="approved",
            source="claude_api",
            status="success",
        ).inc()
