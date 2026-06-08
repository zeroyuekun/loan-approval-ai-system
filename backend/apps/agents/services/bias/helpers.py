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
        )
    return None


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


def _call_with_retry(client, fallback, service_name, final_failure_suffix, **api_kwargs):
    """Call the Anthropic API with a single-attempt policy.

    time.sleep() inside a Celery worker blocks the thread and prevents other
    tasks from running, so retry backoff inside the worker has been removed.
    The caller (bias detector) already handles transient failures gracefully
    by returning the supplied ``fallback`` dict, which is scored as the worst-
    case (high-risk) bias result.  Non-transient (4xx) errors are not retried.
    BudgetExhausted / CircuitOpen propagate so callers can invoke
    _handle_bias_unavailable.

    If a single attempt raises a transient error (RateLimit, Timeout, Connection,
    5xx), the function returns ``fallback`` immediately without sleeping.
    """
    try:
        response = guarded_api_call(client, **api_kwargs)
        return _extract_tool_result(response, fallback)
    except anthropic.AuthenticationError as e:
        logger.error("%s auth error (not retryable): %s", service_name, e)
        return fallback
    except anthropic.RateLimitError as e:
        logger.warning("%s rate limited — returning fallback (no sleep): %s", service_name, e)
        logger.error("%s failed (rate limit) — %s", service_name, final_failure_suffix)
        return fallback
    except (anthropic.APITimeoutError, anthropic.APIConnectionError) as e:
        logger.warning("%s connection/timeout — returning fallback (no sleep): %s", service_name, e)
        logger.error("%s failed — %s", service_name, final_failure_suffix)
        return fallback
    except anthropic.APIStatusError as e:
        if e.status_code >= 500:
            logger.warning("%s server error (%d) — returning fallback (no sleep): %s", service_name, e.status_code, e)
            logger.error("%s failed (server error) — %s", service_name, final_failure_suffix)
            return fallback
        else:
            logger.error("%s client error (%d, not retryable): %s", service_name, e.status_code, e)
            return fallback
    except (BudgetExhausted, CircuitOpen):
        raise  # let callers invoke _handle_bias_unavailable
    except Exception as e:
        logger.critical("%s UNEXPECTED failure: %s", service_name, e, exc_info=True)
        return fallback
