"""Unit tests for email html_renderer."""

import re
from pathlib import Path

import pytest

from apps.email_engine.services.html_renderer import TOKENS, render_html

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "email_bodies"
SNAPSHOT_DIR = Path(__file__).parent / "fixtures" / "email_snapshots"


def _type_for_fixture(name: str) -> str:
    if name.startswith("approval"):
        return "approval"
    if name.startswith("denial"):
        return "denial"
    return "marketing"


def _load_fixture(stem: str) -> str:
    return (FIXTURE_DIR / f"{stem}.txt").read_text(encoding="utf-8")


def _snapshot_path(stem: str) -> Path:
    return SNAPSHOT_DIR / f"{stem}.html"


def test_tokens_has_required_keys():
    required = {
        "BRAND_PRIMARY",
        "BRAND_ACCENT",
        "SUCCESS",
        "CAUTION",
        "MARKETING",
        "TEXT",
        "MUTED",
        "FINE",
        "CARD_BG",
        "BORDER",
        "PAGE_BG",
        "FONT_STACK",
        "BODY_SIZE",
        "HEAD_SIZE",
        "LABEL_SIZE",
        "FINE_SIZE",
        "LINE_HEIGHT",
        "MAX_WIDTH",
    }
    assert required <= set(TOKENS.keys())


def test_tokens_brand_colors_match_spec():
    assert TOKENS["BRAND_PRIMARY"] == "#1e40af"
    assert TOKENS["BRAND_ACCENT"] == "#3b82f6"
    assert TOKENS["SUCCESS"] == "#16a34a"
    assert TOKENS["CAUTION"] == "#d97706"
    assert TOKENS["MARKETING"] == "#7c3aed"


def test_render_html_returns_string():
    result = render_html("Dear John,\n\nHello.", email_type="approval")
    assert isinstance(result, str)
    assert result.startswith("<!DOCTYPE") or result.startswith("<table") or result.startswith("<html")


def test_legacy_body_parser_detects_section_labels():
    from apps.email_engine.services.html_renderer import _render_legacy_body

    body = "Dear John,\n\nLoan Details:\n\n  Loan Amount:   $50,000.00"
    out = _render_legacy_body(body)
    assert "<strong>Loan Details:</strong>" in out
    assert "$50,000.00" in out


def test_legacy_body_parser_detects_loan_detail_rows():
    from apps.email_engine.services.html_renderer import _render_legacy_body

    body = "  Loan Amount:             $25,000.00\n  Interest Rate:           6.50% p.a."
    out = _render_legacy_body(body)
    assert "<table" in out
    assert "$25,000.00" in out
    assert "6.50% p.a." in out


def test_skeleton_wraps_body_with_brand_header():
    result = render_html("Dear John,\n\nHello.", email_type="approval")
    assert TOKENS["BRAND_PRIMARY"] in result
    assert "AussieLoanAI" in result
    assert "Australian Credit Licence No. 012345" in result


def test_skeleton_uses_600px_max_width():
    result = render_html("Dear John,", email_type="approval")
    assert "max-width:600px" in result


def test_skeleton_wraps_in_outer_page_bg():
    result = render_html("Dear John,", email_type="approval")
    assert TOKENS["PAGE_BG"] in result


def test_skeleton_has_role_presentation_tables():
    result = render_html("Dear John,", email_type="approval")
    assert 'role="presentation"' in result


def test_render_html_includes_legacy_body():
    result = render_html("Dear John,\n\nHello.", email_type="approval")
    assert "Dear John," in result
    assert "Hello." in result


def test_approval_hero_is_iconless():
    body = _load_fixture("approval_01_personal")
    html = render_html(body, email_type="approval")
    assert "&#10003;" not in html
    assert 'width:48px; height:48px; border-radius:24px' not in html
    assert "Congratulations" in html


