"""Shared helpers for Anthropic API call construction.

The main export is ``build_cached_call_kwargs`` — it constructs the
``client.messages.create(**kwargs)`` payload with Anthropic prompt
caching turned on for the static instructions block. Use it anywhere
the prompt has a stable instruction block ≥1024 tokens that repeats
across calls (Sonnet/Opus minimum; Haiku needs ≥2048).

Pattern:
    1. Move all the static rules / format / template instructions into a
       single string passed as ``system_text``.
    2. Move all per-call dynamic data (applicant name, banking context,
       reasons, ...) into a single string passed as ``user_text``.
    3. The helper wraps the system text in a ``cache_control: ephemeral``
       block — Anthropic stores its processed form server-side for 5 min,
       charging 0.1× the normal input rate on subsequent hits in that
       window. Misses pay 1.25× (small one-time write cost), so the
       break-even is ~2-3 calls per 5-min window.

Docs: https://docs.claude.com/en/docs/build-with-claude/prompt-caching

Tools / temperature / max_tokens / model and any other kwargs pass
through unchanged via ``**other_kwargs``.
"""

from __future__ import annotations

from typing import Any


def build_cached_call_kwargs(
    *,
    system_text: str,
    user_text: str,
    **other_kwargs: Any,
) -> dict[str, Any]:
    """Build a kwargs dict for ``client.messages.create`` with the system
    block cached via Anthropic prompt caching (5-min ephemeral TTL).

    The static instructions in ``system_text`` become the cache key.
    ``user_text`` is the dynamic per-call payload (not cached). Any
    additional keyword arguments — ``model``, ``max_tokens``,
    ``temperature``, ``tools``, ``tool_choice``, etc. — pass through.

    Returns a dict you can splat into ``client.messages.create(**kw)``
    or any wrapper (e.g. ``guarded_api_call(client, **kw)``).
    """
    return {
        "system": [
            {
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": user_text}],
        **other_kwargs,
    }
