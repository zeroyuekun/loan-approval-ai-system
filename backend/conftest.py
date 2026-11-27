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
    monkeypatch.setattr(email_generator, "_CLIENT_CACHE", {})


@pytest.fixture(autouse=True)
def _no_live_full_denial_screen(settings):
    """Keep the every-denial bias LLM screen off unless a test turns it on.

    BiasDetector.analyze would otherwise call the bias LLM for every denial a
    test runs through the real detector: a live Ollama in a developer's stack,
    or an outage fallback (email held) in CI. Tests of that screen set
    BIAS_SCREEN_EVERY_DENIAL=True and fake the call
    (tests/test_bias_every_denial_screen.py).
    """
    settings.BIAS_SCREEN_EVERY_DENIAL = False
