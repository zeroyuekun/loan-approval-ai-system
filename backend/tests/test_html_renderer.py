"""Unit tests for email html_renderer."""
from apps.email_engine.services.html_renderer import TOKENS, render_html


def test_tokens_has_required_keys():
    required = {
        "BRAND_PRIMARY", "BRAND_ACCENT", "SUCCESS", "CAUTION", "MARKETING",
        "TEXT", "MUTED", "FINE", "CARD_BG", "BORDER", "PAGE_BG",
        "FONT_STACK", "BODY_SIZE", "HEAD_SIZE", "LABEL_SIZE", "FINE_SIZE",
        "LINE_HEIGHT", "MAX_WIDTH",
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
