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


class TestContainer:
    def test_container_uses_table_with_600px_width(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        assert "<table" in html
        assert "width:600px" in html.replace(" ", "")
        assert "max-width:100%" in html.replace(" ", "")

    def test_branded_header_contains_app_name(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        assert "Aussie Loan AI" in html

    def test_header_accent_bar_matches_email_type(self):
        html = _plain_text_to_html(DENIAL_PLAIN, email_type="denial")
        compact = html.replace(" ", "")
        assert "background-color:#374151" in compact or "background:#374151" in compact

    def test_html_uses_inline_styles_only(self):
        """Gmail strips <style> blocks — verify we never emit one."""
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        assert "<style" not in html
        assert "</style>" not in html


class TestSectionHeaders:
    def test_section_labels_have_accent_underline(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        assert "Loan Details" in html
        assert "border-bottom:2pxsolid#16a34a" in html.replace(" ", "")

    def test_section_headers_are_18px_bold(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        assert "font-size:18px" in html.replace(" ", "")
        assert "font-weight:bold" in html.replace(" ", "")

    def test_options_are_treated_as_section_headers(self):
        html = _plain_text_to_html(MARKETING_PLAIN, email_type="marketing")
        assert "Option 1: Secured Personal Loan" in html
        assert "border-bottom:2pxsolid#7c3aed" in html.replace(" ", "")


class TestBulletLists:
    def test_consecutive_bullets_collapse_into_single_ul(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        assert html.count("<ul") >= 1
        assert html.count("<li") >= 3

    def test_bullets_use_semantic_li(self):
        html = _plain_text_to_html(DENIAL_PLAIN, email_type="denial")
        assert "<li" in html
        assert "\u2022&nbsp;&nbsp;" not in html

    def test_bullet_items_are_16px(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        assert "font-size:16px" in html.replace(" ", "")


class TestNumberedLists:
    def test_consecutive_numbered_items_collapse_into_single_ol(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        assert html.count("<ol") >= 1
        assert '<p style="margin:2px 0 2px 16px;">1.' not in html

    def test_numbered_list_preserves_order(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        assert html.index("Bank statements") < html.index("Photo ID")
        assert html.index("Photo ID") < html.index("Signed loan contract")


class TestDetailsCard:
    def test_detail_rows_render_inside_card(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        assert "#f9fafb" in html.lower()
        assert "$35,000.00" in html
        assert "8.95% p.a." in html

    def test_label_is_grey_value_is_bold_dark(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        compact = html.replace(" ", "")
        assert "font-size:13px" in compact
        assert "font-size:15px" in compact

    def test_marketing_each_option_gets_its_own_card(self):
        html = _plain_text_to_html(MARKETING_PLAIN, email_type="marketing")
        assert html.count("#f9fafb") >= 2


class TestCTAButton:
    def test_approval_has_review_and_sign_cta(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        assert "Review &amp; Sign" in html or "Review & Sign" in html
        assert "background:#16a34a" in html.replace(" ", "")

    def test_denial_has_explore_options_cta(self):
        html = _plain_text_to_html(DENIAL_PLAIN, email_type="denial")
        assert "Explore Options" in html

    def test_marketing_has_see_alternatives_cta(self):
        html = _plain_text_to_html(MARKETING_PLAIN, email_type="marketing")
        assert "See Alternatives" in html

    def test_cta_is_a_link(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        assert "<a " in html
        assert "text-decoration:none" in html.replace(" ", "")


class TestComplianceFooter:
    def test_denial_has_afca_footer(self):
        html = _plain_text_to_html(DENIAL_PLAIN, email_type="denial")
        assert "AFCA" in html
        assert "1800 931 678" in html
        assert "afca.org.au" in html

    def test_approval_has_no_afca_footer(self):
        html = _plain_text_to_html(APPROVAL_PLAIN, email_type="approval")
        assert "AFCA" not in html
        assert "1800 931 678" not in html

    def test_marketing_has_no_afca_footer(self):
        html = _plain_text_to_html(MARKETING_PLAIN, email_type="marketing")
        assert "AFCA" not in html
        assert "1800 931 678" not in html

    def test_afca_footer_is_separated_from_main_signature(self):
        html = _plain_text_to_html(DENIAL_PLAIN, email_type="denial")
        email_idx = html.find("Email:")
        afca_idx = html.find("AFCA")
        assert email_idx != -1 and afca_idx != -1
        assert afca_idx > email_idx
