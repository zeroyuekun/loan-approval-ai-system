"""Shared input sanitization for prompt injection hardening.

Used by email_generator.py, bias_detector.py, and any other service that
passes user-controlled strings into LLM prompts.

Improvements over the original per-module implementations:
- Unicode NFKC normalization (collapses homoglyphs like fullwidth chars)
- Zero-width character stripping (U+200B, U+200C, U+200D, U+FEFF, etc.)
- Broader injection pattern coverage
"""

import re
import unicodedata

# Zero-width and invisible Unicode characters used for obfuscation
_INVISIBLE_CHARS = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f\u2060\u2061\u2062\u2063\u2064\ufeff\u00ad\u034f\u061c\u180e]"
)

_INJECTION_BLOCKLIST = re.compile(
    r"(?:ignore\s+(?:previous|above|all)\s+instructions"
    r"|disregard\s+(?:previous|above|all)\s+instructions"
    r"|system\s+prompt"
    r"|you\s+are\s+now"
    r"|new\s+instructions"
    r"|forget\s+(?:previous|your|all)\s+instructions"
    r"|override\s+(?:previous|your|all)\s+instructions"
    r"|act\s+as\s+(?:a|an|the)\s+"
    r"|pretend\s+(?:you|to\s+be)"
    r"|do\s+not\s+follow\s+(?:previous|above|any)\s+instructions"
    r"|<\s*/?(?:system|user|assistant|human)\s*>)",
    re.IGNORECASE,
)


def sanitize_prompt_input(value, max_length=500):
    """Strip characters and patterns that could manipulate prompt structure.

    1. Unicode NFKC normalization (collapses fullwidth, compatibility forms)
    2. Strip zero-width / invisible characters
    3. Remove prompt-structural characters (<>[]{}|)
    4. Collapse whitespace
    5. Remove known injection phrases
    6. Truncate to max_length
    """
    if not isinstance(value, str):
        return value

    # Normalize Unicode (NFKC collapses fullwidth A → A, homoglyphs, etc.)
    value = unicodedata.normalize("NFKC", value)

    # Strip invisible characters
    value = _INVISIBLE_CHARS.sub("", value)

    # Remove prompt-structural characters
    value = re.sub(r"[<>\[\]{}|]", "", value)

    # Collapse all whitespace (newlines, tabs) to single spaces
    value = re.sub(r"\s+", " ", value)

    # Remove known injection phrases
    value = _INJECTION_BLOCKLIST.sub("", value)

    return value[:max_length].strip()
