"""Unit tests for email html_renderer."""

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


def test_approval_renders_success_hero():
    body = _load_fixture("approval_01_personal")
    html = render_html(body, email_type="approval")
    assert f"background-color:{TOKENS['SUCCESS']}" in html
    assert "&#10003;" in html
    assert "Congratulations" in html


def test_denial_renders_caution_hero():
    body = "Dear John,\n\nWe reviewed your application.\n"
    html = render_html(body, email_type="denial")
    assert f"background-color:{TOKENS['CAUTION']}" in html
    assert "&#9432;" in html


def test_marketing_renders_marketing_hero():
    body = "Dear John,\n\nHere are some options.\n"
    html = render_html(body, email_type="marketing")
    assert f"background-color:{TOKENS['MARKETING']}" in html
    assert "&#10022;" in html


def test_hero_extracts_first_name_from_greeting():
    body = "Dear Priya,\n\nApplication approved.\n"
    html = render_html(body, email_type="approval")
    assert "Congratulations, Priya!" in html


def test_hero_approval_extracts_loan_type():
    body = "Dear Emma,\n\nWe are pleased to advise that your application for a Home Loan has been approved.\n"
    html = render_html(body, email_type="approval")
    assert "Your Home Loan Is Approved" in html


def test_approval_loan_details_renders_as_card():
    body = _load_fixture("approval_01_personal")
    html = render_html(body, email_type="approval")
    assert f"border-left:4px solid {TOKENS['SUCCESS']}" in html
    assert "LOAN DETAILS" in html.upper()
    assert "$25,000.00" in html
    assert "6.50% p.a." in html


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
    "marketing_01_three_options",
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