def test_denial_hero_is_iconless():
    body = "Dear John,\n\nWe reviewed your application.\n"
    html = render_html(body, email_type="denial")
    assert "&#9432;" not in html
    assert 'width:48px; height:48px; border-radius:24px' not in html
    assert "Update on Your Application" in html


def test_marketing_hero_is_iconless():
    body = "Dear John,\n\nHere are some options.\n"
    html = render_html(body, email_type="marketing")
    assert "&#10022;" not in html
    assert 'width:48px; height:48px; border-radius:24px' not in html
    assert "A Few Options for You" in html


def test_hero_extracts_first_name_from_greeting():
    body = "Dear Priya,\n\nApplication approved.\n"
    html = render_html(body, email_type="approval")
    assert "Congratulations, Priya!" in html


def test_hero_approval_extracts_loan_type():
    body = "Dear Emma,\n\nWe are pleased to advise that your application for a Home Loan has been approved.\n"
    html = render_html(body, email_type="approval")
    assert "Your Home Loan Is Approved" in html


def test_hero_approval_extracts_multi_word_loan_type():
    # APPROVAL_LOAN_TYPE_RE was widened to capture multi-word product names like
    # "Home Improvement Loan" and "Investment Property Loan" — single-word
    # capture would otherwise truncate to "Improvement Loan" / "Property Loan".
    body = (
        "Dear Aiyana,\n\nWe are pleased to advise that your application for a "
        "Home Improvement Loan has been approved.\n"
    )
    html = render_html(body, email_type="approval")
    assert "Your Home Improvement Loan Is Approved" in html


def test_hero_approval_extracts_three_word_loan_type():
    body = (
        "Dear Aiyana,\n\nWe are pleased to advise that your application for an "
        "Investment Property Loan has been approved.\n"
    )
    html = render_html(body, email_type="approval")
    assert "Your Investment Property Loan Is Approved" in html


def test_approval_loan_details_renders_as_card():
    body = _load_fixture("approval_01_personal")
    html = render_html(body, email_type="approval")
    assert f"border-left:4px solid {TOKENS['SUCCESS']}" in html
    assert "LOAN DETAILS" in html.upper()
    assert "$25,000.00" in html
    assert "6.50% p.a." in html


def test_approval_next_steps_renders_numbered_pills():
    body = _load_fixture("approval_01_personal")
    html = render_html(body, email_type="approval")
    assert "border-radius:12px" in html
    assert f"background-color:{TOKENS['BRAND_PRIMARY']}" in html
    assert "Sign and return your documents by 22 April 2026." in html


def test_approval_has_cta_button():
    body = _load_fixture("approval_01_personal")
    html = render_html(body, email_type="approval")
    assert "Review &amp; Sign Documents" in html
    assert f"background-color:{TOKENS['BRAND_ACCENT']}" in html


def test_approval_signature_has_divider():
    body = _load_fixture("approval_01_personal")
    html = render_html(body, email_type="approval")
    assert f"border-top:1px solid {TOKENS['BORDER']}" in html
    assert "Sarah Mitchell" in html
    assert "Senior Lending Officer" in html


def test_approval_attachments_chips_rendered():
    body = _load_fixture("approval_01_personal")
    html = render_html(body, email_type="approval")
    assert "ATTACHMENTS" in html.upper()
    assert "&#128206;" in html  # paperclip
    assert "Loan Contract.pdf" in html


def test_denial_assessment_factors_card():
    body = _load_fixture("denial_01_serviceability")
    html = render_html(body, email_type="denial")
    assert f"border-left:4px solid {TOKENS['CAUTION']}" in html
    assert "ASSESSMENT FACTORS" in html.upper()
    assert "Debt-to-income ratio" in html


def test_denial_what_you_can_do_card():
    body = _load_fixture("denial_01_serviceability")
    html = render_html(body, email_type="denial")
    assert f"border-left:4px solid {TOKENS['SUCCESS']}" in html
    assert "WHAT YOU CAN DO" in html.upper()
    assert "Reduce outstanding debts" in html


