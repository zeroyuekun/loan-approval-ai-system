"""Unit tests for the free Groq email backend adapter (GroqLLMClient).

These verify the adapter normalises an OpenAI/Groq chat-completion response into
the exact Anthropic-ish shape that EmailGenerator._parse_tool_response and
guarded_api_call read — without any network calls (httpx client is mocked).
"""

import json
from unittest.mock import MagicMock

import anthropic
import httpx
import pytest

from apps.email_engine.services.email_generator import EMAIL_SUBMIT_TOOL
from apps.email_engine.services.llm_client import (
    GroqLLMClient,
    _map_finish_reason,
    _to_openai_tool,
)


def _http_response(status_code=200, payload=None, text_body=""):
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    if payload is not None:
        return httpx.Response(status_code, request=req, json=payload)
    return httpx.Response(status_code, request=req, text=text_body)


def _client(seed=7):
    c = GroqLLMClient(api_key="test-key", model="llama-3.1-8b-instant", seed=seed)
    c._http = MagicMock()  # replace the real httpx.Client
    return c


def _completion(*, tool_args=None, text=None, finish_reason="tool_calls", usage=None):
    message = {"content": text}
    if tool_args is not None:
        message["tool_calls"] = [
            {"function": {"name": "submit_email", "arguments": tool_args}}
        ]
    return {
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": usage or {"prompt_tokens": 12, "completion_tokens": 34},
    }


class TestTranslationHelpers:
    def test_to_openai_tool_maps_input_schema_to_parameters(self):
        out = _to_openai_tool(EMAIL_SUBMIT_TOOL)
        assert out["type"] == "function"
        assert out["function"]["name"] == "submit_email"
        assert out["function"]["parameters"] == EMAIL_SUBMIT_TOOL["input_schema"]

    def test_length_finish_reason_maps_to_max_tokens(self):
        # Only this mapping matters: it drives the truncation guard downstream.
        assert _map_finish_reason("length") == "max_tokens"
        assert _map_finish_reason("stop") == "stop"
        assert _map_finish_reason("tool_calls") == "tool_calls"


class TestGroqResponseNormalisation:
    def test_tool_call_becomes_tool_use_block_with_usage(self):
        c = _client()
        c._http.post.return_value = _http_response(
            payload=_completion(
                tool_args=json.dumps({"subject": "S", "body": "B"}),
                usage={"prompt_tokens": 100, "completion_tokens": 200},
            )
        )

        resp = c.messages.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": "x"}],
            max_tokens=512,
            tools=[EMAIL_SUBMIT_TOOL],
            tool_choice={"type": "tool", "name": "submit_email"},
        )

        tool_block = next(b for b in resp.content if b.type == "tool_use")
        assert tool_block.input == {"subject": "S", "body": "B"}
        assert resp.usage.input_tokens == 100
        assert resp.usage.output_tokens == 200

    def test_finish_length_sets_stop_reason_max_tokens(self):
        c = _client()
        c._http.post.return_value = _http_response(
            payload=_completion(tool_args=json.dumps({"subject": "S", "body": "B"}), finish_reason="length")
        )
        resp = c.messages.create(messages=[{"role": "user", "content": "x"}])
        assert resp.stop_reason == "max_tokens"

    def test_malformed_tool_args_falls_back_to_text_block(self):
        c = _client()
        c._http.post.return_value = _http_response(
            payload=_completion(tool_args="{not valid json", text="Subject: Hi\n\nReal body text", finish_reason="stop")
        )
        resp = c.messages.create(messages=[{"role": "user", "content": "x"}])
        # No usable tool_use block, but the text block survives for the
        # caller's text-parse fallback.
        assert all(b.type != "tool_use" for b in resp.content)
        text_block = next(b for b in resp.content if b.type == "text")
        assert "Real body text" in text_block.text

    def test_missing_usage_defaults_to_zero(self):
        c = _client()
        payload = _completion(tool_args=json.dumps({"subject": "S", "body": "B"}))
        del payload["usage"]
        c._http.post.return_value = _http_response(payload=payload)
        resp = c.messages.create(messages=[{"role": "user", "content": "x"}])
        assert resp.usage.input_tokens == 0
        assert resp.usage.output_tokens == 0


class TestGroqRequestPayload:
    def test_payload_injects_seed_temperature_and_translated_tool(self):
        c = _client(seed=42)
        c._http.post.return_value = _http_response(
            payload=_completion(tool_args=json.dumps({"subject": "S", "body": "B"}))
        )

        c.messages.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=2048,
            temperature=0.0,
            tools=[EMAIL_SUBMIT_TOOL],
            tool_choice={"type": "tool", "name": "submit_email"},
        )

        sent = c._http.post.call_args.kwargs["json"]
        assert sent["seed"] == 42
        assert sent["temperature"] == 0.0
        assert sent["max_tokens"] == 2048
        assert sent["model"] == "llama-3.1-8b-instant"
        assert sent["tool_choice"] == {"type": "function", "function": {"name": "submit_email"}}
        assert sent["tools"][0]["function"]["name"] == "submit_email"
        # Auth header carries the bearer key.
        assert c._http.post.call_args.kwargs["headers"]["Authorization"] == "Bearer test-key"


class TestGroqErrorHandling:
    def test_429_raises_anthropic_rate_limit_error(self):
        c = _client()
        c._http.post.return_value = _http_response(status_code=429, payload={"error": "rate limited"})
        with pytest.raises(anthropic.RateLimitError):
            c.messages.create(messages=[{"role": "user", "content": "x"}])

    def test_500_raises_runtime_error(self):
        c = _client()
        c._http.post.return_value = _http_response(status_code=500, text_body="upstream boom")
        with pytest.raises(RuntimeError):
            c.messages.create(messages=[{"role": "user", "content": "x"}])

    def test_transport_error_raises_runtime_error(self):
        c = _client()
        c._http.post.side_effect = httpx.ConnectError("no route")
        with pytest.raises(RuntimeError):
            c.messages.create(messages=[{"role": "user", "content": "x"}])

    def test_provider_attribute_is_groq(self):
        # guarded_api_call reads getattr(client, "provider", "anthropic") for the
        # cross-border audit log.
        assert GroqLLMClient(api_key="x").provider == "groq"
