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
        # Australian Tax File Number (XXX XXX XXX)
        (re.compile(r'\b\d{3}\s?\d{3}\s?\d{3}\b'), '[TFN_REDACTED]'),
        # Medicare number (XXXX XXXXX X)
        (re.compile(r'\b\d{4}\s?\d{5}\s?\d\b'), '[MEDICARE_REDACTED]'),
        # Email addresses
        (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), '[EMAIL_REDACTED]'),
        # Phone numbers (Australian: 04XX XXX XXX, 1300/1800, +61)
        (re.compile(r'(?:\+61|0)[2-478]\d{8}'), '[PHONE_REDACTED]'),
        # Dollar amounts following sensitive keywords
        (re.compile(r'(?:income|salary|wage|earning)[=:\s"\']+\$?[\d,.]+', re.IGNORECASE), '[INCOME_REDACTED]'),
        # Generic ID number patterns after identity keywords
        (re.compile(r'(?:passport|licence|license|driver)[=:\s"\']+[A-Z0-9]{6,12}', re.IGNORECASE), '[ID_REDACTED]'),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(str(record.msg))
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._redact(str(v)) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._redact(str(a)) for a in record.args)
        return True

    def _redact(self, text: str) -> str:
        for pattern, replacement in self._PATTERNS:
            text = pattern.sub(replacement, text)
        return text