def test_denial_credit_report_card():
    body = _load_fixture("denial_01_serviceability")
    html = render_html(body, email_type="denial")
    assert "FREE CREDIT REPORT" in html.upper()
    assert f"border-left:4px solid {TOKENS['BRAND_ACCENT']}" in html
    assert "equifax.com.au" in html


def test_denial_dual_cta():
    body = _load_fixture("denial_01_serviceability")
    html = render_html(body, email_type="denial")
    assert 'href="tel:' in html
    assert "Call Sarah" in html
    assert "mailto:" in html


def test_marketing_offer_cards():
    body = _load_fixture("marketing_01_three_options")
    html = render_html(body, email_type="marketing")
    assert f"border-left:4px solid {TOKENS['MARKETING']}" in html
    assert "OPTION 1" in html.upper()
    assert "OPTION 2" in html.upper()
    assert "OPTION 3" in html.upper()
    assert "Smaller Personal Loan" in html
    assert "Secured Car Loan" in html


def test_marketing_unsubscribe_mandatory():
    body = _load_fixture("marketing_01_three_options")
    html = render_html(body, email_type="marketing")
    assert "Unsubscribe" in html
    assert 'href="https://aussieloanai.com.au/unsubscribe' in html


def test_marketing_term_deposit_fcs_disclaimer():
    body = _load_fixture("marketing_04_term_deposit")
    html = render_html(body, email_type="marketing")
    assert "Financial Claims Scheme" in html or "FCS" in html


def test_marketing_bonus_rate_disclaimer():
    body = _load_fixture("marketing_05_bonus_rate")
    html = render_html(body, email_type="marketing")
    assert "Bonus rates apply" in html or "bonus rate" in html.lower()


def test_marketing_single_option_does_not_over_render():
    body = _load_fixture("marketing_03_single_option")
    html = render_html(body, email_type="marketing")
    assert "OPTION 1" in html.upper()
    assert "OPTION 2" not in html.upper()


def test_marketing_call_cta_uses_marketing_color():
    body = _load_fixture("marketing_01_three_options")
    html = render_html(body, email_type="marketing")
    assert 'href="tel:1300000000"' in html
    assert "Call Sarah" in html


def test_sender_uses_new_renderer():
    """sender.py must import render_html from html_renderer, not define its own."""
    from apps.email_engine.services import sender as sender_mod

    assert not hasattr(sender_mod, "_plain_text_to_html"), (
        "sender.py should no longer define _plain_text_to_html — must import render_html from html_renderer instead."
    )


ALL_FIXTURE_STEMS = [
    "approval_01_personal",
    "approval_02_home_loan",
    "approval_03_with_cosigner",
    "approval_04_conditional",
    "approval_05_auto_loan",
    "denial_01_serviceability",
    "denial_02_credit_score",
    "denial_03_employment",
    "denial_04_multiple_factors",
    "denial_05_policy",
    "denial_06_live_shape",
    "marketing_01_three_options",
    "marketing_02_two_options",
    "marketing_03_single_option",
    "marketing_04_term_deposit",
    "marketing_05_bonus_rate",
]


@pytest.mark.parametrize("stem", ALL_FIXTURE_STEMS)
def test_snapshot_matches(stem):
    body = _load_fixture(stem)
    actual = render_html(body, email_type=_type_for_fixture(stem))
    snapshot = _snapshot_path(stem)
    if not snapshot.exists():
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes(actual.encode("utf-8"))
        pytest.skip(f"Wrote new snapshot {snapshot.name} — re-run to assert.")
    expected = snapshot.read_bytes().decode("utf-8")
    assert actual == expected, f"Snapshot drift in {stem}. Delete {snapshot} and re-run to accept the new output."


