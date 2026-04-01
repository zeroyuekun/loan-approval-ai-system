"""Tests for pre-deployment fairness gate.

The fairness gate checks disparate impact ratio >= 0.80 (EEOC four-fifths rule)
across all protected attributes before a model can go active.
"""

from apps.ml_engine.services.fairness_gate import check_fairness_gate


class TestFairnessGate:
    def _make_fairness_metrics(self, **overrides):
        """Build fairness metrics dict mimicking MetricsService output."""
        defaults = {
            "employment_type": {
                "groups": {
                    "payg_permanent": {"count": 500, "predicted_approval_rate": 0.70},
                    "self_employed": {"count": 200, "predicted_approval_rate": 0.60},
                },
                "disparate_impact_ratio": 0.857,  # 0.60/0.70 = 0.857, passes
                "equalized_odds_difference": 0.05,
                "passes_80_percent_rule": True,
            },
            "applicant_type": {
                "groups": {
                    "single": {"count": 400, "predicted_approval_rate": 0.65},
                    "couple": {"count": 300, "predicted_approval_rate": 0.72},
                },
                "disparate_impact_ratio": 0.903,  # 0.65/0.72 = 0.903, passes
                "equalized_odds_difference": 0.03,
                "passes_80_percent_rule": True,
            },
        }
        defaults.update(overrides)
        return defaults

    def test_passes_when_all_above_threshold(self):
        metrics = self._make_fairness_metrics()
        result = check_fairness_gate(metrics)
        assert result["passed"] is True
        assert result["minimum_dir"] >= 0.80
        assert result["failing_attributes"] == []

    def test_fails_when_dir_below_threshold(self):
        metrics = self._make_fairness_metrics(
            employment_type={
                "groups": {
                    "payg_permanent": {"count": 500, "predicted_approval_rate": 0.80},
                    "self_employed": {"count": 200, "predicted_approval_rate": 0.50},
                },
                "disparate_impact_ratio": 0.625,  # 0.50/0.80 = 0.625, fails
                "equalized_odds_difference": 0.10,
                "passes_80_percent_rule": False,
            }
        )
        result = check_fairness_gate(metrics)
        assert result["passed"] is False
        assert "employment_type" in result["failing_attributes"]
        assert result["minimum_dir"] < 0.80

    def test_custom_threshold(self):
        metrics = self._make_fairness_metrics(
            employment_type={
                "groups": {},
                "disparate_impact_ratio": 0.85,
                "equalized_odds_difference": 0.05,
                "passes_80_percent_rule": True,
            }
        )
        # Passes at 0.80 but fails at 0.90
        result_80 = check_fairness_gate(metrics, threshold=0.80)
        assert result_80["passed"] is True

        result_90 = check_fairness_gate(metrics, threshold=0.90)
        assert result_90["passed"] is False

    def test_handles_none_dir(self):
        """Attributes with undefined DIR (single group) should not fail the gate."""
        metrics = {
            "single_group_attr": {
                "groups": {"only_group": {"count": 100, "predicted_approval_rate": 0.70}},
                "disparate_impact_ratio": None,
                "equalized_odds_difference": 0.0,
                "passes_80_percent_rule": None,
            }
        }
        result = check_fairness_gate(metrics)
        assert result["passed"] is True
        assert result["minimum_dir"] is None

    def test_empty_metrics_passes(self):
        result = check_fairness_gate({})
        assert result["passed"] is True
        assert result["results"] == []

    def test_result_structure(self):
        metrics = self._make_fairness_metrics()
        result = check_fairness_gate(metrics)
        assert "passed" in result
        assert "threshold" in result
        assert "results" in result
        assert "minimum_dir" in result
        assert "failing_attributes" in result
        assert result["threshold"] == 0.80

    def test_multiple_failures_reported(self):
        metrics = {
            "attr_a": {"disparate_impact_ratio": 0.70},
            "attr_b": {"disparate_impact_ratio": 0.75},
            "attr_c": {"disparate_impact_ratio": 0.90},
        }
        result = check_fairness_gate(metrics)
        assert result["passed"] is False
        assert set(result["failing_attributes"]) == {"attr_a", "attr_b"}
        assert result["minimum_dir"] == 0.70
