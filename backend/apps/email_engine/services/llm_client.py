"""Provider adapter for OpenAI-compatible LLM email backends (Groq, Ollama).

Why this exists
---------------
Decision emails are written by an LLM, but the lending *decision* itself is
deterministic ML — so the email writer is a low-stakes, swappable component.
This adapter lets the email path run on any OpenAI-/chat-completions-compatible
endpoint instead of the paid Claude API:

  * **Groq** — a free hosted tier (no per-token cost), or
  * **Ollama** — a free, *local/on-prem* model (no per-minute token cap, and no
    data leaves the host — see ADR 010),

without touching the budget guard, the guardrail battery, or the deterministic
template fallback.

It deliberately duck-types ``anthropic.Anthropic`` so the single call site in
``api_budget.guarded_api_call`` (``client.messages.create(**kwargs)``) and the
response parsing in ``EmailGenerator._parse_tool_response`` need **no**
structural change. The adapter:

  * accepts Anthropic-shaped kwargs (``model``/``messages``/``max_tokens``/
    ``temperature``/``tools``/``tool_choice``),
  * translates the forced ``submit_email`` tool into OpenAI function-calling,
  * injects ``temperature=0`` + a fixed ``seed`` for reproducibility,
  * normalises the OpenAI response back into the Anthropic-ish object shape the
    caller reads (``.content[].type/.input/.text``, ``.usage.input_tokens/
    output_tokens``, ``.stop_reason``),
  * raises ``anthropic.RateLimitError`` on HTTP 429 so the existing retry seam
    in ``EmailGenerator`` is reused unchanged,
  * raises ``EmailBackendError`` on 4xx/5xx/transport failures so the caller
    degrades to the deterministic template.

Ollama notes (see ADR 010 + the research that drove this):
  * Ollama's OpenAI ``/v1`` endpoint *ignores* forced ``tool_choice``, so a
    small local model may answer in plain text. The adapter already emits a text
    block alongside any tool block, so ``_parse_tool_response``'s text fallback
    covers it; if that fails, guardrails + the template fallback are the floor.
  * Ollama's ``/v1`` endpoint also ignores a per-request context window, so the
    ~9k-token compliance prompt must be served by a model whose context window
    is baked in (a Modelfile ``PARAMETER num_ctx 16384`` — done in the compose
    ``ollama-init`` step, exposed as the ``loan-email`` model). Nothing extra is
    sent in the payload for that reason.
"""

import json
import logging

import anthropic
import httpx

from .exceptions import EmailBackendError

logger = logging.getLogger("email_engine.llm_client")

DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_MODEL = "llama-3.1-8b-instant"

# Local Ollama defaults. ``loan-email`` is the custom model baked with a 16k
# context window (Modelfile) by the compose ``ollama-init`` service.
DEFAULT_OLLAMA_BASE_URL = "http://ollama:11434/v1"
DEFAULT_OLLAMA_MODEL = "loan-email"


class _Block:
    """A single response content block (mirrors an Anthropic content block)."""

    __slots__ = ("type", "input", "text")

    def __init__(self, type, input=None, text=None):  # noqa: A002 — match Anthropic attr name
        self.type = type
        self.input = input
        self.text = text


class _Usage:
    """Token usage with Anthropic-style attribute names."""

    __slots__ = ("input_tokens", "output_tokens")

    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _Response:
    """Anthropic-shaped response the caller reads via attribute access."""

    __slots__ = ("content", "usage", "stop_reason")

    def __init__(self, content, usage, stop_reason):
        self.content = content
        self.usage = usage
        self.stop_reason = stop_reason


class _Messages:
    """Exposes ``.create(**kwargs)`` to mirror ``anthropic.Anthropic().messages``."""

    def __init__(self, client):
        self._client = client

    def create(self, **kwargs):
        return self._client._create(**kwargs)


def _to_openai_tool(anthropic_tool):
    """Translate an Anthropic tool def to OpenAI function-calling form."""
    return {
        "type": "function",
        "function": {
            "name": anthropic_tool.get("name"),
            "description": anthropic_tool.get("description", ""),
            "parameters": anthropic_tool.get("input_schema", {"type": "object", "properties": {}}),
        },
    }


def _map_finish_reason(finish_reason):
    """Map OpenAI ``finish_reason`` to the Anthropic ``stop_reason`` the caller checks.

    Only ``max_tokens`` matters downstream (it triggers the truncation guard in
    ``_parse_tool_response``); everything else passes through unchanged.
    """
    if finish_reason == "length":
        return "max_tokens"
    return finish_reason


