"""Fail-safe bias-check behaviour (M7 / M10 / L21)."""


def test_bias_check_unavailable_counter_exists():
    from apps.agents.metrics import bias_check_unavailable_total

    # prometheus_client Counter exposes a _name and labelnames.
    assert bias_check_unavailable_total._name == "bias_check_unavailable"
    assert "mode" in bias_check_unavailable_total._labelnames
