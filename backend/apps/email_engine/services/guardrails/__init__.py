"""Guardrails package — compliance checks for generated emails.

Split into:
  - patterns.py: regex tables (discriminatory terms, AI giveaways, dignity, etc.)
  - engine.py: GuardrailChecker class with all check_* methods

Re-export the class so `from apps.email_engine.services.guardrails import GuardrailChecker`
keeps working after the module → package conversion.
"""

from .engine import GuardrailChecker

__all__ = ["GuardrailChecker"]
