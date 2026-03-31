"""Tests for intersectional fairness analysis.

Pure computation tests — no Django DB required.
"""

import numpy as np

from apps.ml_engine.services.intersectional_fairness import (
    _compute_group_fairness,
    compute_intersectional_fairness,
)

# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------


def _make_uniform_data(n=600):
    """Create data where all groups have identical approval rates (exactly 50%).

    Uses deterministic pattern (alternating 0/1) to avoid sampling noise
    that could trigger false amplification detection.
    """
    y_pred = np.array([0, 1] * (n // 2))  # exactly 50% approval for everyone
    y_true = y_pred.copy()
    y_prob = y_pred.astype(float)
    # 2 employment types, 2 applicant types, evenly distributed
    emp = np.array(["full_time", "part_time"] * (n // 2))[:n]
    app = np.array((["individual"] * (n // 2)) + (["joint"] * (n // 2)))
    return y_true, y_pred, y_prob, {"employment_type": emp, "applicant_type": app}


def _make_single_axis_compliant_intersectional_violation(n=1200):
    """Craft data that passes single-axis 80% rule but fails at intersection.

    Design:
        employment_type: A (600), B (600)
        applicant_type:  X (600), Y (600)

        Single-axis approval rates:
            A: ~50%, B: ~45%  => DI = 0.45/0.50 = 0.90 (passes)
            X: ~50%, Y: ~45%  => DI = 0.45/0.50 = 0.90 (passes)

        Intersectional:
            A+X: 70% approval (300 members)
            A+Y: 30% approval (300 members)  -> avg A = 50%
            B+X: 30% approval (300 members)
            B+Y: 60% approval (300 members)  -> avg B = 45%

        Intersection DI = 30/70 = 0.4286 (fails 80% rule)
    """
    rng = np.random.RandomState(123)
    group_size = n // 4  # 300 each

    emp = np.array(["A"] * (2 * group_size) + ["B"] * (2 * group_size))
    app = np.array(["X"] * group_size + ["Y"] * group_size + ["X"] * group_size + ["Y"] * group_size)

    # Approval rates per intersection
    rates = {
        ("A", "X"): 0.70,
        ("A", "Y"): 0.30,
        ("B", "X"): 0.30,
        ("B", "Y"): 0.60,
    }

    y_pred = np.zeros(4 * group_size, dtype=int)
    offset = 0
    for (_e, _a), rate in rates.items():
        approved = int(group_size * rate)
        segment = np.array([1] * approved + [0] * (group_size - approved))
        rng.shuffle(segment)
        y_pred[offset : offset + group_size] = segment
        offset += group_size

    y_true = y_pred.copy()
    y_prob = y_pred.astype(float)

    return y_true, y_pred, y_prob, {"employment_type": emp, "applicant_type": app}


# ---------------------------------------------------------------
# Tests
# ---------------------------------------------------------------


class TestUniformApprovalRates:
    """When all groups have similar approval rates, no amplification."""

    def test_no_amplification_detected(self):
        y_true, y_pred, y_prob, attrs = _make_uniform_data()
        result = compute_intersectional_fairness(y_true, y_pred, y_prob, attrs)

        assert not result["amplification_detected"]

    def test_single_axis_keys_present(self):
        y_true, y_pred, y_prob, attrs = _make_uniform_data()
        result = compute_intersectional_fairness(y_true, y_pred, y_prob, attrs)

        assert "employment_type" in result["single_axis"]
        assert "applicant_type" in result["single_axis"]

    def test_intersectional_key_present(self):
        y_true, y_pred, y_prob, attrs = _make_uniform_data()
        result = compute_intersectional_fairness(y_true, y_pred, y_prob, attrs)

        assert "employment_type x applicant_type" in result["intersectional"]

    def test_summary_is_string(self):
        y_true, y_pred, y_prob, attrs = _make_uniform_data()
        result = compute_intersectional_fairness(y_true, y_pred, y_prob, attrs)

        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0


class TestIntersectionalViolation:
    """Single-axis compliant but intersectional failure."""

    def setup_method(self):
        y_true, y_pred, y_prob, attrs = _make_single_axis_compliant_intersectional_violation()
        self.result = compute_intersectional_fairness(y_true, y_pred, y_prob, attrs)

    def test_single_axis_passes(self):
        for attr_name, attr_result in self.result["single_axis"].items():
            assert attr_result["passes_80_percent_rule"] is True, f"Single-axis {attr_name} should pass 80% rule"

    def test_intersectional_fails(self):
        pair = self.result["intersectional"]["employment_type x applicant_type"]
        assert pair["passes_80_percent_rule"] is False, "Intersectional DI should fail 80% rule"

    def test_amplification_detected(self):
        assert self.result["amplification_detected"] is True

    def test_worst_subgroup_identified(self):
        ws = self.result["worst_subgroup"]
        assert ws is not None
        assert ws["approval_rate"] == 0.3
        # The worst subgroup should be one of the 30% groups
        assert "0.3" in str(ws["approval_rate"])

    def test_summary_mentions_amplification(self):
        assert "AMPLIFICATION" in self.result["summary"]


class TestMinGroupSizeFiltering:
    """Small groups should be excluded from fairness computation."""

    def test_small_groups_excluded(self):
        n = 200
        y_pred = np.ones(n, dtype=int)
        # 195 in group 'big', 5 in group 'tiny'
        labels = np.array(["big"] * 195 + ["tiny"] * 5)

        result = _compute_group_fairness(y_pred, labels, min_group_size=30)

        assert "big" in result["groups"]
        assert "tiny" not in result["groups"]
        # With only one qualifying group, DI should be None
        assert result["disparate_impact_ratio"] is None

    def test_group_included_above_threshold(self):
        n = 200
        y_pred = np.ones(n, dtype=int)
        labels = np.array(["big"] * 100 + ["medium"] * 100)

        result = _compute_group_fairness(y_pred, labels, min_group_size=30)

        assert "big" in result["groups"]
        assert "medium" in result["groups"]

    def test_intersectional_respects_min_group_size(self):
        """Intersection subgroups below min_group_size are excluded."""
        rng = np.random.RandomState(99)
        n = 300
        y_pred = rng.randint(0, 2, size=n)
        y_true = y_pred.copy()
        y_prob = y_pred.astype(float)

        # Most people are A+X, a few are B+Y
        emp = np.array(["A"] * 290 + ["B"] * 10)
        app = np.array(["X"] * 290 + ["Y"] * 10)

        result = compute_intersectional_fairness(
            y_true,
            y_pred,
            y_prob,
            {"employment_type": emp, "applicant_type": app},
            min_group_size=30,
        )

        pair = result["intersectional"]["employment_type x applicant_type"]
        # B + Y group (10 members) should be excluded
        assert "B + Y" not in pair["groups"]


class TestEmptyInput:
    """Graceful handling of empty or degenerate inputs."""

    def test_empty_arrays(self):
        result = compute_intersectional_fairness(
            np.array([]),
            np.array([]),
            np.array([]),
            {"attr": np.array([])},
        )
        assert result["amplification_detected"] is False
        assert result["worst_subgroup"] is None
        assert "No data" in result["summary"]

    def test_no_protected_attributes(self):
        result = compute_intersectional_fairness(
            np.array([1, 0, 1]),
            np.array([1, 0, 1]),
            np.array([0.9, 0.1, 0.8]),
            {},
        )
        assert result["amplification_detected"] is False
        assert result["single_axis"] == {}
        assert result["intersectional"] == {}

    def test_single_attribute_no_intersections(self):
        """With only one attribute, there are no pairwise intersections."""
        n = 100
        y_pred = np.ones(n, dtype=int)
        y_true = y_pred.copy()
        y_prob = y_pred.astype(float)
        attrs = {"employment_type": np.array(["A"] * 50 + ["B"] * 50)}

        result = compute_intersectional_fairness(y_true, y_pred, y_prob, attrs)

        assert len(result["single_axis"]) == 1
        assert len(result["intersectional"]) == 0
        assert result["amplification_detected"] is False


class TestWorstSubgroupIdentification:
    """Ensure worst_subgroup is correctly identified."""

    def test_worst_subgroup_has_lowest_rate(self):
        y_true, y_pred, y_prob, attrs = _make_single_axis_compliant_intersectional_violation()
        result = compute_intersectional_fairness(y_true, y_pred, y_prob, attrs)

        ws = result["worst_subgroup"]
        # Collect all approval rates from all intersections
        all_rates = []
        for pair_result in result["intersectional"].values():
            for group_info in pair_result["groups"].values():
                all_rates.append(group_info["approval_rate"])

        assert ws["approval_rate"] == min(all_rates)

    def test_worst_subgroup_has_count(self):
        y_true, y_pred, y_prob, attrs = _make_single_axis_compliant_intersectional_violation()
        result = compute_intersectional_fairness(y_true, y_pred, y_prob, attrs)

        ws = result["worst_subgroup"]
        assert "count" in ws
        assert ws["count"] > 0


class TestAmplificationFlag:
    """Verify the amplification_detected flag logic."""

    def test_no_amplification_when_intersectional_is_better(self):
        """If intersections are better than single-axis, no amplification."""
        y_true, y_pred, y_prob, attrs = _make_uniform_data()
        result = compute_intersectional_fairness(y_true, y_pred, y_prob, attrs)

        assert not result["amplification_detected"]

    def test_amplification_when_intersectional_is_worse(self):
        """If intersections are worse than single-axis, amplification detected."""
        y_true, y_pred, y_prob, attrs = _make_single_axis_compliant_intersectional_violation()
        result = compute_intersectional_fairness(y_true, y_pred, y_prob, attrs)

        assert result["amplification_detected"] is True


class TestThreeAttributes:
    """With 3 attributes, should produce 3 pairwise intersections."""

    def test_three_pairwise_intersections(self):
        n = 600
        rng = np.random.RandomState(7)
        y_pred = rng.randint(0, 2, size=n)
        y_true = y_pred.copy()
        y_prob = y_pred.astype(float)

        attrs = {
            "employment_type": np.array(["FT", "PT", "CAS"] * (n // 3))[:n],
            "applicant_type": np.array(["IND", "JNT"] * (n // 2))[:n],
            "state": np.array(["NSW", "VIC", "QLD"] * (n // 3))[:n],
        }

        result = compute_intersectional_fairness(y_true, y_pred, y_prob, attrs)

        assert len(result["intersectional"]) == 3
        expected_pairs = {
            "employment_type x applicant_type",
            "employment_type x state",
            "applicant_type x state",
        }
        assert set(result["intersectional"].keys()) == expected_pairs