def test_no_flexbox_or_grid():
    for stem in ALL_FIXTURE_STEMS:
        body = _load_fixture(stem)
        html = render_html(body, email_type=_type_for_fixture(stem))
        for forbidden in ["display:flex", "display: flex", "display:grid", "display: grid", "display:inline-flex"]:
            assert forbidden not in html, f"{stem}: forbidden `{forbidden}` in output"


def test_no_style_tag():
    for stem in ALL_FIXTURE_STEMS:
        body = _load_fixture(stem)
        html = render_html(body, email_type=_type_for_fixture(stem))
        assert "<style" not in html.lower(), f"{stem}: found <style> tag (Gmail strips these)"


def test_size_under_102kb():
    for stem in ALL_FIXTURE_STEMS:
        body = _load_fixture(stem)
        html = render_html(body, email_type=_type_for_fixture(stem))
        size_kb = len(html.encode("utf-8")) / 1024
        assert size_kb < 102, f"{stem}: {size_kb:.1f} KB — Gmail clips at 102 KB"


def test_inner_max_width_600():
    html = render_html("Dear John,", email_type="approval")
    assert "max-width:600px" in html


# ----------------------------------------------------------------------------
# Gmail-safe lint hardening (PR 6 Task 6.3)
# ----------------------------------------------------------------------------


def test_no_margin_on_td():
    """Gmail ignores `margin` on `<td>`. Padding only."""
    for stem in ALL_FIXTURE_STEMS:
        body = _load_fixture(stem)
        html = render_html(body, email_type=_type_for_fixture(stem))
        assert not re.search(r'<td[^>]*style="[^"]*margin', html), (
            f"{stem}: found margin on <td>. Gmail ignores this — use padding."
        )


def test_all_urls_https_or_tel_or_mailto():
    """Every href must be a safe scheme (https/tel/mailto/anchor)."""
    for stem in ALL_FIXTURE_STEMS:
        body = _load_fixture(stem)
        html = render_html(body, email_type=_type_for_fixture(stem))
        for m in re.finditer(r'href="([^"]+)"', html):
            url = m.group(1)
            assert url.startswith(("https://", "tel:", "mailto:", "#")), (
                f"{stem}: href {url!r} must be https, tel, mailto, or anchor"
            )


def test_no_image_tags():
    """Brand is CSS + unicode — no <img> can fail to load."""
    for stem in ALL_FIXTURE_STEMS:
        body = _load_fixture(stem)
        html = render_html(body, email_type=_type_for_fixture(stem))
        assert "<img" not in html.lower(), f"{stem}: found <img> — brand is CSS-only"


def test_cta_anchors_have_inline_white_color():
    """Dark-mode readability: CTA buttons must have inline white color on <a>."""
    # Approval CTA: Review & Sign
    body = _load_fixture("approval_01_personal")
    html = render_html(body, email_type="approval")
    # Find the anchor wrapping "Review & Sign Documents" text
    assert re.search(r"<a\s[^>]*color:#ffffff[^>]*>Review &amp; Sign Documents</a>", html), (
        "Approval CTA anchor missing inline color:#ffffff"
    )

    # Marketing CTA: Call Sarah on …
    body = _load_fixture("marketing_01_three_options")
    html = render_html(body, email_type="marketing")
    assert re.search(r"<a\s[^>]*color:#ffffff[^>]*>Call Sarah on 1300 000 000</a>", html), (
        "Marketing CTA anchor missing inline color:#ffffff"
    )


def test_no_javascript_urls():
    """No javascript: or data: URIs — security hardening."""
    for stem in ALL_FIXTURE_STEMS:
        body = _load_fixture(stem)
        html = render_html(body, email_type=_type_for_fixture(stem))
        assert "javascript:" not in html.lower(), f"{stem}: javascript: scheme found"
        assert "data:" not in html.lower(), f"{stem}: data: URI found"