class OpenAICompatibleLLMClient:
    """Minimal OpenAI-compatible chat client, duck-typed as anthropic.Anthropic.

    Works against any OpenAI-/chat-completions-compatible endpoint (Groq's free
    hosted tier or a local Ollama server). Only the surface ``EmailGenerator`` +
    ``guarded_api_call`` actually use is implemented:
    ``.messages.create(**anthropic_shaped_kwargs)`` returning an object exposing
    ``.content`` / ``.usage`` / ``.stop_reason``.

    ``provider`` is recorded on each APICallLog (Privacy Act APP 8 audit) — e.g.
    ``"groq"`` / ``"ollama"`` — and drives the logged destination country.
    """

    def __init__(
        self,
        api_key,
        base_url=DEFAULT_GROQ_BASE_URL,
        model=DEFAULT_GROQ_MODEL,
        seed=0,
        timeout=None,
        provider="groq",
    ):
        self._api_key = api_key
        self._base_url = (base_url or DEFAULT_GROQ_BASE_URL).rstrip("/")
        self._default_model = model or DEFAULT_GROQ_MODEL
        self._seed = seed
        self._http = httpx.Client(timeout=timeout or httpx.Timeout(60.0, connect=10.0))
        self.provider = provider
        self.messages = _Messages(self)

    # -- internal -----------------------------------------------------------

    def _create(self, **kwargs):
        payload = self._build_payload(kwargs)
        try:
            resp = self._http.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.HTTPError as exc:
            # Transport-level failure (e.g. a local Ollama server that isn't up)
            # — surface as a backend error so the caller degrades to the
            # deterministic template instead of crashing.
            raise EmailBackendError(f"{self.provider} request failed: {exc}") from exc

        if resp.status_code == 429:
            raise self._rate_limit_error(resp)
        if resp.status_code >= 400:
            # 4xx (e.g. 413 request-too-large on a small free tier) / 5xx →
            # degrade to the template rather than hard-error.
            raise EmailBackendError(f"{self.provider} API error {resp.status_code}: {resp.text[:300]}")

        return self._normalise(resp.json())

    def _build_payload(self, kwargs):
        payload = {
            "model": kwargs.get("model") or self._default_model,
            "messages": kwargs.get("messages", []),
            # AI_TEMPERATURE_DECISION_EMAIL is 0.0; seed makes the model
            # best-effort reproducible for the same prompt.
            "temperature": kwargs.get("temperature", 0.0),
            "seed": self._seed,
        }
        max_tokens = kwargs.get("max_tokens")
        if max_tokens:
            payload["max_tokens"] = max_tokens

        tools = kwargs.get("tools")
        if tools:
            payload["tools"] = [_to_openai_tool(t) for t in tools]

        tool_choice = kwargs.get("tool_choice")
        if isinstance(tool_choice, dict) and tool_choice.get("name"):
            # Anthropic {"type":"tool","name":X} -> OpenAI forced function call.
            # (Groq honours this; Ollama's /v1 ignores it and may answer in plain
            # text — handled by the text block emitted in _normalise.)
            payload["tool_choice"] = {"type": "function", "function": {"name": tool_choice["name"]}}
        return payload

    def _rate_limit_error(self, resp):
        """Build an ``anthropic.RateLimitError`` so EmailGenerator's existing
        ``except anthropic.RateLimitError`` seam is reused. Falls back to a
        generic error if the SDK signature differs."""
        try:
            return anthropic.RateLimitError(f"{self.provider} API rate limited", response=resp, body=None)
        except Exception:  # noqa: BLE001 — defensive against SDK signature drift
            return EmailBackendError(f"{self.provider} API rate limited (429)")

    def _normalise(self, data):
        """Convert an OpenAI chat-completion dict into the Anthropic-ish shape."""
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        blocks = []

        # Forced function call -> a synthetic tool_use block carrying {subject,body}.
        for call in message.get("tool_calls") or []:
            func = call.get("function") or {}
            raw_args = func.get("arguments")
            if not raw_args:
                continue
            try:
                parsed = json.loads(raw_args)
            except (TypeError, ValueError):
                logger.warning("tool_call arguments were not valid JSON — relying on text fallback")
                continue
            blocks.append(_Block(type="tool_use", input=parsed))

        # Always also expose any plain text so the caller's text-parse fallback
        # (EmailGenerator._parse_tool_response) can recover if the tool call was
        # malformed or empty — smaller / local models are less reliable at tool
        # use, and Ollama's /v1 endpoint ignores forced tool_choice entirely.
        text = message.get("content")
        if text:
            blocks.append(_Block(type="text", text=text))

        usage_raw = data.get("usage") or {}
        usage = _Usage(
            input_tokens=usage_raw.get("prompt_tokens", 0),
            output_tokens=usage_raw.get("completion_tokens", 0),
        )
        stop_reason = _map_finish_reason(choice.get("finish_reason"))
        return _Response(content=blocks, usage=usage, stop_reason=stop_reason)


# Back-compat alias: the original Groq-specific name. ``provider`` defaults to
# "groq", so existing call sites and tests that import/patch ``GroqLLMClient``
# keep working unchanged.
GroqLLMClient = OpenAICompatibleLLMClient
