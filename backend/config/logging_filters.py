"""PII masking filter for structured logging.

Redacts sensitive financial and identity data from log messages before
they reach any handler (console, file, aggregator). Patterns cover
Australian-format identifiers and common financial fields.
"""

import logging
import re


class PiiMaskingFilter(logging.Filter):
    """Redact PII patterns from log record messages and args."""

    _PATTERNS: list[tuple[re.Pattern, str]] = [
        # Phone numbers FIRST: a spaced/dashed phone tail otherwise gets stolen
        # and mislabelled by the generic 9-digit TFN/Medicare matchers below.
        # Australian mobile (04XX XXX XXX), landline ((0X) XXXX XXXX) and +61
        # forms, tolerant of spaces/dashes between groups — CustomerProfile.phone
        # is a free-text CharField, so real values are rarely an unbroken run.
        (re.compile(r"(?:\+?61[\s-]?|\(?0)[2-478]\)?(?:[\s-]?\d){8}"), "[PHONE_REDACTED]"),
        # Australian Tax File Number (XXX XXX XXX)
        (re.compile(r"\b\d{3}\s?\d{3}\s?\d{3}\b"), "[TFN_REDACTED]"),
        # Medicare number (XXXX XXXXX X)
        (re.compile(r"\b\d{4}\s?\d{5}\s?\d\b"), "[MEDICARE_REDACTED]"),
        # Email addresses
        (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[EMAIL_REDACTED]"),
        # Dollar amounts following sensitive keywords
        (re.compile(r'(?:income|salary|wage|earning)[=:\s"\']+\$?[\d,.]+', re.IGNORECASE), "[INCOME_REDACTED]"),
        # Generic ID number patterns after identity keywords
        (re.compile(r'(?:passport|licence|license|driver)[=:\s"\']+[A-Z0-9]{6,12}', re.IGNORECASE), "[ID_REDACTED]"),
    ]

    # Standard LogRecord attributes — anything NOT here was attached via the
    # logging `extra={...}` kwarg and may carry PII, so it must be scrubbed too.
    _STD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(str(record.msg))
        if record.args:
            # Redact ONLY string args — coercing numbers to str (the old
            # behaviour) corrupted them so a "%d"/"%f" format string then raised
            # TypeError at emit time. PII only ever appears in string args.
            if isinstance(record.args, dict):
                record.args = {k: (self._redact(v) if isinstance(v, str) else v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._redact(a) if isinstance(a, str) else a for a in record.args)
        # Structured-logging extras land as custom record attributes; redact any
        # string-valued ones without disturbing the standard LogRecord fields.
        for key, value in list(record.__dict__.items()):
            if key not in self._STD_ATTRS and isinstance(value, str):
                record.__dict__[key] = self._redact(value)
        return True

    def _redact(self, text: str) -> str:
        for pattern, replacement in self._PATTERNS:
            text = pattern.sub(replacement, text)
        return text
