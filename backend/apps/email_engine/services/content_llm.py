"""Which LLM, if any, may word customer-facing copy.

Decision emails, offer reasoning and the marketing follow-up are all text a
customer reads, so one setting governs them: ``EMAIL_LLM_BACKEND``.

* ``template`` (default): no model writes customer text; every caller uses its
  deterministic template.
* ``ollama``: a local model on the compose ``ollama`` service ($0, no data
  leaves the host).
* ``groq`` / ``anthropic``: hosted providers, used only when their key is set.
"""

import os

DEFAULT_EMAIL_LLM_BACKEND = "template"


def email_llm_backend():
    """The configured backend name, lower-cased; blank means the default."""
    return (os.environ.get("EMAIL_LLM_BACKEND", "") or DEFAULT_EMAIL_LLM_BACKEND).lower()


def make_content_llm_client():
    """Return ``(client_or_None, model)`` for customer-facing copy.

    ``None`` means "use the deterministic template": either the backend is
    ``template`` or a hosted backend has no key.
    """
    from .email_generator import EmailGenerator

    client, _provider, model = EmailGenerator._build_client(
        email_llm_backend(), os.environ.get("EMAIL_LLM_MODEL", "") or ""
    )
    return client, model
