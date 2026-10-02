"""Sentry must not receive request bodies or stack-frame locals.

Login, registration and loan application bodies carry passwords and applicant
PII. sentry-sdk attaches request bodies whatever send_default_pii says, and
includes frame locals by default.
"""

import importlib
from unittest.mock import patch

import pytest

import config.settings.base as base_settings
from config.sentry import scrub_event


@pytest.fixture
def reloaded_with_dsn(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.example.invalid/1")
    with patch("sentry_sdk.init") as init:
        importlib.reload(base_settings)
    yield init
    monkeypatch.delenv("SENTRY_DSN")
    importlib.reload(base_settings)


def test_sentry_init_keeps_bodies_and_locals_out(reloaded_with_dsn):
    reloaded_with_dsn.assert_called_once()
    kwargs = reloaded_with_dsn.call_args.kwargs
    assert kwargs["max_request_body_size"] == "never"
    assert kwargs["include_local_variables"] is False
    assert kwargs["send_default_pii"] is False
    assert kwargs["before_send"] is scrub_event
    assert kwargs["before_send_transaction"] is scrub_event


def _frames():
    return [{"function": "post", "vars": {"password": "hunter2-long-pass"}}, {"function": "inner"}]


def test_scrub_event_drops_request_body_and_frame_vars():
    event = {
        "request": {"url": "https://api.example/api/v1/auth/login/", "data": {"password": "hunter2-long-pass"}},
        "exception": {"values": [{"type": "ValueError", "stacktrace": {"frames": _frames()}}]},
        "threads": {"values": [{"id": 1, "stacktrace": {"frames": _frames()}}]},
        "stacktrace": {"frames": _frames()},
    }

    result = scrub_event(event, hint={})

    assert result is event
    assert "data" not in result["request"]
    assert result["request"]["url"].endswith("/auth/login/")
    frames = (
        result["exception"]["values"][0]["stacktrace"]["frames"]
        + result["threads"]["values"][0]["stacktrace"]["frames"]
        + result["stacktrace"]["frames"]
    )
    assert len(frames) == 6
    assert all("vars" not in frame for frame in frames)
    assert "hunter2" not in repr(result)


def test_scrub_event_tolerates_events_without_request_or_frames():
    event = {"message": "plain log message", "exception": {"values": [{"type": "KeyError"}]}}
    assert scrub_event(event, hint={}) == {
        "message": "plain log message",
        "exception": {"values": [{"type": "KeyError"}]},
    }