def test_outlook_conditional_comments_absent():
    """No Outlook conditional comments — we don't target Outlook-specific rendering."""
    for stem in ALL_FIXTURE_STEMS:
        body = _load_fixture(stem)
        html = render_html(body, email_type=_type_for_fixture(stem))
        assert "<!--[if" not in html, f"{stem}: found Outlook conditional comment"


def test_tables_have_role_presentation():
    """All content <table> must have role=presentation for screen readers."""
    for stem in ["approval_01_personal", "denial_01_serviceability", "marketing_01_three_options"]:
        body = _load_fixture(stem)
        html = render_html(body, email_type=_type_for_fixture(stem))
        # Count <table ...> occurrences
        table_count = len(re.findall(r"<table\b", html))
        role_count = len(re.findall(r'<table[^>]*role="presentation"', html))
        assert role_count == table_count, (
            f"{stem}: {table_count - role_count} of {table_count} <table> tags missing role=presentation"
        )


# ----------------------------------------------------------------------------
# HTML escape parity with frontend/src/lib/emailHtmlRenderer.ts
# ----------------------------------------------------------------------------

_XSS_BODY = (
    'Dear <script>alert("x\'s")</script>,\n\n'
    "Congratulations! Your Personal Loan has been approved.\n\n"
    "Loan Details:\n"
    "- Loan Type: <img src=x onerror=alert(1)>\n"
    "- Amount: $15,000\n"
    "- Term: 3 years\n"
    "- Interest Rate: 12.5% p.a.\n\n"
    "We're Here For You:\n"
    'Reach us at "support@aussieloanai.com".\n\n'
    "Kind regards,\n"
    'The AussieLoanAI "Team"\n'
)

_XSS_DENIAL_BODY = (
    "Dear <b>attacker</b>,\n\n"
    "Unfortunately we are unable to approve your application at this time.\n\n"
    "Factors:\n"
    "Serviceability: debt-to-income exceeds <script>alert(1)</script> policy\n"
    "Credit: score below our O'Brien benchmark\n\n"
    "What you can do:\n"
    '- Visit "https://example.com/help" for guidance\n'
    "- Reapply after 3 months\n"
)


@pytest.mark.parametrize(
    "body,email_type",
    [
        (_XSS_BODY, "approval"),
        (_XSS_DENIAL_BODY, "denial"),
    ],
)
def test_escapes_untrusted_markup_in_body(body, email_type):
    """Injected <script>, <img>, and attribute-breaking chars must be HTML-escaped."""
    out = render_html(body, email_type=email_type)
    assert "<script>" not in out, f"{email_type}: raw <script> tag survived escaping"
    assert "<img src=x" not in out, f"{email_type}: raw <img> tag survived escaping"
    assert "&lt;script&gt;" in out, f"{email_type}: expected &lt;script&gt; entity"
    assert "&quot;" in out, f'{email_type}: expected &quot; entity for injected "'
    assert "&#x27;" in out, f"{email_type}: expected &#x27; entity for injected '"


def test_escapes_ampersand_without_double_escaping():
    """An injected `&` becomes `&amp;`, and an injected `&amp;` becomes `&amp;amp;`."""
    body = (
        "Dear Jane & Co,\n\n"
        "Your loan is approved.\n\n"
        "Loan Details:\n"
        "- Loan Type: Personal & Household\n"
        "- Amount: $10,000\n\n"
        "Regards,\n"
        "Team\n"
    )
    out = render_html(body, email_type="approval")
    assert "Jane &amp; Co" in out
    assert "Personal &amp; Household" in out
    assert "Jane & Co" not in out  # ensure raw & was escaped in output


def test_escape_helper_matches_ts_five_char_contract():
    """_e() must escape exactly the five chars that escapeHtml() in the TS renderer escapes.

    If this contract drifts, the snapshot parity test in
    frontend/src/__tests__/lib/emailHtmlRenderer.test.ts will fail on the next run.
    """
    from apps.email_engine.services.html_renderer import _e

    assert _e("&") == "&amp;"
    assert _e("<") == "&lt;"
    assert _e(">") == "&gt;"
    assert _e('"') == "&quot;"
    assert _e("'") == "&#x27;"
    assert _e("plain text") == "plain text"
    assert _e("a&b<c>d\"e'f") == "a&amp;b&lt;c&gt;d&quot;e&#x27;f"


