"""Tests for _plain_text_to_html HTML rendering.

Covers the three email types (approval, denial, marketing) and validates
that generated HTML is Gmail-compatible (inline styles only, table layout,
600px container).
"""
from unittest.mock import patch

import pytest

from apps.email_engine.services.sender import _plain_text_to_html, send_decision_email


# Representative approval plain-text body (matches template_fallback output)
APPROVAL_PLAIN = """Dear Sarah,

Congratulations! Your loan application has been approved.

Loan Details:

  Loan Amount:            $35,000.00
  Interest Rate:          8.95% p.a.
  Term:                   5 years
  Monthly Repayment:      $724.18

Next Steps:

\u2022  Review the attached loan contract
\u2022  Sign and return within 7 days
\u2022  Funds disbursed within 2 business days

Required Documentation:

  1. Bank statements (last 3 months)
  2. Photo ID
  3. Signed loan contract

Attachments:

  1. Loan Contract.pdf
  2. Key Facts Sheet.pdf
  3. Credit Guide.pdf

Kind regards,

Sarah Mitchell
Senior Lending Officer

ABN 12 345 678 901
Phone: 1300 LOAN AI
Email: decisions@aussieloanai.com.au
"""


# Representative denial body
DENIAL_PLAIN = """Dear Sarah,

Thank you for your loan application. After careful review, we are unable to approve your application at this time.

This decision was based on a thorough review of your financial profile, specifically:

\u2022  Credit score below our current threshold
\u2022  Debt-to-income ratio exceeds our lending criteria
\u2022  Employment tenure shorter than required

What You Can Do:

\u2022  Request your credit file from Equifax or illion (free once per year)
\u2022  Pay down existing debts to improve DTI
\u2022  Reapply after 12 months of stable employment

Kind regards,

Sarah Mitchell
Senior Lending Officer

ABN 12 345 678 901
Phone: 1300 LOAN AI
Email: decisions@aussieloanai.com.au
"""


# Representative marketing body
MARKETING_PLAIN = """Dear Sarah,

While your recent loan application wasn't approved, we have some alternative options that may suit your situation better.

Option 1: Secured Personal Loan

  Amount:                 $15,000.00
  Interest Rate:          9.95% p.a.
  Term:                   3 years
  Monthly Repayment:      $483.67

A secured personal loan may be a more suitable path given your current profile.

Option 2: Debt Consolidation

  Amount:                 $20,000.00
  Interest Rate:          11.50% p.a.
  Term:                   5 years
  Monthly Repayment:      $440.21

Consolidating existing debts into a single repayment could simplify your finances.

Kind regards,

Sarah Mitchell
Senior Lending Officer

ABN 12 345 678 901
Phone: 1300 LOAN AI
Email: alternatives@aussieloanai.com.au
"""


class TestAccentColors:
    def test_approval_html_contains_green_accent(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        assert "#16a34a" in html

    def test_denial_html_contains_slate_accent(self):
        html = _plain_text_to_html(DENIAL_PLAIN, email_type="denial")
        assert "#374151" in html

    def test_marketing_html_contains_purple_accent(self):
        html = _plain_text_to_html(MARKETING_PLAIN, email_type="marketing")
        assert "#7c3aed" in html

    def test_denial_html_has_no_red_tone(self):
        """Denial must not use harsh/alarming colors per tone preference."""
        html = _plain_text_to_html(DENIAL_PLAIN, email_type="denial")
        assert "#dc2626" not in html
        assert "#ef4444" not in html
        assert "#f87171" not in html

    def test_unknown_email_type_defaults_to_approval_accent(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="anything_else")
        assert "#16a34a" in html
