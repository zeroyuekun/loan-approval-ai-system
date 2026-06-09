"""Tests for config.logging_filters.PiiMaskingFilter (review #5 + #19).

#5: the phone pattern only matched an unbroken digit run, so the common AU
spaced/dashed forms (the way CustomerProfile.phone actually stores numbers)
leaked into logs unredacted, and an unbroken number was mislabelled MEDICARE.
#19: the filter scrubbed record.msg/args but not structured-logging `extra={}`
fields, so any future extra carrying PII bypassed redaction.
"""

from __future__ import annotations

import logging

from config.logging_filters import PiiMaskingFilter


def _redact(text: str) -> str:
    return PiiMaskingFilter()._redact(text)


class TestPhoneRedaction:
    def test_spaced_mobile_is_redacted(self):
        out = _redact("call 0412 345 678 today")
        assert "[PHONE_REDACTED]" in out
        assert "0412 345 678" not in out

    def test_dashed_mobile_is_redacted(self):
        out = _redact("ph 0412-345-678")
        assert "[PHONE_REDACTED]" in out
        assert "0412-345-678" not in out

    def test_parenthesised_landline_is_redacted(self):
        out = _redact("office (02) 9876 5432")
        assert "[PHONE_REDACTED]" in out

    def test_plus61_international_is_redacted(self):
        assert "[PHONE_REDACTED]" in _redact("intl +61 412 345 678")

    def test_unbroken_mobile_is_phone_not_medicare(self):
        # Phone runs before the generic Medicare matcher, so an unbroken mobile
        # is labelled PHONE rather than mislabelled MEDICARE.
        out = _redact("mobile 0412345678")
        assert "[PHONE_REDACTED]" in out
        assert "0412345678" not in out
        assert "MEDICARE" not in out

    def test_real_tfn_not_stolen_by_phone(self):
        # A 9-digit TFN does not start with 0/+61, so phone leaves it for the TFN
        # matcher rather than swallowing it.
        out = _redact("tfn 123 456 789")
        assert "[TFN_REDACTED]" in out


class TestExtrasRedaction:
    def test_string_extra_field_is_redacted(self):
        record = logging.LogRecord("svc", logging.INFO, "/p", 1, "decision logged", None, None)
        record.applicant_phone = "0412 345 678"  # simulates extra={"applicant_phone": ...}
        PiiMaskingFilter().filter(record)
        assert record.applicant_phone == _redact("0412 345 678")
        assert "[PHONE_REDACTED]" in record.applicant_phone

    def test_standard_attributes_are_not_touched(self):
        record = logging.LogRecord("mymod", logging.INFO, "/p", 1, "hello", None, None)
        PiiMaskingFilter().filter(record)
        assert record.name == "mymod"
        assert record.levelname == "INFO"


def test_email_still_redacted():
    assert "[EMAIL_REDACTED]" in _redact("contact applicant@example.com")


def test_numeric_log_args_are_not_corrupted():
    # The filter must NOT coerce numeric args to strings — doing so makes a
    # "%d"/"%f" format string raise TypeError at emit time. (Regression guard for
    # the dev-logging wiring that surfaced this; PII only appears in string args.)
    record = logging.LogRecord("svc", logging.INFO, "/p", 1, "Excluded %d weak features (IV < %.2f)", (19, 0.02), None)
    PiiMaskingFilter().filter(record)
    assert record.getMessage() == "Excluded 19 weak features (IV < 0.02)"


def test_string_args_are_still_redacted():
    record = logging.LogRecord("svc", logging.INFO, "/p", 1, "applicant %s", ("0412 345 678",), None)
    PiiMaskingFilter().filter(record)
    assert "[PHONE_REDACTED]" in record.getMessage()