def test_safe_url_accepts_allowed_schemes():
    from apps.email_engine.services.html_renderer import _safe_url

    assert _safe_url("https://example.com/path") == "https://example.com/path"
    assert _safe_url("http://example.com") == "http://example.com"
    assert _safe_url("mailto:user@example.com") == "mailto:user@example.com"
    assert _safe_url("tel:1300000000") == "tel:1300000000"


def test_safe_url_accepts_case_insensitive_schemes():
    from apps.email_engine.services.html_renderer import _safe_url

    assert _safe_url("HTTPS://example.com") == "HTTPS://example.com"
    assert _safe_url("HttP://example.com") == "HttP://example.com"


def test_safe_url_strips_surrounding_whitespace():
    from apps.email_engine.services.html_renderer import _safe_url

    assert _safe_url("  https://example.com  ") == "https://example.com"


def test_safe_url_rejects_javascript_scheme():
    from apps.email_engine.services.html_renderer import SAFE_URL_FALLBACK, _safe_url

    assert _safe_url("javascript:alert(1)") == SAFE_URL_FALLBACK
    assert _safe_url("JaVaScRiPt:alert(1)") == SAFE_URL_FALLBACK
    assert _safe_url(" javascript:alert(1)") == SAFE_URL_FALLBACK


def test_safe_url_rejects_other_dangerous_schemes():
    from apps.email_engine.services.html_renderer import SAFE_URL_FALLBACK, _safe_url

    assert _safe_url("data:text/html,<script>alert(1)</script>") == SAFE_URL_FALLBACK
    assert _safe_url("vbscript:msgbox(1)") == SAFE_URL_FALLBACK
    assert _safe_url("file:///etc/passwd") == SAFE_URL_FALLBACK


def test_safe_url_rejects_schemeless_or_garbage_input():
    from apps.email_engine.services.html_renderer import SAFE_URL_FALLBACK, _safe_url

    assert _safe_url("") == SAFE_URL_FALLBACK
    assert _safe_url("not a url") == SAFE_URL_FALLBACK
    assert _safe_url("//example.com/path") == SAFE_URL_FALLBACK
    # Non-string input must not explode (defensive guard for LLM-parsed bodies)
    assert _safe_url(None) == SAFE_URL_FALLBACK  # type: ignore[arg-type]


def test_marketing_footer_sanitizes_llm_injected_javascript_url():
    """End-to-end: malicious unsubscribe URL in LLM-rendered body must not reach the href."""
    body = (
        "Dear Customer,\n\nSpecial term deposit offer.\n\n"
        "Sarah\n\nABN 00 000 000 000\n"
        "Unsubscribe: javascript:alert('xss')"
    )
    out = render_html(body, email_type="marketing")
    # The scheme must never appear inside an href — it's fine if it remains in
    # body text (it's escaped and harmless there).
    hrefs = re.findall(r'href\s*=\s*"([^"]*)"', out)
    for href in hrefs:
        assert not href.lower().startswith("javascript:"), f"Unsafe href: {href}"
    assert 'href="https://aussieloanai.com.au/unsubscribe"' in out


def test_marketing_footer_preserves_legitimate_unsubscribe_url():
    body = (
        "Dear Customer,\n\nSpecial offer.\n\n"
        "Sarah\n\nABN 00 000 000 000\n"
        "Unsubscribe: https://aussieloanai.com.au/unsubscribe?u=abc123"
    )
    out = render_html(body, email_type="marketing")
    assert "https://aussieloanai.com.au/unsubscribe?u=abc123" in out
