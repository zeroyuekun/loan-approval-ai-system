"""Tests for custom Prometheus ML metrics."""

from apps.ml_engine.services.predictor import (
    ml_drift_warnings_total,
    ml_prediction_confidence,
    ml_prediction_latency_seconds,
    ml_predictions_total,
)


class TestPrometheusMetrics:
    def test_predictions_counter_registered(self):
        # prometheus_client Counter strips _total suffix from _name
        assert 'ml_predictions' in ml_predictions_total._name
        assert 'decision' in ml_predictions_total._labelnames
        assert 'model_version' in ml_predictions_total._labelnames

    def test_latency_histogram_registered(self):
        assert 'ml_prediction_latency' in ml_prediction_latency_seconds._name

    def test_confidence_histogram_registered(self):
        assert 'ml_prediction_confidence' in ml_prediction_confidence._name
        assert len(ml_prediction_confidence._upper_bounds) == 11  # 10 buckets + inf

    def test_drift_counter_registered(self):
        assert 'ml_drift_warnings' in ml_drift_warnings_total._name

    def test_counter_can_increment(self):
        before = ml_drift_warnings_total._value.get()
        ml_drift_warnings_total.inc()
        after = ml_drift_warnings_total._value.get()
        assert after == before + 1

    def test_histogram_can_observe(self):
        ml_prediction_latency_seconds.observe(0.5)
        ml_prediction_confidence.observe(0.75)
