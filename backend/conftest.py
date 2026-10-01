import pytest


@pytest.fixture(autouse=True)
def _isolate_email_llm_client(monkeypatch):
    """Give every test a fresh email LLM client built from a clean environment.

    EmailGenerator memoizes its client per process, so a client built (or
    mocked) in one test would otherwise be handed to the next. A developer's
    .env can also select a local backend (EMAIL_LLM_BACKEND=ollama) that the
    tests do not expect; CI never sets these variables.
    """
    from apps.email_engine.services import email_generator

    monkeypatch.delenv("EMAIL_LLM_BACKEND", raising=False)
    monkeypatch.delenv("EMAIL_LLM_MODEL", raising=False)
    email_generator._CLIENT_CACHE.clear()
    yield
    email_generator._CLIENT_CACHE.clear()
