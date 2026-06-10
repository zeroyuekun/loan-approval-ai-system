"""Watchdog must treat a 403 from the ops-gated /api/v1/health/deep/ endpoint as
an AUTH state (no/!valid HEALTH_CHECK_TOKEN — typical in local dev), not a health
failure. Before this guard, a 403 body ({"error": "unauthorized"}) fell through to
the degraded branch and falsely escalated consecutive_failures → CRITICAL alerts.
A genuine 503 (degraded) body must still count, and a 200 healthy body still resets.

The token-UNSET 403 skip must not swallow production token drift, though: when a
token IS configured but rejected (rotated server-side while the watchdog still
holds the old env copy), every cycle 403s forever. Treating that as a benign skip
left consecutive_failures at 0 and let the watchdog:health Redis key (120s TTL)
expire — monitoring silently dead. That case must count as a failure, record an
"auth_rejected" health state, and escalate to the CRITICAL alert at threshold.
"""

from unittest.mock import MagicMock, patch

from django.test import override_settings

from apps.agents.management.commands.watchdog import Command


def _command(consecutive_failures=0):
    cmd = Command()
    cmd.consecutive_failures = consecutive_failures
    cmd.max_failures = 3
    return cmd


def _resp(status_code, body):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    return resp


@patch.object(Command, "_record_health")
@patch("apps.agents.management.commands.watchdog.httpx.get")
def test_gated_403_is_not_a_health_failure(mock_get, mock_record):
    mock_get.return_value = _resp(403, {"error": "unauthorized"})
    cmd = _command()

    cmd._check_health()

    assert cmd.consecutive_failures == 0  # auth state, not penalised
    mock_record.assert_not_called()


@patch.object(Command, "_record_health")
@patch("apps.agents.management.commands.watchdog.httpx.get")
def test_degraded_503_counts_as_failure(mock_get, mock_record):
    mock_get.return_value = _resp(503, {"database": "error: down", "redis": "ok", "status": "degraded"})
    cmd = _command()

    cmd._check_health()

    assert cmd.consecutive_failures == 1
    mock_record.assert_called_once()
    assert mock_record.call_args[0][0] == "degraded"


@patch.object(Command, "_record_health")
@patch("apps.agents.management.commands.watchdog.httpx.get")
def test_healthy_200_resets_failures(mock_get, mock_record):
    mock_get.return_value = _resp(200, {"database": "ok", "redis": "ok", "status": "healthy"})
    cmd = _command(consecutive_failures=2)

    cmd._check_health()

    assert cmd.consecutive_failures == 0
    mock_record.assert_called_once()
    assert mock_record.call_args[0][0] == "healthy"


@override_settings(HEALTH_CHECK_TOKEN="ops-token-rotated-away")
@patch.object(Command, "_record_health")
@patch("apps.agents.management.commands.watchdog.httpx.get")
def test_403_with_token_configured_counts_as_auth_rejected(mock_get, mock_record):
    """Token drift (configured token rejected) must count + keep Redis key alive."""
    mock_get.return_value = _resp(403, {"error": "unauthorized"})
    cmd = _command()

    cmd._check_health()

    assert cmd.consecutive_failures == 1
    mock_record.assert_called_once()
    assert mock_record.call_args[0][0] == "auth_rejected"


@override_settings(HEALTH_CHECK_TOKEN="ops-token-rotated-away")
@patch("apps.agents.management.commands.watchdog.logger")
@patch.object(Command, "_record_health")
@patch("apps.agents.management.commands.watchdog.httpx.get")
def test_403_with_token_at_threshold_fires_critical_alert(mock_get, mock_record, mock_logger):
    """Persistent token drift must escalate to the CRITICAL alert path."""
    mock_get.return_value = _resp(403, {"error": "unauthorized"})
    cmd = _command(consecutive_failures=2)  # max_failures=3 → this cycle hits threshold

    cmd._check_health()

    assert cmd.consecutive_failures == 3
    assert mock_record.call_args[0][0] == "auth_rejected"
    mock_logger.critical.assert_called_once()
    assert "3" in mock_logger.critical.call_args[0][0] % mock_logger.critical.call_args[0][1:]


@patch("apps.agents.management.commands.watchdog.logger")
@patch.object(Command, "_record_health")
@patch("apps.agents.management.commands.watchdog.httpx.get")
def test_403_without_token_never_fires_critical(mock_get, mock_record, mock_logger):
    """Token-unset (local dev) 403s stay a benign skip even past the threshold."""
    mock_get.return_value = _resp(403, {"error": "unauthorized"})
    cmd = _command(consecutive_failures=2)

    cmd._check_health()

    assert cmd.consecutive_failures == 2  # untouched
    mock_record.assert_not_called()
    mock_logger.critical.assert_not_called()
