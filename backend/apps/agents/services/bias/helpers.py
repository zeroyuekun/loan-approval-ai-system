import json
import logging
import os

import anthropic
import httpx

from utils.sanitization import sanitize_prompt_input as _sanitize_prompt_input

from ..api_budget import BudgetExhausted, CircuitOpen, guarded_api_call

logger = logging.getLogger("agents.bias_detector")


def _parse_json_response(response_text, fallback):
    """Extract JSON from a response, returning fallback on failure."""
    try:
        json_start = response_text.find("{")
        json_end = response_text.rfind("}") + 1
        return json.loads(response_text[json_start:json_end])
    except (json.JSONDecodeError, ValueError):
        return fallback


def _extract_tool_result(response, fallback):
    """Extract structured result from tool_use response, with fallback."""
    try:
        tool_block = next(b for b in response.content if b.type == "tool_use")
        return tool_block.input
    except (StopIteration, AttributeError):
        text_block = next((b for b in response.content if b.type == "text"), None)
        if text_block:
            return _parse_json_response(text_block.text, fallback)
        return fallback


def _make_anthropic_client():
    """Construct an Anthropic client if ANTHROPIC_API_KEY is set, else None."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        return anthropic.Anthropic(
            api_key=api_key,
            timeout=httpx.Timeout(60.0, connect=10.0),
            # Pin the SDK's transient-error retry policy (connect errors,
            # 408/429/5xx with backoff) so the relied-upon default can't drift.
            max_retries=2,
        )
    return None


# Default for the senior compliance reviewers (Opus 4.8 — free same-price
# upgrade over legacy 4.7). Configurable via BIAS_REVIEWER_MODEL.
DEFAULT_REVIEWER_MODEL = "claude-opus-4-8"


def _reviewer_model():
    """Resolve the senior-reviewer model; blank or unset falls back to the default."""
    from django.conf import settings as django_settings

    return getattr(django_settings, "BIAS_REVIEWER_MODEL", "") or DEFAULT_REVIEWER_MODEL


def _format_flag_detail(prescreen):
    """Format each individual flag with its details for the junior analyst."""
    if not prescreen["findings"]:
        return "No flags to classify."
    lines = []
    for i, finding in enumerate(prescreen["findings"], 1):
        check_name = finding.get("check_name", "unknown")
        sanitized_finding = _sanitize_prompt_input(str(finding.get("details", "No details")), max_length=500)
        lines.append(f"Flag {i}: [{check_name}] {sanitized_finding}")
    return "\n".join(lines)


def _call_with_fallback(client, fallback, service_name, final_failure_suffix, **api_kwargs):
    """Call the Anthropic API once, returning ``fallback`` on terminal failure.

    Transient errors are retried by the SDK client's own bounded backoff
    (policy pinned in _make_anthropic_client); there is no extra retry loop
    here, which would hold the Celery worker thread longer. Any API error
    that survives the SDK retries returns ``fallback``, which the
    bias-detector callers score as the worst-case (high-risk) result.
    BudgetExhausted and CircuitOpen propagate so callers can invoke
    _handle_bias_unavailable.
    """
    try:
        response = guarded_api_call(client, **api_kwargs)
        return _extract_tool_result(response, fallback)
    except (BudgetExhausted, CircuitOpen):
        raise  # let callers invoke _handle_bias_unavailable
    except anthropic.APIError as e:
        logger.error("%s failed (%s: %s) — %s", service_name, type(e).__name__, e, final_failure_suffix)
        return fallback
    except Exception as e:
        logger.critical("%s UNEXPECTED failure: %s", service_name, e, exc_info=True)
        return fallback
