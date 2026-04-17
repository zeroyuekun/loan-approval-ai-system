"""Unified plain-text → Gmail-safe HTML renderer for decision + marketing emails.

Single source of truth for all three email types. Design tokens (colors, type
scale, spacing) live here and mirror verbatim in frontend/src/lib/emailHtmlRenderer.ts.
A CI snapshot parity test fails if the two drift.

See: docs/superpowers/specs/2026-04-17-email-redesign-design.md
"""
from typing import Literal

EmailType = Literal["approval", "denial", "marketing"]

TOKENS: dict[str, str] = {
    "BRAND_PRIMARY": "#1e40af",
    "BRAND_ACCENT": "#3b82f6",
    "SUCCESS": "#16a34a",
    "CAUTION": "#d97706",
    "MARKETING": "#7c3aed",
    "TEXT": "#111827",
    "MUTED": "#6b7280",
    "FINE": "#9ca3af",
    "CARD_BG": "#f8fafc",
    "BORDER": "#e5e7eb",
    "PAGE_BG": "#f3f4f6",
    "FONT_STACK": "system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif",
    "BODY_SIZE": "15px",
    "HEAD_SIZE": "22px",
    "LABEL_SIZE": "13px",
    "FINE_SIZE": "12px",
    "LINE_HEIGHT": "1.6",
    "MAX_WIDTH": "600px",
}


def render_html(plain_body: str, email_type: EmailType) -> str:
    """Convert plain-text email body into Gmail-safe HTML.

    Args:
        plain_body: Raw plain-text email as produced by Claude/template fallback.
        email_type: One of "approval", "denial", "marketing".

    Returns:
        Gmail-safe HTML string with inline styles. Ready to pass to
        Django's send_mail(html_message=...).
    """
    # PR 1 stub — real implementation in later steps.
    return f'<table role="presentation"><tr><td>{plain_body}</td></tr></table>'
